"""Persistent alerts with incident cooldown and conservative delivery recovery.

Once a network send starts, ambiguous failures are marked unknown; they are
never automatically resent. Failures before sending can be retried safely.
"""
from app.bootstrap.timebase import business_now

import datetime as dt
import html
import json
import logging
import os
import threading
import time
import uuid

from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import is_failure
from app.bootstrap.helpers import get_runtime_env

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_started = False


def enqueue_result(db, record, output):
    if get_runtime_env() != 'production':
        return
    pid, ended = record['pid'], dt.datetime.fromisoformat(record['end_time'])
    if db.dialect == 'PostgreSQL':
        import hashlib
        key = int.from_bytes(hashlib.sha256(('wfs-alert:'+pid).encode()).digest()[:8], 'big', signed=True)
        db.execute_query_sql('SELECT pg_advisory_xact_lock(CAST(? AS BIGINT))',params=(key,))
    elif not db._local_sqlite:
        db.execute_sql('LOCK TABLE wfs_alert_incidents IN EXCLUSIVE MODE')
    previous = db.execute_query_sql('SELECT incident,last_alert_at FROM wfs_alert_incidents WHERE pid=?', params=(pid,))
    if is_failure(record.get('state')):
        kind = 'failure'
        incident = previous[0][0] if previous else uuid.uuid4().hex
        cooldown = max(60,int(os.environ.get('WFS_ALERT_COOLDOWN_SECONDS','1800')))
        if previous and (ended-dt.datetime.fromisoformat(str(previous[0][1]))).total_seconds() < cooldown:
            db.execute_sql('UPDATE wfs_alert_incidents SET failures=failures+1 WHERE pid=?',params=(pid,))
            return
        if previous:
            db.execute_sql('UPDATE wfs_alert_incidents SET last_alert_at=?,failures=failures+1 WHERE pid=?',params=(ended,pid))
        else:
            db.execute_sql('INSERT INTO wfs_alert_incidents(pid,incident,opened_at,last_alert_at,failures) VALUES(?,?,?,?,1)',params=(pid,incident,ended,ended))
    elif record.get('state') == 0 and previous:
        kind,incident = 'recovery',previous[0][0]
        db.execute_sql('DELETE FROM wfs_alert_incidents WHERE pid=?',params=(pid,))
    else:
        return
    rows = db.execute_query_sql('SELECT sms_receiver,email_receiver FROM wfs_job_stats WHERE pid=?',params=(pid,))
    if not rows:
        return
    for channel,receiver in zip(('sms','email'),rows[0]):
        if not receiver:
            continue
        payload = json.dumps({'receiver':receiver,'task_name':record['task_name'],'output':output[:64000]},ensure_ascii=False)
        identifier = record['run_id']+':'+channel+':'+kind
        if not db.execute_query_sql('SELECT 1 FROM wfs_notifications WHERE id=?',params=(identifier,)):
            db.execute_sql('INSERT INTO wfs_notifications(id,pid,channel,status,attempts,created_at,due_at,payload,message,kind,incident) VALUES(?,?,?,\'pending\',0,?,?,?,\'\',?,?)',
                           params=(identifier,pid,channel,ended,ended,payload,kind,incident))


def _resolve(db, receiver, channel):
    from app.bootstrap.core import getReceiverList
    return getReceiverList(receiver,'telephone' if channel == 'sms' else 'email',db.get_connection())


def _send(channel,recipients,pid,payload,kind):
    label = '执行恢复' if kind == 'recovery' else '执行失败'
    if channel == 'sms':
        from app.common.sms import send_sms
        if not send_sms(recipients,f'WFS任务 {pid} {label}。\n{payload["output"][:200]}'):
            return False
    else:
        from app.common.mail import send_mail
        send_mail(to_receivers=recipients,subject=f'WFS任务 {payload["task_name"] or pid} {label}',
                  body=f'PID: {html.escape(pid)}<br/><pre>{html.escape(payload["output"])}</pre>')
    return True


def process_batch(limit=20, recover=False):
    with _lock, GaussDB() as db:
        if recover:
            db.execute_sql("UPDATE wfs_notifications SET status='unknown',message='服务重启前发送未确认；请核对网关记录，系统不会自动重发。' WHERE status='sending'")
        rows = db.execute_query_sql("SELECT id,pid,channel,payload,kind,attempts FROM wfs_notifications WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT ?",params=(business_now(),limit))
        for identifier,pid,channel,raw,kind,attempts in rows:
            payload = json.loads(raw)
            try:
                recipients = _resolve(db,payload['receiver'],channel)
                if not recipients:
                    raise ValueError('没有可用的接收人')
            except Exception as exc:
                attempts += 1
                db.execute_sql('UPDATE wfs_notifications SET attempts=?,status=?,due_at=?,message=? WHERE id=?',
                               params=(attempts,'failed' if attempts>=5 else 'pending',business_now()+dt.timedelta(seconds=min(3600,30*2**attempts)),str(exc)[:1000],identifier))
                continue
            # Autocommit before network I/O: a crash now must not cause resend.
            db.execute_sql("UPDATE wfs_notifications SET status='sending',attempts=attempts+1 WHERE id=? AND status='pending'",params=(identifier,))
            try:
                accepted = _send(channel,recipients,pid,payload,kind)
                status,message = ('sent','网关已接受') if accepted else ('unknown','网关未确认；请核对发送记录后人工处理。')
            except Exception as exc:
                status,message = 'unknown',str(exc)[:1000]
            db.execute_sql('UPDATE wfs_notifications SET status=?,message=? WHERE id=?',params=(status,message,identifier))
    return len(rows)


def start_notifications():
    global _started
    if get_runtime_env() != 'production' or _started:
        return
    _started = True
    def loop():
        recover = True
        while True:
            try:
                process_batch(recover=recover)
                recover = False
            except Exception:
                logger.exception('persistent notification delivery unavailable')
            time.sleep(5)
    threading.Thread(target=loop,name='wfs-notifications',daemon=True).start()
