"""Administrator-only examples and pip repository configuration."""
from flask import Blueprint, request
from app.bootstrap import task_publishing as settings
from app.bootstrap.global_vars import success_msg, error_msg

blueprint = Blueprint('task_publishing', __name__)
BASE = '/api/admin/task-publishing'


@blueprint.errorhandler(settings.PublishingError)
def publishing_error(error):
    return error_msg(str(error)), error.status


@blueprint.before_request
def limit_payload():
    if request.method == 'POST' and (request.content_length is None or request.content_length > 300000):
        return error_msg('发布设置内容过大或缺少大小信息。'), 413


@blueprint.get(BASE + '/examples')
def examples():
    return success_msg({'items': settings.examples()})


@blueprint.post(BASE + '/examples')
def save_example():
    return success_msg(settings.save_example(request.get_json(silent=True) or {}))


@blueprint.get(BASE + '/repository')
def repository():
    return success_msg(settings.public_repository())


@blueprint.post(BASE + '/repository')
def save_repository():
    return success_msg(settings.save_repository(request.get_json(silent=True) or {}))
