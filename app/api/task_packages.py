"""Authenticated package administration and read-only release inspection."""
from flask import Blueprint, g, request, send_file, Response
import os
import requests
from urllib.parse import urljoin
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap import task_packages as packages
blueprint = Blueprint('task_packages', __name__)
BASE = '/api/taskinfo/packages'

@blueprint.before_request
def guard_and_forward():
    if request.method not in ('GET', 'HEAD'):
        if request.content_length is None or request.content_length > 100000:
            return (error_msg('请求内容过大。'), 413)
        allowed = {name.strip() for name in os.environ.get('WFS_TASK_PUBLISHERS', '').split(',') if name.strip()}
        if allowed and g.identity['username'] not in allowed:
            return (error_msg('此账户未获得任务发布权限。'), 403)
    from app.api.task.views import _scheduler_control_enabled, _internal_auth_headers, WFS_SCHEDULER_CONTROL_URL
    if not _scheduler_control_enabled():
        return None
    g.audit_forwarded = True
    headers = _internal_auth_headers()
    arguments = {'params': request.args, 'timeout': 60}
    if request.method not in ('GET', 'HEAD'):
        arguments['json'] = request.get_json(silent=True)
    try:
        response = requests.request(request.method, urljoin(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/', request.path.lstrip('/')), headers=headers, **arguments)
    except requests.RequestException:
        return (error_msg('调度服务暂时不可用，请稍后重试。'), 503)
    if response.headers.get('Content-Type', '').startswith('application/json'):
        return (response.json(), response.status_code)
    if request.path.endswith(('/download', '/example')) and response.ok:
        return Response(response.content, status=response.status_code, headers={key: value for key, value in response.headers.items() if key.lower() in ('content-type', 'content-disposition')})
    return (error_msg('调度服务返回了无效内容。'), 502)

@blueprint.errorhandler(packages.PackageError)
def package_error(exc):
    return (error_msg(str(exc)), exc.status)

@blueprint.get(BASE)
def index():
    pid = request.args.get('pid')
    if pid and pid not in packages.registry():
        return success_msg({'task': None, 'versions': []})
    return success_msg(packages.overview(pid))

@blueprint.get(BASE + '/example')
def example_package():
    import io
    import zipfile
    from pathlib import Path
    examples = {'outputs': 'file_output', 'nested': 'nested_report', **{name: 'feature_suite/' + name for name in ('report_flow', 'database_transaction', 'retry_once', 'business_backfill', 'queue_observer', 'business_connection')}}
    kind = request.args.get('kind', 'outputs')
    if kind not in examples:
        raise packages.PackageError('示例类型不存在。', 404)
    root = Path(__file__).resolve().parents[2] / 'examples/tasks' / examples[kind]
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file() and (not path.is_symlink()) and ('__pycache__' not in path.parts) and (path.name != '.wfs-task.json'):
                archive.write(path, path.relative_to(root).as_posix())
    result.seek(0)
    return send_file(result, mimetype='application/zip', as_attachment=True, download_name=f'{kind}-task-example.zip')

@blueprint.get(BASE + '/preview')
def preview():
    return success_msg(packages.preview(request.args.get('pid'), request.args.get('version'), request.args.get('path')))

@blueprint.get(BASE + '/download')
def download():
    pid, version = (request.args.get('pid'), request.args.get('version'))
    return send_file(packages.download(pid, version), mimetype='application/zip', as_attachment=True, download_name=f'{pid}-{version[:8]}.zip')

def _audit(action, pid, version=''):
    from app.bootstrap.operations import audit
    audit(g.identity['username'], 'package_' + action, pid, details=version)
    g.audit_forwarded = True

@blueprint.route(BASE + '/gitlab', methods=['GET', 'POST'])
def gitlab_tasks():
    from app.bootstrap import gitlab_tasks as tasks
    from app.bootstrap.gitlab_updates import GitLabError
    try:
        if request.method == 'GET':
            data = tasks.changes()
            if g.identity['role'] == 'maintainer':
                from app.bootstrap.task_access import for_task
                data['items'] = [i for i in data['items'] if 'publish' in for_task(g.identity, i['pid'], i.get('group_name'))]
            return success_msg(data)
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise packages.PackageError('请求内容必须为对象。')
        actor = g.identity['username']
        if body.get('action') == 'stage':
            if 'pid' in body or 'task_id' in body:
                raise packages.PackageError('任务标识由平台生成，不可修改。')
            result = tasks.stage(body.get('id'), actor, body.get('configuration'))
        elif body.get('action') == 'delete':
            result = tasks.remove(body.get('id'), actor)
        elif body.get('action') == 'recover':
            if g.identity['role'] != 'admin':
                raise packages.PackageError('仅管理员可以恢复任务目录关联。', 403)
            result = tasks.recover(body.get('id'), actor)
        else:
            raise packages.PackageError('无效的 GitLab 任务操作。')
        _audit('gitlab_' + body['action'], result['pid'], result.get('version', ''))
        return success_msg(result)
    except GitLabError as exc:
        return (error_msg(str(exc)), exc.status)

@blueprint.post(BASE + '/action')
def action():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise packages.PackageError('请求内容必须为对象。')
    pid, action = (body.get('pid'), body.get('action'))
    if not isinstance(pid, str) or not packages.IDENTIFIER.fullmatch(pid):
        raise packages.PackageError('请提供有效的任务编号。')
    version = body.get('version', '')
    actor = g.identity['username']
    if action == 'prepare':
        result = packages.prepare(pid, version, body.get('main_file', ''), body.get('requirements'))
    elif action in ('publish', 'rollback', 'trash', 'restore', 'rebuild'):
        revision = body.get('revision')
        if type(revision) is not int or revision < 1:
            raise packages.PackageError('请携带当前任务状态版本号。', 409)
        if action == 'rebuild':
            result = packages.rebuild(pid, version, revision, actor)
        elif action in ('publish', 'rollback'):
            result = packages.publish(pid, version, revision, actor, rollback=action == 'rollback', reason=body.get('reason', ''))
        else:
            result = packages.recycle(pid, revision, actor, restore=action == 'restore')
    else:
        raise packages.PackageError('无效操作。')
    _audit(action, pid, result.get('version', version))
    return success_msg(result)
