"""Administrator-only GitLab metadata/diffs. External requests are GET-only."""
from flask import Blueprint, g, request
from app.bootstrap import gitlab_updates as updates
from app.bootstrap.global_vars import success_msg, error_msg

blueprint = Blueprint('gitlab_updates', __name__)
BASE = '/api/admin/gitlab-updates'


@blueprint.errorhandler(updates.GitLabError)
def error(exc):
    return error_msg(str(exc)), exc.status


@blueprint.post('/api/integrations/gitlab/webhook')
def webhook():
    from app.bootstrap.gitlab_webhook import receive
    if request.content_length is None or request.content_length>65536:
        return error_msg('Webhook 内容过大。'),413
    body=request.get_json(silent=True)
    if not isinstance(body,dict): return error_msg('事件格式无效。'),400
    try:
        accepted=receive(request.headers.get('X-Gitlab-Token',''),request.headers.get('X-Gitlab-Event',''),
            request.headers.get('X-Gitlab-Event-UUID',''),body)
    except PermissionError: return error_msg('Webhook 验证失败。'),401
    except ValueError as exc: return error_msg(str(exc)),400
    return success_msg({'accepted':accepted}),202

@blueprint.before_request
def limits():
    if request.method == 'POST' and (request.content_length is None or request.content_length > 100000):
        return error_msg('GitLab 设置或请求内容过大。'), 413


@blueprint.get(BASE + '/configuration')
def configuration():
    return success_msg(updates.public_configuration())


@blueprint.post(BASE + '/configuration')
def save():
    return success_msg(updates.save_configuration(request.get_json(silent=True) or {}))


@blueprint.get(BASE + '/state')
def state():
    return success_msg(updates.state(g.identity['username'], brief=request.args.get('brief') == 'true'))


@blueprint.post(BASE + '/scan')
def scan():
    updates.request_scan(force=True)
    return success_msg(updates.state(g.identity['username']))


@blueprint.post(BASE + '/acknowledge')
def acknowledge():
    updates.acknowledge(g.identity['username'], (request.get_json(silent=True) or {}).get('fingerprint'))
    return success_msg(updates.state(g.identity['username'], True))


@blueprint.get(BASE + '/diff')
def diff():
    try:
        index = int(request.args.get('index', ''))
    except ValueError:
        return error_msg('请选择有效文件。'), 400
    return success_msg(updates.diff(request.args.get('id'), index))
