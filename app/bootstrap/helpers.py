import os

from configobj import ConfigObj
from app import CONFIG_DIR


def get_runtime_env(default='production'):
    env_name = os.environ.get('WFS_ENV') or os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV')
    if env_name:
        return env_name
    if default is None:
        return None
    return 'development' if os.name == 'nt' else default


def load_config(section, key, default=None):
    current_env = get_runtime_env()
    cfg_file = os.path.join(CONFIG_DIR, current_env+'.ini')
    cfg_base = ConfigObj(cfg_file, encoding='utf-8')
    config = cfg_base.get(section) or {}
    return config.get(key, default)


def load_section(section, default=None):
    current_env = get_runtime_env()
    cfg_file = os.path.join(CONFIG_DIR, current_env + '.ini')
    cfg_base = ConfigObj(cfg_file, encoding='utf-8')
    config = cfg_base.get(section)
    if config is None:
        return default if default is not None else {}
    return config
