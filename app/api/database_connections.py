"""Administrator business connections; the platform database is deployment configuration."""

import os
import time
from flask import Blueprint, request
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap import connection_settings as settings

blueprint = Blueprint("database_connections", __name__)


@blueprint.get("/api/admin/database-connections")
def connections():
    try:
        from app.common.db.catalog import capabilities
        from app.bootstrap.helpers import get_runtime_env

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
            }
        )
    except ValueError as exc:
        return error_msg(str(exc)), 400


@blueprint.post("/api/admin/database-connections/<action>")
def change_connection(action):
    if action not in {"test", "save"}:
        return error_msg("操作不存在。"), 404
    try:
        profile = settings.validate(request.get_json(silent=True))
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
            result["profile"] = settings.save(profile)
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
    except RuntimeError as exc:
        return error_msg(str(exc)), 409
