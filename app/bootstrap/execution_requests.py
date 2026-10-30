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
_dispatch_lock=threading.Lock()

def table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS work_requests(id TEXT PRIMARY KEY,pid TEXT NOT NULL,
        kind TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,
        due_at TEXT NOT NULL,run_id TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '')""")
    if 'expires_at' not in {row[1] for row in db.execute('PRAGMA table_info(work_requests)')}:
        try: db.execute("ALTER TABLE work_requests ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''")
        except Exception:
            if 'expires_at' not in {row[1] for row in db.execute('PRAGMA table_info(work_requests)')}: raise
    db.execute('CREATE INDEX IF NOT EXISTS work_requests_due ON work_requests(status,due_at)')
    db.execute('CREATE INDEX IF NOT EXISTS work_requests_task ON work_requests(pid,status)')
    db.execute('CREATE INDEX IF NOT EXISTS work_requests_expiry ON work_requests(status,expires_at)')

def snapshot(pid=None):
    with admission.store() as db:
        table(db)
        rows=db.execute("SELECT id,pid,kind,status,payload,created_at,due_at,run_id,message,expires_at FROM work_requests "+
                        ('WHERE pid=? ' if pid else '')+'ORDER BY created_at DESC LIMIT 100',(pid,) if pid else ()).fetchall()
    return [dict(zip(('id','pid','kind','status','context','created_at','due_at','run_id','message','expires_at'),r)) for r in rows]

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
    dispatch_policy=load('dispatch')
    with admission.store() as db:
        table(db)
        encoded=json.dumps(context,ensure_ascii=False)
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT pid,kind,payload FROM work_requests WHERE id=?',(identifier,)).fetchone()
        if existing:
            if existing!=(pid,kind,encoded): raise RuntimeError('请求编号已被其他内容使用。')
            return identifier
        if _full(db,pid,dispatch_policy): raise ValueError('执行队列已满，请处理积压后重试。')
        due=now+dt.timedelta(seconds=delay)
        db.execute('INSERT INTO work_requests(id,pid,kind,status,payload,created_at,due_at,expires_at) VALUES(?,?,?,?,?,?,?,?)',
                   (identifier,pid,kind,'pending',encoded,str(now),str(due),str(due+dt.timedelta(seconds=dispatch_policy['max_wait_seconds']))))
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

def _full(db,pid,policy):
    count=db.execute("SELECT COUNT(*) FROM work_requests WHERE status IN ('pending','dispatching')").fetchone()[0]
    task_count=db.execute("SELECT COUNT(*) FROM work_requests WHERE pid=? AND status IN ('pending','dispatching')",(pid,)).fetchone()[0]
    return count>=policy['max_pending'] or task_count>=policy['max_pending_per_task']


def enqueue_scheduled(job, planned):
    """Persist one automatic firing, with bounded backlog and deterministic identity."""
    from app.bootstrap.timebase import business_time
    from app.bootstrap.task_packages import storage_root
    from pathlib import Path
    pid=job.args[1]
    planned=business_time(planned)
    identifier='schedule_'+hashlib.sha256((pid+'|'+str(planned)).encode()).hexdigest()
    policy=load('dispatch'); task_policy=load('task',pid)
    window=policy['max_wait_seconds']
    if job.misfire_grace_time is not None: window=min(window,job.misfire_grace_time)
    expiry=planned+dt.timedelta(seconds=window)
    stagger=task_policy['stagger_seconds']
    offset=int(hashlib.sha256(pid.encode()).hexdigest(),16)%(stagger+1) if stagger else 0
    due=planned+dt.timedelta(seconds=offset)
    now=business_now()
    version=''
    try:
        parts=Path(job.args[0]).resolve().relative_to(storage_root().resolve()).parts
        if len(parts)>=5 and parts[1]=='releases' and parts[3]=='code': version=parts[2]
    except ValueError: pass
    context=dict(source='scheduled',actor='scheduler',scheduled_time=str(planned),version=version,
                 schedule_revision=(job.kwargs.get('limits') or {}).get('_schedule_revision',0),
                 parameters=task_policy['parameters'],scheduled_args=list(job.args),
                 scheduled_limits=job.kwargs.get('limits') or {})
    with admission.store() as db:
        table(db);db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM work_requests WHERE id=?',(identifier,)).fetchone(): return identifier
        status,message='pending','等待错峰时间。' if offset else '等待执行名额。'
        if now>=expiry: status,message='expired','错过允许启动的时间，未执行。'
        elif due>=expiry: status,message='rejected','错峰偏移超过允许启动窗口，请调整任务错峰设置。'
        elif admission.maintenance()['enabled']: status,message='cancelled','维护期间的自动计划不补跑。'
        elif _full(db,pid,policy): status,message='rejected','执行队列已满，此次计划未接收；请核对业务是否需要补跑。'
        db.execute('INSERT INTO work_requests(id,pid,kind,status,payload,created_at,due_at,expires_at,message) VALUES(?,?,?,?,?,?,?,?,?)',
                   (identifier,pid,'scheduled',status,json.dumps(context,ensure_ascii=False),str(now),str(due),str(expiry),message))
    if status!='pending': logger.warning('scheduled request %s %s: %s',identifier,status,message)
    return identifier


def dispatch(recover=False):
    if not _dispatch_lock.acquire(blocking=False): return
    try: _dispatch(recover)
    finally: _dispatch_lock.release()


def _dispatch(recover=False):
    from app.bootstrap import dispatch_control
    now=business_now()
    with admission.store() as db:
        table(db)
        if recover:
            db.execute("UPDATE work_requests SET status='unknown',message='重启前派发未确认；请核对执行记录，不会自动重放。' WHERE status='dispatching'")
        db.execute("UPDATE work_requests SET status='expired',message='已超过允许启动的时间，未派发；请核对业务是否需要补跑。' WHERE status='pending' AND expires_at<>'' AND expires_at<=?",(str(now),))
        # Retain ambiguous receipts indefinitely; only compact terminal queue history.
        db.execute("DELETE FROM work_requests WHERE id IN (SELECT id FROM work_requests WHERE status IN ('accepted','expired','rejected','cancelled') AND created_at<? LIMIT 1000)",
                   (str(now-dt.timedelta(days=7)),))
    if admission.maintenance()['enabled'] or dispatch_control.reason(include_interval=False): return
    with admission.store() as db:
        rows=db.execute("SELECT id,pid,kind,payload,expires_at FROM work_requests WHERE status='pending' AND due_at<=? ORDER BY due_at,created_at,id LIMIT 100",(str(now),)).fetchall()
    for identifier,pid,kind,raw,expiry in rows:
        if dispatch_control.reason(include_interval=False): break
        context=json.loads(raw)
        if expiry and str(business_now())>=expiry: continue
        with admission.store() as db:
            cursor=db.execute("UPDATE work_requests SET status='dispatching',message='' WHERE id=? AND status='pending'",(identifier,))
            if not cursor.rowcount: continue
        try:
            if kind=='retry':
                policy=load('task',pid)
                if not policy['retry_enabled'] or not policy['idempotent'] or context['retry_attempt']>policy['retry_limit']:
                    raise ValueError('重试策略已停用或改变。')
            from app.bootstrap.core import call_task_once
            result=admission.manual_request(context['actor'],pid,identifier,
                lambda:call_task_once(pid,actor=context['actor'],context={**context,'request_id':identifier,'expires_at':expiry}))
            status,run_id,message='accepted',result['run_id'],''
        except (admission.CapacityUnavailable,admission.MaintenanceClosed) as exc:
            with admission.store() as db:
                db.execute("UPDATE work_requests SET status='pending',due_at=?,message=? WHERE id=?",(str(business_now()+dt.timedelta(seconds=1)),str(exc).replace('本次调度跳过','等待名额').replace('本次计划跳过','等待名额'),identifier))
            continue
        except admission.PlanCancelled as exc:
            status,run_id,message='cancelled','',str(exc)[:500]
        except Exception as exc:
            status,run_id,message='unknown','',str(exc)[:500]
        with admission.store() as db:
            db.execute('UPDATE work_requests SET status=?,run_id=?,message=? WHERE id=?',(status,run_id,message,identifier))


def queue_status(status='',query='',page=1,include_names=False):
    from app.bootstrap import dispatch_control
    valid={'pending','dispatching','accepted','expired','rejected','unknown','cancelled'}
    if status and status not in valid: raise ValueError('未知队列状态。')
    if not isinstance(query,str) or len(query)>200: raise ValueError('搜索条件过长。')
    if type(page) is not int or not 1<=page<=100000: raise ValueError('队列页码无效。')
    names={}
    if include_names or query:
        from app.bootstrap.task_loader import discover_task_specs
        names={s['pid']:s.get('task_name') or s['pid'] for s in discover_task_specs()}
    clauses=[];params=[]
    if status: clauses.append('status=?');params.append(status)
    if query:
        # Name matching happens before pagination, including tasks outside the first page.
        matches=[pid for pid,name in names.items() if query.casefold() in name.casefold()]
        clauses.append('(instr(lower(pid),lower(?))>0 OR pid IN (SELECT value FROM json_each(?)))')
        params.extend((query,json.dumps(matches)))
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    now=business_now();size=25 if include_names else 100
    with admission.store() as db:
        table(db)
        counts=dict(db.execute("SELECT status,COUNT(*) FROM work_requests WHERE status IN ('pending','dispatching','unknown') OR created_at>=? GROUP BY status",(str(now-dt.timedelta(hours=24)),)))
        oldest=db.execute("SELECT MIN(created_at) FROM work_requests WHERE status='pending'").fetchone()[0]
        total=db.execute('SELECT COUNT(*) FROM work_requests'+where,params).fetchone()[0]
        page=min(page,max(1,(total+size-1)//size))
        rows=db.execute("SELECT id,pid,kind,status,created_at,due_at,expires_at,message,run_id FROM work_requests"+where+
                        " ORDER BY CASE WHEN status='pending' THEN 0 WHEN status IN ('expired','rejected','unknown') THEN 1 ELSE 2 END,created_at DESC,id LIMIT ? OFFSET ?",(*params,size,(page-1)*size)).fetchall()
    items=[dict(zip(('id','pid','kind','status','created_at','due_at','expires_at','message','run_id'),row)) for row in rows]
    for item in items:
        item['task_name']=names.get(item['pid'],item['pid'])
        item['wait_seconds']=max(0,int((now-dt.datetime.fromisoformat(item['created_at'])).total_seconds())) if item['status']=='pending' else None
    return dict(dispatch_control.snapshot(),counts=counts,items=items,total=total,page=page,page_size=size,
                oldest_wait_seconds=max(0,int((now-dt.datetime.fromisoformat(oldest)).total_seconds())) if oldest else 0)


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
            try:
                from app.bootstrap.dispatch_control import sample
                sample()
                dispatch(recover);recover=False
            except Exception: logger.exception('execution request dispatch unavailable')
            time.sleep(1)
    threading.Thread(target=loop,name='wfs-execution-requests',daemon=True).start()
