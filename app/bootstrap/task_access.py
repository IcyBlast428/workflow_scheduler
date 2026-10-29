"""Explicit task operation grants. Existing viewer/operator remain read-only.

Read-only task visibility follows the existing shared workspace model; these
are operation/code grants, not tenant isolation or an untrusted-code boundary.
"""
import json
from flask import request
from app.bootstrap import admission

CAPABILITIES={'run','schedule','publish','view_code'}

def configuration(username):
    from flask import has_request_context,g
    if has_request_context():
        cache=getattr(g,'task_access_cache',None)
        if cache is None: cache={};g.task_access_cache=cache
        if username in cache:return cache[username]
    value=admission.policy('access:'+username,{'revision':0,'tasks':[],'groups':[],'capabilities':[]})
    if has_request_context():cache[username]=value
    return value

def save(username,form,actor):
    from app.bootstrap.permissions import user_record
    user=user_record(username)
    if not user or user['role']!='maintainer': raise ValueError('请先创建任务维护员账户。')
    from app.bootstrap.operational_policy import string_list
    tasks=string_list(form.get('tasks',[]));groups=string_list(form.get('groups',[]));caps=string_list(form.get('capabilities',[]))
    if not set(caps)<=CAPABILITIES: raise ValueError('存在未知任务权限。')
    with admission.store() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT payload FROM settings WHERE key=?',('access:'+username,)).fetchone()
        revision=json.loads(row[0])['revision'] if row else 0
        if form.get('revision')!=revision: raise RuntimeError('授权已变化，请刷新。')
        value={'revision':revision+1,'tasks':tasks,'groups':groups,'capabilities':caps,'actor':actor}
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('access:'+username,json.dumps(value)))
    return value

def for_task(user,pid,group=None):
    if user['role']=='admin': return sorted(CAPABILITIES)
    if user['role']!='maintainer': return []
    value=configuration(user['username'])
    if pid in value['tasks']: return value['capabilities']
    if group is None:
        from app.bootstrap.task_loader import discover_task_specs
        group=next((s.get('group_name') for s in discover_task_specs() if s['pid']==pid),None)
        if group is None:
            from app.bootstrap.gitlab_tasks import changes
            group=next((i.get('group_name') for i in changes().get('items',[]) if i['pid']==pid),None)
    return value['capabilities'] if group in value['groups'] else []

def request_allowed(user):
    path,method=request.path,request.method
    body=request.get_json(silent=True) or {};body=body if isinstance(body,dict) else {}
    from app.bootstrap.permissions import VIEWER_GETS,VIEWER_POSTS
    # Legacy workspace reads are shared. Source and package contents require
    # a separate explicit capability below.
    if method in ('GET','HEAD') and path in VIEWER_GETS or method=='POST' and path in VIEWER_POSTS:
        return True
    pid=request.args.get('pid') or body.get('pid') or request.args.get('id')
    if path=='/api/taskinfo/call_task': capability='run'
    elif path in ('/api/taskinfo/schedule','/api/taskinfo/editTask','/api/taskinfo/restore'): capability='schedule'
    elif path=='/api/taskinfo/batch':
        ids=body.get('ids')
        return isinstance(ids,list) and bool(ids) and all('schedule' in for_task(user,i) for i in ids if isinstance(i,str)) and all(isinstance(i,str) for i in ids)
    elif path in ('/api/taskinfo/source','/api/taskinfo/flow'): capability='view_code'
    elif path.startswith('/api/taskinfo/packages'):
        capability='publish'
        if path.endswith('/gitlab'):
            if method in ('GET','HEAD'): return True
            from app.bootstrap.gitlab_tasks import changes
            item=next((i for i in changes()['items'] if i['id']==body.get('id')),None)
            return bool(item and 'publish' in for_task(user,item['pid'],item.get('group_name')))
        if not pid: return False
    else: return False
    return isinstance(pid,str) and capability in for_task(user,pid)
