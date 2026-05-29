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
    """从环境对应的 INI 中读取业务数据库配置。

    非高斯业务库属于公共/任务侧能力，暂时沿用 `app/config/database/*.ini`。
    未来如果要改为 Nacos 或密钥服务，只需要替换这一层，不影响 adapter。
    """
    current_env = get_runtime_env()
    ini = os.path.join(CONFIG_DIR, 'database', current_env + '.ini')
    config_base = ConfigObj(ini, encoding='utf-8')
    config = config_base.get(db_id)
    if not config:
        raise RuntimeError('missing database config section [{}] in {}'.format(db_id, ini))

    dialect = (config.get('dialect') or db_id.split('_', 1)[0]).strip("'\"").lower()
    return {
        'id': db_id,
        'dialect': dialect,
        'user': (config.get('user') or '').strip("'\""),
        'password': _decrypt_password((config.get('password') or '').strip("'\"")),
        'host': (config.get('host') or '').strip("'\""),
        'port': (config.get('port') or '').strip("'\""),
        'database': (config.get('database') or '').strip("'\""),
        'charset': (config.get('charset') or 'utf8').strip("'\""),
    }
