"""Persistent single-host admission policy and conservative request receipts.

A pending receipt is never automatically replayed after a crash: callers must
inspect execution records. This provides duplicate prevention, not exactly-once
business side effects. All scheduling processes must share WFS_DATA_DIR.
"""
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from app.bootstrap.timebase import business_now

lock = threading.RLock()

@contextmanager
def store():
    from app.bootstrap.global_vars import DATA_DIR
    path = Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'admission.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        if os.name != 'nt': path.chmod(0o600)
        db.executescript("""CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts(actor TEXT,key TEXT,pid TEXT,status TEXT,run_id TEXT,message TEXT,
        created_at TEXT,PRIMARY KEY(actor,key));""")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally: db.close()

def policy(key, default):
    with store() as db:
        row = db.execute('SELECT payload FROM settings WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default

def maintenance():
    return policy('maintenance',dict(enabled=False, revision=0, reason='', actor='', updated_at=''))

def set_maintenance(enabled, revision, reason, actor):
    if not isinstance(enabled,bool) or not isinstance(reason,str) or len(reason)>500:
        raise ValueError('维护状态或原因无效。')
    with lock, store() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT payload FROM settings WHERE key='maintenance'").fetchone()
        current=json.loads(row[0]) if row else {'revision':0}
        if revision != current['revision']: raise RuntimeError('维护状态已变化，请刷新。')
        value=dict(enabled=enabled,revision=revision+1,reason=reason.strip(),actor=actor,updated_at=str(business_now()))
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('maintenance',json.dumps(value)))
    return value

class CapacityUnavailable(ValueError):
    pass

class MaintenanceClosed(RuntimeError):
    pass

def ensure_open():
    if maintenance()['enabled']: raise MaintenanceClosed('平台处于维护模式，暂不接受新的执行。')

def manual_request(actor, pid, key, submit):
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',key):
        raise ValueError('执行请求编号无效，请刷新后重试。')
    with lock:
        with store() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT pid,status,run_id,message FROM receipts WHERE actor=? AND key=?',(actor,key)).fetchone()
            if row:
                if row[0]!=pid: raise RuntimeError('请求编号已用于其他任务。')
                if row[1]=='accepted': return dict(run_id=row[2],replayed=True,message='已找到原执行记录')
                raise RuntimeError(row[3] or '原请求结果待核对，请查看执行记录；不会重复启动。')
            ensure_open()
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?)',(actor,key,pid,'pending','','',str(business_now())))
        try: run_id=submit()
        except (CapacityUnavailable,MaintenanceClosed):
            with store() as db: db.execute('DELETE FROM receipts WHERE actor=? AND key=?',(actor,key))
            raise
        except Exception:
            with store() as db:
                db.execute("UPDATE receipts SET status='unknown',message=? WHERE actor=? AND key=?",
                           ('执行未确认，请核对任务记录后发起新请求。',actor,key))
            raise
        with store() as db:
            db.execute("UPDATE receipts SET status='accepted',run_id=? WHERE actor=? AND key=?",(run_id,actor,key))
        return dict(run_id=run_id,replayed=False,message='任务已排队')

def grant(pid):
    return policy('connections:'+pid,dict(mode='legacy',connections=[],revision=0))

def save_grant(pid, form, actor):
    from app.bootstrap.connection_settings import profiles
    ids=form.get('connections',[]); mode=form.get('mode')
    if mode not in ('legacy','restricted') or not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) for i in ids):
        raise ValueError('连接授权格式无效。')
    available=profiles()
    if any(i=='platform' or i not in available for i in ids): raise ValueError('请选择已配置的业务连接。')
    with store() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT payload FROM settings WHERE key=?',('connections:'+pid,)).fetchone()
        old=json.loads(row[0]) if row else {'revision':0}
        if form.get('revision')!=old['revision']: raise RuntimeError('授权已变化，请刷新。')
        value=dict(mode=mode,connections=sorted(set(ids)),revision=old['revision']+1,actor=actor,updated_at=str(business_now()))
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('connections:'+pid,json.dumps(value)))
    return value

def connection_environment(pid):
    access=grant(pid)
    if access['mode']=='legacy': return None
    from app.bootstrap.connection_settings import business_profile
    selected={}
    for identifier in access['connections']:
        profile=business_profile(identifier)
        if not profile: raise ValueError('任务授权连接已不存在：'+identifier)
        selected[identifier]=profile
    payload=json.dumps(selected,ensure_ascii=True)
    if len(payload)>60000: raise ValueError('任务授权连接信息过多，请减少授权范围。')
    return payload
