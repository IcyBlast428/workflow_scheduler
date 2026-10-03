"""Task details, execution inspection, configuration history and administration."""
import json
import os
import shutil
from pathlib import Path
from flask import Blueprint, request, send_file, g
from werkzeug.security import generate_password_hash
from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap.operations import list_runs, read_run, read_log, run_path
from app.bootstrap.schedule_config import load_schedule, save_schedule, record_application
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.task_source import SourceError, list_source, read_source
from app.bootstrap.permissions import ROLES
from app.settings import AUTH_ADMIN_USERNAME

blueprint = Blueprint('operations', __name__)


@blueprint.get('/api/taskinfo/matrix')
def execution_matrix():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    from app.bootstrap.execution_matrix import cached_snapshot
    try:
        return success_msg(cached_snapshot(request.args.get('date'),request.args.get('cursor')))
    except ValueError as exc:
        return error_msg(str(exc)), 400


def _forward():
    from app.api.task.views import _scheduler_control_enabled, _proxy_scheduler_resource
    if _scheduler_control_enabled():
        return _proxy_scheduler_resource(request.path)


def _apply(pid, data):
    from app.bootstrap.core import aps_start
    record_application(pid, data.get('version', 0), 'pending')
    try:
        aps_start(task_pid=pid, action='refresh')
        record_application(pid, data.get('version', 0), 'applied')
        data['application'] = {'status':'applied', 'message':''}
    except Exception as exc:
        record_application(pid, data.get('version', 0), 'failed', str(exc))
        data['application'] = {'status':'failed', 'message':str(exc)}
    return data


@blueprint.get('/api/taskinfo/detail')
def task_detail():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    pid = request.args.get('pid')
    spec = next((item for item in discover_task_specs() if item['pid'] == pid), None)
    if not spec:
        return error_msg('task not found'), 404
    path = Path(spec['task_dir']) / 'README.md'
    description = path.read_text(encoding='utf-8', errors='replace')[:64000] if path.is_file() else '此任务尚未提供 README.md 说明。'
    with GaussDB() as db:
        versions = db.execute_query_sql('SELECT version,changed_at,changed_by FROM wfs_config_versions WHERE pid=? ORDER BY version DESC LIMIT 20', params=(pid,), return_json=True)
        changes = db.execute_query_sql('SELECT actor,action,outcome,created_at FROM wfs_audit WHERE target=? ORDER BY created_at DESC LIMIT 20', params=(pid,), return_json=True)
    from app.extensions import scheduler
    from app.bootstrap.global_vars import runnings
    records = list_runs(pid)
    job = scheduler.get_job(pid)
    next_time = getattr(job,'next_run_time',None)
    with GaussDB() as db:
        notifications = db.execute_query_sql('SELECT id,channel,status,attempts,message,created_at FROM wfs_notifications WHERE pid=? ORDER BY created_at DESC LIMIT 20',params=(pid,),return_json=True)
    return success_msg({'pid':pid, 'description':description, 'schedule':load_schedule(pid), 'runs':records, 'versions':versions, 'audit':changes,
                        'notifications':notifications,'diagnostics':{'active':runnings.count(),'capacity':int(os.environ.get('WFS_MAX_ACTIVE_RUNS','20')),
                        'next_run_time':str(next_time or ''),'last_not_started':next((item for item in records if item['status'] in ('skipped','missed')),None)}})


@blueprint.post('/api/taskinfo/batch')
def batch_tasks():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    from app.bootstrap.core import serialized_configuration, aps_start
    from app.bootstrap.schedule_config import set_schedule_enabled
    from app.bootstrap.global_vars import ignores, runnings
    from app.bootstrap.operations import audit
    form = request.get_json(silent=True) or {}
    if not isinstance(form, dict):
        return error_msg('批量操作请求格式无效。'),400
    ids,action = form.get('ids'),form.get('action')
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(pid,str) for pid in ids) or len(set(ids))!=len(ids) or action not in ('pause','start'):
        return error_msg('请选取 1 至 100 个任务，并选择暂停或启用。'),400
    @serialized_configuration
    def apply():
        specs = {spec['pid']:spec for spec in discover_task_specs()}
        preview = []
        for pid in ids:
            spec = specs.get(pid)
            if not spec or spec.get('error') or spec.get('main_file_error') or not spec.get('schedule_configured'):
                raise ValueError('任务不存在、配置异常或尚未设置调度：'+pid)
            schedule = load_schedule(pid)
            preview.append({'pid':pid,'name':spec.get('task_name') or spec['folder_name'],'version':schedule['version'],
                            'active':runnings.count(pid),'enabled':schedule['enabled']})
        if form.get('preview',False):
            return {'preview':preview,'action':action}
        versions = form.get('versions')
        if not isinstance(versions,dict) or any(versions.get(item['pid'])!=item['version'] for item in preview):
            raise RuntimeError('预览后配置已变化，请重新预览再操作。')
        results = []
        for item in preview:
            pid = item['pid']
            try:
                set_schedule_enabled(pid,action=='start',actor=g.identity['username'])
                if action=='pause':
                    ignores.add(pid)
                    if scheduler.get_job(pid):
                        scheduler.remove_job(pid)
                else:
                    ignores.remove(pid)
                    aps_start(task_pid=pid,action='start')
                saved = load_schedule(pid)
                record_application(pid,saved['version'],'applied')
                results.append({'pid':pid,'ok':True})
                audit(g.identity['username'],'batch_'+action,pid)
            except Exception as exc:
                results.append({'pid':pid,'ok':False,'message':str(exc)})
                record_application(pid,load_schedule(pid)['version'],'failed',str(exc))
                audit(g.identity['username'],'batch_'+action,pid,'failed',str(exc))
        return {'results':results}
    try:
        return success_msg(apply())
    except ValueError as exc:
        return error_msg(str(exc)),400
    except RuntimeError as exc:
        return error_msg(str(exc)),409


@blueprint.get('/api/admin/runtime')
def runtime_health():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    from app.bootstrap import operations, journal
    from app.bootstrap.run_summary import coverage
    from app.bootstrap.runtime_metrics import snapshot
    with GaussDB() as db:
        alerts = db.execute_query_sql('SELECT status,COUNT(*) FROM wfs_notifications GROUP BY status')
        summary = coverage(db)
    directory = operations._directory
    usage = shutil.disk_usage(directory)
    return success_msg({'journal':journal.health(directory),'maintenance':operations.service_state(),
                        'summary':summary,'alerts':dict(alerts),'free_mb':usage.free//1024//1024,'metrics':snapshot()})


@blueprint.get('/api/taskinfo/runs')
def runs():
    forwarded = _forward()
    return forwarded if forwarded is not None else success_msg(list_runs(request.args.get('pid'), request.args.get('limit',50)))


@blueprint.get('/api/taskinfo/source')
def task_source():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    pid = request.args.get('pid')
    spec = next((item for item in discover_task_specs() if item['pid'] == pid), None)
    if not spec:
        return error_msg('任务不存在。'), 404
    try:
        filename = request.args.get('file')
        return success_msg(read_source(spec, filename) if filename is not None else list_source(spec, request.args.get('dir', ''), request.args.get('offset', 0)))
    except SourceError as exc:
        return error_msg(str(exc)), exc.status
    except OSError:
        return error_msg('任务目录暂时无法读取。'), 503


@blueprint.get('/api/taskinfo/run')
def run_detail():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    try:
        return success_msg(read_log(request.args.get('run_id'), request.args.get('offset',0)))
    except (ValueError, OSError) as exc:
        return error_msg(str(exc)), 404


@blueprint.get('/api/taskinfo/run-download')
def run_download():
    try:
        run_id = request.args.get('run_id')
        read_run(run_id)
        return send_file(run_path(run_id, 'log'), as_attachment=True, download_name=f'execution-{run_id}.log')
    except (ValueError, OSError):
        return error_msg('日志尚未生成或已超过保留期限。'), 404


@blueprint.post('/api/taskinfo/restore')
def restore_configuration():
    forwarded = _forward()
    if forwarded is not None:
        return forwarded
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or payload.get('version') is None:
        return error_msg('请重新打开配置历史再恢复。'), 400
    pid = payload.get('pid')
    try:
        restore_version = int(payload.get('restore_version',0))
    except (TypeError, ValueError):
        return error_msg('配置版本无效。'), 400
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT payload FROM wfs_config_versions WHERE pid=? AND version=?', params=(pid,restore_version))
    if not rows:
        return error_msg('配置版本不存在。'), 404
    form = json.loads(rows[0][0])
    form.update(version=payload.get('version'), updated_by=g.identity['username'])
    try:
        return success_msg(_apply(pid, save_schedule(pid, form)))
    except (ValueError, RuntimeError) as exc:
        return error_msg(str(exc)), 409


@blueprint.get('/api/admin/audit')
def audit_log():
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT actor,action,target,outcome,details,created_at FROM wfs_audit ORDER BY created_at DESC LIMIT 100', return_json=True)
    return success_msg(rows)


@blueprint.route('/api/admin/users', methods=['GET','POST'])
def users():
    if request.method == 'GET':
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT username,role,enabled FROM wfs_users ORDER BY username', return_json=True)
        return success_msg([{'username':AUTH_ADMIN_USERNAME,'role':'admin','enabled':1,'managed_by':'environment'}] + rows)
    form = request.get_json(silent=True) or {}
    if not isinstance(form, dict):
        return error_msg('账户信息无效。'), 400
    username = str(form.get('username') or '').strip()
    role = form.get('role')
    password = form.get('password') or ''
    if not username or len(username) > 100 or username == AUTH_ADMIN_USERNAME or not isinstance(role,str) or role not in ROLES:
        return error_msg('用户名或角色无效；环境管理员不能在这里修改。'), 400
    if username == g.identity['username']:
        return error_msg('请由另一名管理员修改当前账户。'), 400
    if password and (not isinstance(password,str) or not 12 <= len(password) <= 1024):
        return error_msg('密码长度应为 12 至 1024 个字符。'), 400
    with GaussDB() as db:
        db.begin_transaction()
        try:
            previous = db.execute_query_sql('SELECT password_hash FROM wfs_users WHERE username=?', params=(username,))
            if not previous and not password:
                db.set_rollback()
                return error_msg('新账户必须设置密码。'), 400
            password_hash = generate_password_hash(password, method='scrypt') if password else previous[0][0]
            db.execute_sql('DELETE FROM wfs_users WHERE username=?', params=(username,))
            db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,?)', params=(username,password_hash,role,int(bool(form.get('enabled',True)))))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
    return success_msg('账户已保存；权限和禁用状态立即生效。')
