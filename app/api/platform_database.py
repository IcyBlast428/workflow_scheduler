"""Admin-only staged platform bootstrap configuration; no live database migration."""
import time
from flask import Blueprint, request, g
from app.bootstrap import platform_config as settings
from app.bootstrap.global_vars import success_msg, error_msg
from app.settings import AUTH_ADMIN_USERNAME
from app.bootstrap import nacos_connections
from app.common.nacos import NacosError, NacosConflict, NacosPublishUncertain

blueprint = Blueprint('platform_database', __name__)


def can_edit():
    """平台主库只能由环境指定的内置管理员修改，不能仅依据 admin 角色放行。"""
    identity = getattr(g, 'identity', None) or {}
    return identity.get('role') == 'admin' and identity.get('username') == AUTH_ADMIN_USERNAME


def probe(profile):
    """用独立连接只读检查候选库；不能初始化表、迁移数据或替换当前连接池。"""
    from app.bootstrap.database import GaussDB
    from scripts.init_database import validate
    began = time.monotonic()
    try:
        with GaussDB(config_override=profile, pooled=False) as db:
            validate(db)
    except Exception:
        # 驱动异常可能带连接串或密码，管理接口统一返回可操作且不含凭据的提示。
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
        return success_msg({**settings.snapshot(), 'diagnostics': diagnostics(), 'drivers': drivers,
                            'can_edit': can_edit(), 'editor_username': AUTH_ADMIN_USERNAME})
    except ValueError as exc:
        return error_msg(str(exc)), 400


@blueprint.post('/api/admin/platform-database/<action>')
def change(action):
    # 前端只读只是展示约束；必须在解析配置、发起数据库连接之前独立鉴权。
    if not can_edit():
        return error_msg('仅内置管理员账号可以测试或修改平台数据库连接。'), 403
    if action not in ('test', 'save'):
        return error_msg('操作不存在。'), 404
    try:
        previous = settings.saved()
        form = request.get_json(silent=True)
        if not isinstance(form, dict):
            raise ValueError('连接信息必须为对象。')
        session = nacos_connections.context(form) if form.get('source', previous.get('source')) == 'nacos' else None
        profile = settings.validate(nacos_connections.prepare(form, previous, session), previous=previous)
        result = probe(profile)
        if action == 'save':
            # The audit must succeed against the CURRENT platform before staging.
            from app.bootstrap.operations import audit
            audit(g.identity['username'], 'platform_connection_stage', 'platform', details='连接测试通过，准备保存待重启配置；不自动迁移数据。')
            # settings.save 会再次核对 revision；测试期间被他人修改时不能覆盖新配置。
            if settings.saved()['revision'] != profile['revision']:
                raise RuntimeError('平台连接已被修改，请刷新后重试。')
            remote_synced = nacos_connections.publish(profile, session)
            result['nacos_synced'] = remote_synced
            try:
                if remote_synced:
                    nacos_connections.check_context(session)
                result['profile'] = settings.save(profile)
            except Exception:
                if remote_synced:
                    return error_msg('Nacos 已更新，但平台待重启配置保存失败；请重新读取后再保存。当前平台仍使用原连接。'), 503
                raise
            result['restart_required'] = True
        return success_msg(result)
    except ValueError as exc:
        return error_msg(str(exc)), 400
    except NacosConflict as exc:
        return error_msg(str(exc)), 409
    except (NacosPublishUncertain, NacosError) as exc:
        return error_msg(str(exc)), 503
    except RuntimeError as exc:
        return error_msg(str(exc)), 409
    except OSError:
        return error_msg('平台连接配置无法写入，请检查数据目录权限和磁盘空间。'), 503
