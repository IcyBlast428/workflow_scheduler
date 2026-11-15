"""Administrator business connections; the platform database is deployment configuration."""

import os
import time
from flask import Blueprint, request, g
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap import connection_settings as settings

from app.api.platform_database import can_edit
from app.common.nacos import NacosError, NacosConflict, NacosPublishUncertain
from app.bootstrap import nacos_connections

blueprint = Blueprint("database_connections", __name__)


@blueprint.get("/api/admin/database-connections")
def connections():
    try:
        from app.common.db.catalog import capabilities
        from app.bootstrap.helpers import get_runtime_env
        from app.common.db.engine_pool import snapshot as pool_snapshot

        test = os.environ.get("WFS_POSTGRES_TEST") == "true"
        return success_msg(
            {
                "configuration_source": "独立协议测试配置"
                if test
                else "Nacos / 服务配置",
                "environment": get_runtime_env(),
                "active_dialect": "PostgreSQL（GaussDB 协议测试）"
                if test
                else "GaussDB / DWS",
                "profiles": [
                    settings.public_profile(p) for p in settings.profiles().values()
                ],
                "supported_databases": capabilities(),
                "business_pools": pool_snapshot(),
                "business_pool_scope": "current_web_process",
                "task_connection_entry": "NewDB",
                "can_manage_nacos": can_edit(),
            }
        )
    except ValueError as exc:
        return error_msg(str(exc)), 400


@blueprint.post("/api/admin/database-connections/<action>")
def change_connection(action):
    if action not in {"test", "save"}:
        return error_msg("操作不存在。"), 404
    remote_synced = False
    try:
        form = request.get_json(silent=True)
        if not isinstance(form, dict):
            raise ValueError('连接信息必须为对象。')
        previous = settings.profiles().get(str(form.get('id', '')), {})
        if 'nacos' in (form.get('source'), previous.get('source')) and not can_edit():
            return error_msg('仅内置管理员账号可以测试或修改 Nacos 来源连接。'), 403
        session = nacos_connections.context(form) if form.get('source', previous.get('source')) == 'nacos' else None
        profile = settings.validate(nacos_connections.prepare(form, previous, session), previous=previous)
        from app.bootstrap.connection_lifecycle import record_test

        started = time.monotonic()
        try:
            result = settings.probe_business(profile)
        except Exception:
            record_test(
                profile["id"],
                profile["revision"],
                False,
                (time.monotonic() - started) * 1000,
            )
            raise
        if action == "save":
            # Avoid holding a platform pool lease during network calls.
            current = settings.profiles().get(profile['id'], {})
            if current.get('revision', 0) != profile['revision']:
                raise RuntimeError('连接信息已被修改，请刷新后重试。')
            if profile.get('source') == 'nacos':
                from app.bootstrap.operations import audit
                audit(g.identity['username'], 'nacos_business_publish', profile['id'], details='连接测试通过，准备以版本校验回写 Nacos。')
            remote_synced = nacos_connections.publish(profile, session)
            result["nacos_synced"] = remote_synced
            try:
                if remote_synced:
                    nacos_connections.check_context(session)
                result["profile"] = settings.save(profile)
            except Exception:
                if remote_synced:
                    return error_msg('Nacos 已更新，但本地连接登记保存失败；请重新读取配置后再保存。'), 503
                raise
        revision = result.get("profile", profile)["revision"]
        record_test(
            profile["id"],
            revision,
            result["ready"],
            (time.monotonic() - started) * 1000,
        )
        return success_msg(result)
    except ValueError as exc:
        return error_msg(str(exc)), 400
    except NacosConflict as exc:
        return error_msg(str(exc)), 409
    except (NacosPublishUncertain, NacosError) as exc:
        return error_msg(str(exc)), 503
    except RuntimeError as exc:
        return error_msg(str(exc)), 409
