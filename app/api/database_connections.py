"""Administrator-only connection management; never proxy credentials to tasks."""
from flask import Blueprint, request
import os
from app.bootstrap.global_vars import success_msg, error_msg
from app.bootstrap import connection_settings as settings

blueprint = Blueprint('database_connections', __name__)


@blueprint.get('/api/admin/database-connections')
def connections():
    try:
        active = settings.active_platform()
        profiles = settings.profiles()
        pending = profiles.get('platform')
        from app.common.db.catalog import capabilities
        from app.bootstrap.helpers import get_runtime_env
        local = bool(os.environ.get('WFS_LOCAL_DB_PATH'))
        production = get_runtime_env() == 'production'
        source = '平台管理' if active else '本地 SQLite' if local else 'Nacos' if production else '本地 INI / 环境配置'
        dialect = 'MySQL / PolarDB' if active else 'SQLite' if local else ('PostgreSQL' if os.environ.get('WFS_DB_DIALECT') == 'postgresql' or os.environ.get('WFS_POSTGRES_TEST') == 'true' else 'GaussDB / DWS')
        return success_msg({'configuration_source':source, 'platform_editable':bool(active), 'environment':get_runtime_env(), 'profiles': [settings.public_profile(item) for item in profiles.values()],
                            'active': settings.public_profile(active) if active else None,
                            'active_dialect': dialect,
                            'restart_required': pending != active, 'supported_databases': capabilities()})
    except ValueError as exc:
        return error_msg(str(exc)), 400


@blueprint.post('/api/admin/database-connections/<action>')
def change_connection(action):
    if action not in {'test', 'save', 'initialize'}:
        return error_msg('操作不存在。'), 404
    try:
        form = request.get_json(silent=True)
        profile = settings.validate(form)
        if action == 'initialize':
            if profile['id'] != 'platform' or form.get('confirm_database') != profile['database']:
                raise ValueError('请准确输入目标数据库名称，确认只在新库初始化平台表。')
        import time
        from app.bootstrap.connection_lifecycle import record_test
        started=time.monotonic()
        try:
            result = settings.probe(profile, initialize=action == 'initialize')
        except Exception:
            if profile['id']!='platform': record_test(profile['id'],profile['revision'],False,(time.monotonic()-started)*1000)
            raise
        if profile['id']!='platform': record_test(profile['id'],profile['revision'],result.get('ready'),(time.monotonic()-started)*1000)
        if action == 'save':
            if not result['ready']:
                raise ValueError('目标库缺少平台表或 summary_version 字段，请先初始化新库或完成结构迁移。')
            saved = settings.save(profile)
            result.update(profile=saved, restart_required=profile['id'] == 'platform')
        return success_msg(result)
    except ValueError as exc:
        return error_msg(str(exc)), 400
    except RuntimeError as exc:
        return error_msg(str(exc)), 409
