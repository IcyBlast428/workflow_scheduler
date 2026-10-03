import datetime
import os
from datetime import timedelta

from configobj import ConfigObj

from app import CONFIG_DIR
from app.bootstrap import helpers
from app.bootstrap.global_vars import BASE_DIR
from app.common.pyDes import do_decrypt as _p
from app.loggings import get_local_ip


def build_database_uri(environment):
    if os.environ.get('WFS_LOCAL_DB_PATH'):
        return 'sqlite:///' + os.path.abspath(os.environ['WFS_LOCAL_DB_PATH']).replace('\\', '/')
    cfg_file = os.path.join(CONFIG_DIR, 'database', 'system.ini')
    cfg_base = ConfigObj(cfg_file, encoding='utf-8')
    config = cfg_base.get(environment)
    if not config:
        raise Exception(f'{environment} not config')
    dialect = config.get("dialect")
    driver = config.get('driver')
    user = config.get("user")
    password = config.get("password")
    host = config.get("host")
    port = config.get("port")
    database = config.get("database")
    if password:
        password = _p(password)
    return '{}+{}://{}:{}@{}:{}/{}?charset=utf8'.format(dialect, driver, user, password, host, port, database)


class Config:
    APP_NAME = helpers.load_config('basic', 'app_name', '定时任务调度')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get('WFS_SECRET_KEY')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    SESSION_COOKIE_SECURE = os.environ.get('WFS_COOKIE_SECURE', 'false').lower() in {'1', 'true', 'yes'}
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_REFRESH_EACH_REQUEST = False
    TIME_ZONE = 'Asia/ShangHai'
    USE_I18N = True
    USE_L10N = True
    USE_TZ = True
    SCHEDULER_TIMEZONE = 'Asia/Shanghai'
    SCHEDULER_API_ENABLED = False
    JOBS = [
        {
            "id": "MAIN_TASK_JOB",
            "func": "app.bootstrap.core:aps_start",
            "name": 'Main task bootstrap',
            "trigger": "date",
            "run_date": (datetime.datetime.now() + datetime.timedelta(seconds=2)).strftime('%Y-%m-%d %H:%M:%S'),
            "max_instances": 10,
            "replace_existing": True,
            "coalesce": True,
            'misfire_grace_time': 1000,
        }
    ]
    SCHEDULER_EXECUTORS = {
        'default': {'type': 'threadpool', 'max_workers': 20}
    }


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    DEBUG = False
    TESTING = True


env = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}

_runtime_env = helpers.get_runtime_env(default=None)
if _runtime_env:
    FLASK_ENV = _runtime_env
elif os.name == 'nt' or get_local_ip().startswith('76.10') or get_local_ip().startswith('84.10'):
    FLASK_ENV = 'development'
else:
    FLASK_ENV = 'production'


def _load_runtime_value(section, key, env_name=None, default=None):
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value not in (None, ''):
            return env_value
    return helpers.load_config(section, key, default)


def _load_runtime_bool(section, key, env_name=None, default=False):
    raw_value = _load_runtime_value(section, key, env_name, str(default).lower())
    return str(raw_value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _resolve_project_path(path_value):
    project_root = str(BASE_DIR.parent)
    if not path_value:
        return project_root
    if os.path.isabs(path_value):
        return path_value
    return os.path.abspath(os.path.join(project_root, path_value))


AUTH_ADMIN_USERNAME = os.environ.get('WFS_ADMIN_USERNAME', 'admin')
AUTH_ADMIN_PASSWORD_HASH = os.environ.get('WFS_ADMIN_PASSWORD_HASH', '')
APP_AVATAR_URL = _load_runtime_value('runtime', 'avatar_url', 'WFS_AVATAR_URL', '/static/img/head.gif')
CODE_UPDATE_PATH = _resolve_project_path(_load_runtime_value('runtime', 'repo_path', 'WFS_REPO_PATH', '.'))
CODE_UPDATE_REMOTE = _load_runtime_value('runtime', 'code_remote', 'WFS_CODE_REMOTE', 'origin')
CODE_UPDATE_BRANCH = _load_runtime_value('runtime', 'code_branch', 'WFS_CODE_BRANCH', 'workflow_scheduler')
MPCM_ACCESS_TOKEN = _load_runtime_value('runtime', 'mpcm_access_token', 'WFS_MPCM_ACCESS_TOKEN')
WFS_ENABLE_SCHEDULER = _load_runtime_bool('runtime', 'enable_scheduler', 'WFS_ENABLE_SCHEDULER', True)
WFS_SCHEDULER_CONTROL_URL = _load_runtime_value('runtime', 'scheduler_control_url', 'WFS_SCHEDULER_CONTROL_URL', '')
