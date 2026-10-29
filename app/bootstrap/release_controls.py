"""Read-only CI evidence and server-enforced release gates pinned to Git SHA."""
import json
from app.bootstrap import operational_policy as policy
from app.bootstrap.database import GaussDB

def evidence(data):
    source=data.get('git_source') or {}
    if not source: return {'status':'not_applicable','jobs':[],'message':'此版本没有 GitLab 来源。'}
    from app.bootstrap import gitlab_updates as gitlab
    config=gitlab.configuration()
    client=gitlab.Client(config)
    try:
        pipelines,_=client.get('/pipelines',{'sha':source['sha'],'ref':config['target'],'per_page':1,'order_by':'id','sort':'desc'})
        if not isinstance(pipelines,list) or not pipelines: return {'status':'missing','jobs':[],'message':'没有匹配提交与目标分支的流水线。'}
        pipeline=pipelines[0]
        if pipeline.get('sha')!=source['sha'] or pipeline.get('ref')!=config['target']:
            raise gitlab.GitLabError('流水线提交或目标分支不匹配。')
        if type(pipeline.get('id'))is not int: raise gitlab.GitLabError('流水线编号无效。')
        jobs=[]
        for page in (1,2):
            values,headers=client.get('/pipelines/'+str(pipeline['id'])+'/jobs',{'per_page':100,'page':page,'include_retried':'false'})
            if not isinstance(values,list): raise gitlab.GitLabError('流水线作业响应无效。')
            jobs.extend({'name':str(j.get('name',''))[:200],'status':str(j.get('status',''))[:50]} for j in values[:100])
            if not headers.get('X-Next-Page'): break
        else: raise gitlab.GitLabError('流水线作业超过检查上限。')
        return {'id':pipeline['id'],'sha':source['sha'],'status':pipeline.get('status','unknown'),'jobs':jobs,'message':'GitLab 最近一次匹配流水线。'}
    finally: client.close()

def trial_evidence(pid,version):
    with GaussDB() as db:
        rows=db.execute_query_sql("SELECT payload FROM wfs_executions WHERE pid=? AND status='success' ORDER BY created_at DESC LIMIT 100",params=(pid,))
    for (raw,) in rows:
        run=json.loads(raw)
        if run.get('source')=='trial' and run.get('requested_version')==version:
            return {'passed':True,'run_id':run['run_id'],'at':run.get('end_time','')}
    return {'passed':False}

def preview(data):
    p=policy.load('release')
    result={'environment':p['environment'],'policy_revision':p['revision'],'window_open':policy.in_window(p),
            'require_ci':p['require_ci'],'require_trial':p['require_trial'],'trial':trial_evidence(data['pid'],data['version'])}
    if p['require_ci']:
        try: result['ci']=evidence(data)
        except Exception: result['ci']={'status':'unavailable','jobs':[],'message':'无法核对 GitLab 流水线。'}
    else: result['ci']={'status':'not_required','jobs':[],'message':'尚未启用 CI 发布门禁。'}
    return result

def enforce(data):
    from app.bootstrap.task_packages import PackageError
    p=policy.load('release')
    if not policy.in_window(p): raise PackageError('当前不在允许的发布窗口内。',409)
    if p['require_trial'] and not trial_evidence(data['pid'],data['version'])['passed']:
        raise PackageError('此版本尚无成功试运行记录。',409)
    if p['require_ci']:
        ci=evidence(data)
        if ci['status']!='success': raise PackageError('候选提交的 GitLab 流水线尚未成功。',409)
        jobs={j['name']:j['status'] for j in ci['jobs']}
        if any(jobs.get(name)!='success' for name in p['required_jobs']):
            raise PackageError('必须通过的 CI 作业缺失或未成功。',409)
    return p

def recheck(receipt):
    from app.bootstrap.task_packages import PackageError
    current=policy.load('release')
    if current['revision']!=receipt['revision']:
        raise PackageError('发布策略已变化，请刷新预览并重新检查。',409)
    if not policy.in_window(current):
        raise PackageError('发布窗口已结束，请在允许的时间重新操作。',409)
