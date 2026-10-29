"""Connection usage is explicitly declared; never guess dynamic identifiers."""
import json
from app.bootstrap import admission, connection_settings as settings, operational_policy
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.timebase import business_now

def usage(identifier):
    result=[]
    from app.bootstrap.task_packages import registry
    specs={spec['pid']:spec for spec in discover_task_specs()}
    for pid,record in registry().items():
        if not record.get('deleted_at'):specs.setdefault(pid,{'pid':pid,'task_name':record.get('task_name','')})
    for spec in specs.values():
        pid=spec['pid']; access=admission.grant(pid); policy=operational_policy.load('task',pid)
        if identifier in set(access['connections'])|set(policy['declared_connections'])|set(policy['test_connections'].values()):
            result.append({'pid':pid,'name':spec.get('task_name') or pid,'mode':access['mode']})
    return result

def summary():
    profiles=settings.profiles()
    return [{'id':key,'usage':usage(key),'last_test':admission.policy('connection-test:'+key,{})}
            for key in profiles if key!='platform']

def record_test(identifier,revision,ready,elapsed):
    value={'ready':bool(ready),'elapsed_ms':round(elapsed,1),'at':str(business_now()),'revision':revision}
    with admission.store() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('connection-test:'+identifier,json.dumps(value)))

def change(identifier,action,revision,confirm,actor):
    if identifier=='platform': raise ValueError('平台连接不能通过业务连接生命周期操作修改。')
    with settings._store() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT revision,payload FROM profiles WHERE id=?',(identifier,)).fetchone()
        if not row or row[0]!=revision: raise RuntimeError('连接已变化，请刷新。')
        value=settings._decode(row[1],identifier)
        references=usage(identifier)
        if action=='delete':
            if confirm!=identifier or references or value.get('enabled',True):
                raise ValueError('请先停用连接、解除全部声明/授权/测试映射，并输入连接标识确认。兼容模式中的动态使用仍需人工核对。')
            db.execute('DELETE FROM profiles WHERE id=?',(identifier,))
        elif action in ('disable','enable','archive'):
            value['enabled']=action=='enable'
            value['archived']=action=='archive'
            encrypted=settings._cipher('business').encrypt(json.dumps(value,ensure_ascii=False).encode())
            db.execute('UPDATE profiles SET revision=revision+1,payload=? WHERE id=?',(encrypted,identifier))
        else: raise ValueError('未知连接操作。')
    from app.common.db.engine_pool import dispose
    dispose(identifier)
