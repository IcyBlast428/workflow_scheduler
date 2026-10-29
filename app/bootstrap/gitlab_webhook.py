"""Bounded token-authenticated GitLab event intake with durable coalescing."""
import hmac
import json
import os
import re
import time
from app.bootstrap import admission, gitlab_updates

def receive(token,event,identifier,body):
    expected=os.environ.get('WFS_GITLAB_WEBHOOK_TOKEN','')
    if len(expected)<32 or not isinstance(token,str) or not hmac.compare_digest(expected,token):
        raise PermissionError('Webhook 验证失败。')
    if event not in ('Push Hook','Tag Push Hook','Merge Request Hook','Pipeline Hook'):
        raise ValueError('不支持此事件。')
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',identifier):
        raise ValueError('缺少有效事件编号。')
    config=gitlab_updates.configuration()
    project=body.get('project') or {}
    if not config['enabled'] or config['project'] not in (str(project.get('id','')),project.get('path_with_namespace')):
        raise ValueError('事件项目与平台配置不匹配。')
    with admission.store() as db:
        db.execute('CREATE TABLE IF NOT EXISTS hook_events(id TEXT PRIMARY KEY,at REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM hook_events WHERE id=?',(identifier,)).fetchone(): return False
        db.execute('DELETE FROM hook_events WHERE at<?',(time.time()-7*86400,))
        db.execute('INSERT INTO hook_events VALUES(?,?)',(identifier,time.time()))
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('gitlab-hook-pending',json.dumps({'id':identifier,'at':time.time()})))
    return True

def request_pending():
    pending=admission.policy('gitlab-hook-pending',{})
    if pending and gitlab_updates.request_scan(force=True):
        with admission.store() as db:
            row=db.execute("SELECT payload FROM settings WHERE key='gitlab-hook-pending'").fetchone()
            if row and json.loads(row[0]).get('id')==pending['id']:
                db.execute("DELETE FROM settings WHERE key='gitlab-hook-pending'")
        return True
    return False
