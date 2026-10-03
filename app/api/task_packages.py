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
        allowed = {name.strip() for name in os.environ.get('WFS_TASK_PUBLISHERS', '').split(',') if name.strip()}
        if allowed and g.identity['username'] not in allowed:
            return error_msg('此账户未获得任务发布权限。'), 403
    from app.api.task.views import _scheduler_control_enabled, _internal_auth_headers, WFS_SCHEDULER_CONTROL_URL
    if not _scheduler_control_enabled():
        return None
    g.audit_forwarded = True
    headers = _internal_auth_headers()
    arguments = {'params': request.args, 'timeout': 60}
    if request.mimetype == 'multipart/form-data':
        maximum = packages.limits()['upload_bytes'] + 1024 * 1024
        if request.content_length is None or request.content_length > maximum:
            return error_msg('任务包超过上传限制或缺少大小信息。'), 413
        headers['Content-Type'] = request.headers['Content-Type']
        arguments['data'] = request.get_data()
    elif request.method not in ('GET', 'HEAD'):
        arguments['json'] = request.get_json(silent=True)
    try:
        response = requests.request(request.method, urljoin(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/', request.path.lstrip('/')),
                                    headers=headers, **arguments)
    except requests.RequestException:
        return error_msg('调度服务暂时不可用，请稍后重试。'), 503
    if response.headers.get('Content-Type', '').startswith('application/json'):
        return response.json(), response.status_code
    if request.path.endswith('/download') and response.ok:
        return Response(response.content, status=response.status_code, headers={
            key: value for key, value in response.headers.items() if key.lower() in ('content-type', 'content-disposition')})
    return error_msg('调度服务返回了无效内容。'), 502


@blueprint.errorhandler(packages.PackageError)
def package_error(exc):
    return error_msg(str(exc)), exc.status


@blueprint.get(BASE)
def index():
    return success_msg(packages.overview(request.args.get('pid')))


@blueprint.get(BASE + '/preview')
def preview():
    return success_msg(packages.preview(request.args.get('pid'), request.args.get('version'), request.args.get('path')))


@blueprint.get(BASE + '/download')
def download():
    pid, version = request.args.get('pid'), request.args.get('version')
    return send_file(packages.download(pid, version), mimetype='application/zip', as_attachment=True,
                     download_name=f'{pid}-{version[:8]}.zip')


def _audit(action, pid, version=''):
    from app.bootstrap.operations import audit
    audit(g.identity['username'], 'package_' + action, pid, details=version)
    g.audit_forwarded = True


@blueprint.post(BASE + '/upload')
def upload():
    maximum = packages.limits()['upload_bytes']
    if request.content_length is None or request.content_length > maximum + 1024 * 1024:
        raise packages.PackageError('任务包超过上传大小限制。', 413)
    package = request.files.get('package')
    if not package or not package.filename.lower().endswith('.zip'):
        raise packages.PackageError('请选择 ZIP 任务包。')
    blob = package.stream.read(maximum + 1)
    data = packages.stage(blob, request.form.to_dict(), g.identity['username'])
    _audit('upload', data['pid'], data['version'])
    return success_msg(data)


@blueprint.post(BASE + '/action')
def action():
    body = request.get_json(silent=True) or {}
    pid, action = body.get('pid'), body.get('action')
    if not isinstance(pid, str) or not packages.IDENTIFIER.fullmatch(pid):
        raise packages.PackageError('请提供有效的任务编号。')
    version = body.get('version', '')
    actor = g.identity['username']
    if action == 'import':
        result = packages.import_task(pid, actor)
    elif action == 'prepare':
        result = packages.prepare(pid, version, body.get('main_file', ''))
    elif action in ('publish', 'rollback', 'trash', 'restore'):
        revision = body.get('revision')
        if type(revision) is not int or revision < 1:
            raise packages.PackageError('请携带当前任务状态版本号。', 409)
        if action in ('publish', 'rollback'):
            result = packages.publish(pid, version, revision, actor, rollback=action == 'rollback')
        else:
            result = packages.recycle(pid, revision, actor, restore=action == 'restore')
    else:
        raise packages.PackageError('无效操作。')
    _audit(action, pid, version)
    return success_msg(result)
