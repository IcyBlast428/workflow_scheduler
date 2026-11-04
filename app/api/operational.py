"""Operational workflows, split from the legacy task API."""
import json
from flask import Blueprint, request, g
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap import operational_policy as policy, execution_requests as requests
from app.api.operations import _forward
blueprint = Blueprint('operational', __name__)

@blueprint.before_request
def forward():
    if request.content_length and request.content_length > 100000:
        return (error_msg('请求内容过大。'), 413)
    return _forward()

@blueprint.errorhandler(ValueError)
def invalid(exc):
    return (error_msg(str(exc)), 400)

@blueprint.errorhandler(RuntimeError)
def conflict(exc):
    return (error_msg(str(exc)), 409)

def task_id():
    from app.bootstrap.task_packages import task
    pid = request.args.get('pid', '')
    record = task(pid)
    if record.get('deleted_at'):
        raise ValueError('任务已删除。')
    return pid

def audit(action, target, details=''):
    from app.bootstrap.operations import audit as record
    record(g.identity['username'], action, target, details=details)
    g.audit_forwarded = True


@blueprint.route('/api/admin/operational/log-storage', methods=['GET', 'POST'])
def log_storage():
    from app.bootstrap import log_storage as logs
    if request.method == 'GET':
        return success_msg(logs.preview(int(request.args.get('days', 90))))
    value = logs.execute(request.get_json(silent=True) or {})
    audit('log_cleanup', 'platform', json.dumps(value, ensure_ascii=False))
    return success_msg(value)

@blueprint.route('/api/admin/operational/policy/<kind>', methods=['GET', 'POST'])
def operational_policy(kind):
    if kind not in ('task', 'release', 'groups', 'dispatch'):
        raise ValueError('未知策略。')
    pid = task_id() if kind == 'task' else ''
    if request.method == 'POST':
        value = policy.save(kind, pid, request.get_json(silent=True) or {}, g.identity['username'])
        audit('policy_' + kind, pid or 'platform', str(value['revision']))
    return success_msg(policy.load(kind, pid))

@blueprint.route('/api/admin/operational/requests', methods=['GET', 'POST'])
def execution_requests():
    if request.method == 'GET':
        return success_msg(requests.snapshot(request.args.get('pid')))
    form = request.get_json(silent=True) or {}
    if form.get('action') == 'cancel':
        requests.cancel(form.get('id', ''))
        audit('cancel_request', form.get('id', ''))
        return success_msg({})
    pid = task_id()
    from app.bootstrap.task_packages import task, release
    record = task(pid)
    kind = form.get('kind')
    context = dict(form.get('context') or {})
    if kind == 'trial':
        version = context.get('version')
        data = release(pid, version)
        if data['status'] not in ('ready', 'applied'):
            raise ValueError('试运行版本尚未检查通过。')
        context['version'] = version
    elif kind in ('backfill', 'manual'):
        if not record.get('active_version'):
            raise ValueError('任务尚未发布。')
        context['version'] = record['active_version']
    else:
        raise ValueError('请选择试运行、手动执行或按业务日期补跑。')
    identifier = requests.enqueue(pid, kind, context, g.identity['username'], form.get('request_id'))
    audit('request_' + kind, pid, identifier)
    return success_msg({'id': identifier, 'message': '请求已保存，调度器将按容量派发。'})

@blueprint.get('/api/admin/operational/connections')
def connection_usage():
    from app.bootstrap.connection_lifecycle import summary
    return success_msg(summary())

@blueprint.post('/api/admin/operational/connection')
def connection_action():
    from app.bootstrap.connection_lifecycle import change
    form = request.get_json(silent=True) or {}
    change(form.get('id'), form.get('action'), form.get('revision'), form.get('confirm'), g.identity['username'])
    audit('connection_' + form.get('action', ''), form.get('id', ''))
    return success_msg({'message': '连接状态已更新，下次建立连接时生效。'})

@blueprint.route('/api/admin/operational/notifications', methods=['GET', 'POST'])
def notification_resolution():
    from app.bootstrap.database import GaussDB
    from app.bootstrap import admission
    if request.method == 'GET':
        with GaussDB() as db:
            rows = db.execute_query_sql("SELECT id,pid,channel,status,message,created_at FROM wfs_notifications WHERE status IN ('unknown','failed','pending','sending','resolved_sent','resolved_not_sent','resolved_manual') ORDER BY CASE WHEN status IN ('unknown','failed','pending','sending') THEN 0 ELSE 1 END,created_at DESC LIMIT 100", return_json=True)
        return success_msg([{**r, 'created_at': str(r['created_at']), 'resolution': admission.policy('notification:' + r['id'], {})} for r in rows])
    form = request.get_json(silent=True) or {}
    identifier = form.get('id', '')
    note = form.get('note', '')
    outcome = form.get('outcome')
    if outcome not in ('confirmed_sent', 'confirmed_not_sent', 'dismissed') or not isinstance(note, str) or (not 1 <= len(note.strip()) <= 1000):
        raise ValueError('请选择核对结果，并填写处理说明。')
    with GaussDB() as db:
        db.begin_transaction()
        try:
            suffix = ' FOR UPDATE'
            rows = db.execute_query_sql('SELECT status,message FROM wfs_notifications WHERE id=?' + suffix, params=(identifier,))
            if not rows or rows[0][0] not in ('unknown', 'failed'):
                raise ValueError('只处理发送失败或结果未知的通知；不会重发。')
            transport_status = rows[0][0]
            resolved = {'confirmed_sent': 'resolved_sent', 'confirmed_not_sent': 'resolved_not_sent', 'dismissed': 'resolved_manual'}[outcome]
            summary = '人工核对（原状态 ' + transport_status + '）：' + g.identity['username'] + ' · ' + note.strip() + '；原记录：' + str(rows[0][1])[:500]
            db.execute_sql('UPDATE wfs_notifications SET status=?,message=? WHERE id=?', params=(resolved, summary, identifier))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
    from app.bootstrap.timebase import business_now
    value = {'transport_status': transport_status, 'outcome': outcome, 'note': note.strip(), 'actor': g.identity['username'], 'at': str(business_now())}
    with admission.store() as db:
        db.replace('settings', ('key', 'payload'), ('notification:' + identifier, json.dumps(value, ensure_ascii=False)))
    audit('notification_resolution', identifier, json.dumps(value, ensure_ascii=False))
    return success_msg(value)

@blueprint.route('/api/admin/operational/cleanup', methods=['GET', 'POST'])
def cleanup():
    from app.bootstrap.version_cleanup import plan, execute
    if request.method == 'GET':
        return success_msg(plan(int(request.args.get('keep', 20))))
    value = execute(request.get_json(silent=True) or {}, g.identity['username'])
    audit('version_cleanup', 'platform', json.dumps(value, ensure_ascii=False))
    return success_msg(value)

@blueprint.post('/api/admin/operational/issue')
def resolve_issue():
    from app.bootstrap import admission
    from app.bootstrap.timebase import business_now
    form = request.get_json(silent=True) or {}
    key = form.get('key', '')
    note = form.get('note', '')
    if not isinstance(key, str) or not 1 <= len(key) <= 250 or (not isinstance(note, str)) or (not 1 <= len(note.strip()) <= 1000):
        raise ValueError('请填写有效处理说明。')
    value = {'note': note.strip(), 'actor': g.identity['username'], 'at': str(business_now())}
    with admission.store() as db:
        db.replace('settings', ('key', 'payload'), ('issue:' + key, json.dumps(value, ensure_ascii=False)))
    audit('issue_resolution', key, note)
    from app.bootstrap.snapshot_cache import invalidate
    invalidate()
    return success_msg(value)

@blueprint.get('/api/admin/operational/backup')
def backup_status():
    from app.bootstrap import admission
    return success_msg({'backup': admission.policy('backup:last', {}), 'restore': admission.policy('restore:last', {})})

@blueprint.post('/api/admin/operational/isolation-probe')
def isolation_probe():
    from app.bootstrap.task_isolation import probe
    return success_msg(probe())

@blueprint.get('/api/admin/operational/dispatch')
def dispatch_status():
    return success_msg(requests.queue_status(request.args.get('status', ''), request.args.get('query', ''), int(request.args.get('page', '1')), include_names=True))

@blueprint.route('/api/taskinfo/tags', methods=['GET', 'POST'])
def task_tags():
    from app.bootstrap import task_schema as schema
    pid = request.args.get('pid', '')
    schema.spec(pid)
    if request.method == 'POST':
        value = schema.save_tags(pid, request.get_json(silent=True) or {}, g.identity['username'])
        audit('task_tags', pid)
        from app.bootstrap.snapshot_cache import invalidate
        invalidate()
        return success_msg(value)
    return success_msg(schema.tags(pid))

@blueprint.route('/api/taskinfo/ddl', methods=['GET', 'POST'])
def task_ddl():
    from app.bootstrap import task_schema as schema
    pid = request.args.get('pid', '')
    schema.spec(pid)
    if request.method == 'GET':
        current = schema.current(pid)
        return success_msg(dict(current=current, history=schema.history(pid), diff=schema.diff(current['base'], current['content']), file=schema.FILE))
    form = request.get_json(silent=True) or {}
    action = form.get('action', 'save')
    actor = g.identity['username']
    if action == 'save':
        value = schema.save(pid, form, actor)
    elif action == 'import':
        _, _, _, content, _ = schema.remote(pid)
        value = schema.save(pid, dict(revision=form.get('revision'), content=content, note='载入 GitLab 目标分支 DDL'), actor, remote_base=content)
    elif action == 'preview':
        return success_msg(schema.preview(pid, form.get('revision')))
    elif action == 'submit':
        try:
            value = schema.submit(pid, form.get('token'), actor)
        except (ValueError, RuntimeError):
            raise
        except Exception:
            raise RuntimeError('GitLab 提交结果未确认，请核对分支后再操作。') from None
    else:
        raise ValueError('未知 DDL 操作。')
    audit('task_ddl_' + action, pid, str(value.get('revision', value.get('commit', ''))))
    return success_msg(value)
