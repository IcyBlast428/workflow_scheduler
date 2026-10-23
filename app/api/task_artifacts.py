"""Output reads use the same shared storage as retained execution logs."""
from pathlib import PurePosixPath
from flask import Blueprint, request, send_file
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap import task_artifacts as artifacts
from app.bootstrap.task_source import SourceError

blueprint = Blueprint('task_artifacts', __name__)


@blueprint.errorhandler(SourceError)
def artifact_error(exc):
    return error_msg(str(exc)), exc.status


@blueprint.after_request
def private_output(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@blueprint.get('/api/taskinfo/artifacts')
def outputs():
    run_id = request.args.get('run_id')
    filename = request.args.get('file')
    if filename is not None:
        return success_msg(artifacts.preview_output(run_id, filename))
    return success_msg(artifacts.list_outputs(run_id, request.args.get('dir', ''), request.args.get('offset', 0)))


@blueprint.get('/api/taskinfo/artifact-download')
def download():
    record, stream, _ = artifacts.open_output(request.args.get('run_id'), request.args.get('file'))
    if record['status'] in ('queued', 'running'):
        stream.close()
        raise SourceError('本次执行尚未结束，请结束后下载完整输出文件。', 409)
    try:
        return send_file(stream, mimetype='application/octet-stream', as_attachment=True,
                         download_name=PurePosixPath(request.args['file']).name, conditional=False, etag=False)
    except Exception:
        stream.close()
        raise
