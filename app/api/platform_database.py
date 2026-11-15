"""Admin-only staged platform bootstrap configuration; no live database migration."""
import time
from flask import Blueprint, request, g
from app.bootstrap import platform_config as settings
from app.bootstrap.global_vars import success_msg, error_msg

blueprint = Blueprint('platform_database', __name__)


def probe(profile):
    from app.bootstrap.database import GaussDB
    from scripts.init_database import validate
    began = time.monotonic()
    try:
        with GaussDB(config_override=profile, pooled=False) as db:
            validate(db)
    except Exception:
        raise ValueError('平台连接测试未通过：请检查地址、账号、驱动及目标库结构。不会自动建表或迁移数据。') from None
    return {'ready': True, 'elapsed_ms': round((time.monotonic()-began)*1000, 1)}


@blueprint.get('/api/admin/platform-database')
def platform_database():
    from app.bootstrap.platform_pool import diagnostics
    try:
        import pyodbc
        drivers = pyodbc.drivers()
    except (ImportError, RuntimeError):
        drivers = []
    try:
        return success_msg({**settings.snapshot(), 'diagnostics': diagnostics(), 'drivers': drivers})
    except ValueError as exc:
        return error_msg(str(exc)), 400


@blueprint.post('/api/admin/platform-database/<action>')
def change(action):
    if action not in ('test', 'save'):
        return error_msg('操作不存在。'), 404
    try:
        profile = settings.validate(request.get_json(silent=True))
        result = probe(profile)
        if action == 'save':
            # The audit must succeed against the CURRENT platform before staging.
            from app.bootstrap.operations import audit
            audit(g.identity['username'], 'platform_connection_stage', 'platform', details='连接测试通过，准备保存待重启配置；不自动迁移数据。')
            result['profile'] = settings.save(profile)
            result['restart_required'] = True
        return success_msg(result)
    except ValueError as exc:
        return error_msg(str(exc)), 400
    except RuntimeError as exc:
        return error_msg(str(exc)), 409
    except OSError:
        return error_msg('平台连接配置无法写入，请检查数据目录权限和磁盘空间。'), 503
