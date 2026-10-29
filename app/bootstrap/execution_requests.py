"""Explicit, durable execution requests; ambiguous dispatch is never replayed."""
import datetime as dt
import hashlib
import json
import logging
import threading
import time
import uuid
from app.bootstrap import admission
from app.bootstrap.operational_policy import load, parameters
from app.bootstrap.timebase import business_now

logger=logging.getLogger(__name__)
_started=False

def table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS work_requests(id TEXT PRIMARY KEY,pid TEXT NOT NULL,
        kind TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,
        due_at TEXT NOT NULL,run_id TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '')""")
    db.execute('CREATE INDEX IF NOT EXISTS work_requests_due ON work_requests(status,due_at)')

def snapshot(pid=None):
    with admission.store() as db:
        table(db)
        rows=db.execute("SELECT id,pid,kind,status,payload,created_at,due_at,run_id,message FROM work_requests "+
                        ('WHERE pid=? ' if pid else '')+'ORDER BY created_at DESC LIMIT 100',(pid,) if pid else ()).fetchall()
    return [dict(zip(('id','pid','kind','status','context','created_at','due_at','run_id','message'),r)) for r in rows]

def enqueue(pid,kind,context,actor,identifier=None,delay=0):
    policy=load('task',pid)
    if kind not in ('trial','backfill','manual','retry'): raise ValueError('执行类型无效。')
    if kind in ('backfill','retry') and not policy['idempotent']:
        raise ValueError('此任务未声明可安全重复执行，不能重试或补跑。')
    if kind!='retry' and admission.maintenance()['enabled']: raise RuntimeError('维护期间不能提交新的执行请求。')
    context=dict(context)
    context['parameters']=parameters(context.get('parameters',policy['parameters']))
    context.update(source=kind,actor=actor)
    if kind=='backfill':
        try: day=dt.date.fromisoformat(context.get('business_date',''))
        except (ValueError,TypeError): raise ValueError('请提供 YYYY-MM-DD 业务日期。') from None
        if day>business_now().date(): raise ValueError('补跑日期不能在未来。')
    identifier=identifier or uuid.uuid4().hex
    if not isinstance(identifier,str) or not identifier or len(identifier)>100: raise ValueError('请求编号无效。')
    now=business_now()
    with admission.store() as db:
        table(db)
        encoded=json.dumps(context,ensure_ascii=False)
        existing=db.execute('SELECT pid,kind,payload FROM work_requests WHERE id=?',(identifier,)).fetchone()
        if existing:
            if existing!=(pid,kind,encoded): raise RuntimeError('请求编号已被其他内容使用。')
            return identifier
        db.execute('INSERT INTO work_requests(id,pid,kind,status,payload,created_at,due_at) VALUES(?,?,?,?,?,?,?)',
                   (identifier,pid,kind,'pending',encoded,str(now),str(now+dt.timedelta(seconds=delay))))
    return identifier

def retry_result(record):
    if record['status']!='failed' or record.get('source')=='trial': return
    policy=load('task',record['pid'])
    attempt=int(record.get('retry_attempt',0))
    if (record['status']!='failed' or record.get('source')=='trial' or not policy['idempotent'] or
        not policy['retry_enabled'] or attempt>=policy['retry_limit'] or not record.get('code_version',{}).get('task_release')):
        return
    key='retry_'+record['run_id']
    with admission.store() as db:
        table(db)
        if db.execute('SELECT 1 FROM work_requests WHERE id=?',(key,)).fetchone(): return
    enqueue(record['pid'],'retry',dict(version=record['code_version']['task_release'],
            retry_of=record['run_id'],retry_attempt=attempt+1,business_date=record.get('business_date',''),
            parameters=record.get('parameters',policy['parameters'])), 'automatic-retry',identifier=key,
            delay=policy['retry_delay']*2**attempt)

def dispatch(recover=False):
    with admission.store() as db:
        table(db)
        if recover:
            db.execute("UPDATE work_requests SET status='unknown',message='重启前派发未确认；请核对执行记录，不会自动重放。' WHERE status='dispatching'")
    if admission.maintenance()['enabled']: return
    with admission.store() as db:
        rows=db.execute("SELECT id,pid,kind,payload FROM work_requests WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT 10",(str(business_now()),)).fetchall()
    for identifier,pid,kind,raw in rows:
        context=json.loads(raw)
        with admission.store() as db:
            cursor=db.execute("UPDATE work_requests SET status='dispatching' WHERE id=? AND status='pending'",(identifier,))
            if not cursor.rowcount: continue
        try:
            if kind=='retry':
                policy=load('task',pid)
                if not policy['retry_enabled'] or not policy['idempotent'] or context['retry_attempt']>policy['retry_limit']:
                    raise ValueError('重试策略已停用或改变。')
            from app.bootstrap.core import call_task_once
            result=admission.manual_request(context['actor'],pid,identifier,
                lambda:call_task_once(pid,actor=context['actor'],context={**context,'request_id':identifier}))
            status,run_id,message='accepted',result['run_id'],''
        except (admission.CapacityUnavailable,admission.MaintenanceClosed):
            with admission.store() as db: db.execute("UPDATE work_requests SET status='pending',due_at=? WHERE id=?",(str(business_now()+dt.timedelta(seconds=5)),identifier))
            continue
        except Exception as exc:
            status,run_id,message='unknown','',str(exc)[:500]
        with admission.store() as db:
            db.execute('UPDATE work_requests SET status=?,run_id=?,message=? WHERE id=?',(status,run_id,message,identifier))

def cancel(identifier):
    with admission.store() as db:
        table(db)
        result=db.execute("UPDATE work_requests SET status='cancelled' WHERE id=? AND status='pending'",(identifier,))
        if not result.rowcount: raise RuntimeError('请求已派发或状态改变，不能取消。')

def start():
    global _started
    if _started: return
    _started=True
    def loop():
        recover=True
        while True:
            try: dispatch(recover);recover=False
            except Exception: logger.exception('execution request dispatch unavailable')
            time.sleep(5)
    threading.Thread(target=loop,name='wfs-execution-requests',daemon=True).start()
