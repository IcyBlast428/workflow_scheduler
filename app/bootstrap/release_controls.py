"""Server-enforced trial and time-window release gates."""
import json
from app.bootstrap import operational_policy as policy
from app.bootstrap.database import GaussDB

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
            'require_trial':p['require_trial'],'trial':trial_evidence(data['pid'],data['version'])}
    return result

def enforce(data):
    from app.bootstrap.task_packages import PackageError
    p=policy.load('release')
    if not policy.in_window(p): raise PackageError('当前不在允许的发布窗口内。',409)
    if p['require_trial'] and not trial_evidence(data['pid'],data['version'])['passed']:
        raise PackageError('此版本尚无成功试运行记录。',409)
    return p

def recheck(receipt):
    from app.bootstrap.task_packages import PackageError
    current=policy.load('release')
    if current['revision']!=receipt['revision']:
        raise PackageError('发布策略已变化，请刷新预览并重新检查。',409)
    if not policy.in_window(current):
        raise PackageError('发布窗口已结束，请在允许的时间重新操作。',409)
