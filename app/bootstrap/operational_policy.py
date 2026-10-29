"""Versioned operational policy. No credentials belong in these documents."""
import datetime as dt
import json
import math
import re
from app.bootstrap import admission
from app.bootstrap.timebase import business_now

TASK_DEFAULT = dict(revision=0, idempotent=False, retry_enabled=False, retry_limit=0,
                    retry_delay=60, expected_by='', slow_minutes=60, parameters={},
                    declared_connections=[], test_connections={}, isolation='process',
                    resources={'memory_mb':512,'processes':64,'cpu_percent':100})
RELEASE_DEFAULT = dict(revision=0, require_ci=False, required_jobs=[], branches=['*'],
                       window_start='', window_end='', require_trial=False, environment='development')

def load(kind, identifier=''):
    default = TASK_DEFAULT if kind=='task' else RELEASE_DEFAULT if kind=='release' else {'revision':0,'quotas':{}}
    baseline=json.loads(json.dumps(default))
    return {**baseline,**admission.policy(kind+':'+identifier,baseline)}

def save(kind, identifier, form, actor):
    previous=load(kind,identifier)
    if type(form.get('revision')) is not int or form['revision']!=previous['revision']:
        raise RuntimeError('策略已被修改，请刷新后重试。')
    if kind=='task': value=validate_task(form)
    elif kind=='release': value=validate_release(form)
    elif kind=='groups':
        quotas=form.get('quotas',{})
        if not isinstance(quotas,dict) or len(quotas)>200 or any(not isinstance(k,str) or not k or len(k)>100 or type(v)is not int or not 1<=v<=100 for k,v in quotas.items()):
            raise ValueError('分组配额应为分组名称与 1–100 的执行名额。')
        value={'quotas':quotas}
    else: raise ValueError('未知策略类型。')
    value.update(revision=previous['revision']+1, actor=actor, updated_at=str(business_now()))
    with admission.lock, admission.store() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT payload FROM settings WHERE key=?',(kind+':'+identifier,)).fetchone()
        revision=json.loads(row[0])['revision'] if row else 0
        if revision!=previous['revision']: raise RuntimeError('策略已被修改，请刷新。')
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(kind+':'+identifier,json.dumps(value,ensure_ascii=False)))
    return value

def string_list(value, maximum=100):
    if not isinstance(value,list) or len(value)>maximum or any(not isinstance(s,str) or not s.strip() or len(s)>200 for s in value):
        raise ValueError('请填写有效列表。')
    return sorted(set(value))

def parameters(value):
    if not isinstance(value,dict) or len(value)>50:
        raise ValueError('运行参数必须是最多 50 项的 JSON 对象。')
    try: encoded=json.dumps(value,allow_nan=False)
    except (ValueError,TypeError): raise ValueError('运行参数不支持此类型。') from None
    if len(encoded)>16000: raise ValueError('运行参数最多 16 KiB。')
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',k) for k in value):
        raise ValueError('参数名只允许字母开头的字母、数字与下划线。')
    return value

def time_text(value):
    if value and (not isinstance(value,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value)):
        raise ValueError('时间请使用 HH:MM。')
    return value or ''

def validate_task(form):
    value={k:form.get(k,v) for k,v in TASK_DEFAULT.items() if k!='revision'}
    if type(value['idempotent']) is not bool or type(value['retry_enabled']) is not bool:
        raise ValueError('任务幂等与重试开关无效。')
    for key,low,high in [('retry_limit',0,3),('retry_delay',10,86400),('slow_minutes',1,10080)]:
        if type(value[key])is not int or not low<=value[key]<=high: raise ValueError(key+' 超出范围。')
    if value['retry_enabled'] and (not value['idempotent'] or not value['retry_limit']):
        raise ValueError('启用自动重试前须声明可安全重复执行，并设置重试次数。')
    value['expected_by']=time_text(value['expected_by'])
    value['parameters']=parameters(value['parameters'])
    value['declared_connections']=string_list(value['declared_connections'])
    mapping=value['test_connections']
    if not isinstance(mapping,dict) or len(mapping)>50 or any(not isinstance(k,str) or not isinstance(v,str) or not k or not v or len(k)>100 or len(v)>100 or 'platform' in (k,v) for k,v in mapping.items()):
        raise ValueError('测试连接映射应为原连接标识与测试连接标识。')
    if value['isolation'] not in ('process','systemd'): raise ValueError('执行隔离类型无效。')
    resources=value['resources']
    if not isinstance(resources,dict): raise ValueError('隔离资源配置无效。')
    for key,low,high in [('memory_mb',64,32768),('processes',1,1024),('cpu_percent',1,1600)]:
        if type(resources.get(key))is not int or not low<=resources[key]<=high: raise ValueError('隔离资源 '+key+' 超出范围。')
    value['resources']={key:resources[key] for key in ('memory_mb','processes','cpu_percent')}
    return value

def validate_release(form):
    value={k:form.get(k,v) for k,v in RELEASE_DEFAULT.items() if k!='revision'}
    if any(type(value[k])is not bool for k in ('require_ci','require_trial')): raise ValueError('发布门禁开关无效。')
    value['required_jobs']=string_list(value['required_jobs'],50)
    value['branches']=string_list(value['branches'],100)
    if not value['branches']: raise ValueError('至少保留一个关注分支规则。')
    for key in ('window_start','window_end'): value[key]=time_text(value[key])
    if bool(value['window_start'])!=bool(value['window_end']): raise ValueError('请同时填写发布窗口的开始和结束。')
    if value['environment'] not in ('development','test','production'): raise ValueError('请选择部署环境。')
    return value

def quota(group):
    return load('groups')['quotas'].get(group,0)

def in_window(policy):
    start,end=policy['window_start'],policy['window_end']
    if not start: return True
    current=business_now().strftime('%H:%M')
    return start<=current<=end if start<=end else current>=start or current<=end


def all_tasks():
    with admission.store() as db:
        rows=db.execute("SELECT key,payload FROM settings WHERE key LIKE 'task:%'").fetchall()
    return {key[5:]:{**TASK_DEFAULT,**json.loads(raw)} for key,raw in rows}
