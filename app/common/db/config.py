# -*- coding: utf-8 -*-

import os

from configobj import ConfigObj

from app.bootstrap.global_vars import CONFIG_DIR
from app.bootstrap.helpers import get_runtime_env
from app.common.pyDes import do_decrypt as _p


def _decrypt_password(raw_password):
    if not raw_password:
        return ''
    try:
        return _p(raw_password)
    except Exception:
        # 兼容任务自带配置里直接填写明文密码的情况；生产配置仍建议加密。
        return raw_password


def load_database_config(db_id):
    """优先读取管理员保存的加密配置，未配置的标识回退到旧 INI。"""
    from app.bootstrap.connection_settings import business_profile
    managed = business_profile(db_id)
    if managed:
        return managed
    current_env = get_runtime_env()
    ini = os.path.join(CONFIG_DIR, 'database', current_env + '.ini')
    config_base = ConfigObj(ini, encoding='utf-8')
    config = config_base.get(db_id)
    if not config:
        raise RuntimeError('missing database config section [{}] in {}'.format(db_id, ini))

    dialect = (config.get('dialect') or db_id.split('_', 1)[0]).strip("'\"").lower()
    from app.common.db.catalog import normalize
    return {
        'id': db_id,
        'dialect': normalize(dialect),
        'user': (config.get('user') or '').strip("'\""),
        'password': _decrypt_password((config.get('password') or '').strip("'\"")),
        'host': (config.get('host') or '').strip("'\""),
        'port': (config.get('port') or '').strip("'\""),
        'database': (config.get('database') or '').strip("'\""),
        'charset': (config.get('charset') or 'utf8').strip("'\""),
        'tls': config.get('tls') or 'disabled',
        'ssl_ca': config.get('ssl_ca') or '',
    }
