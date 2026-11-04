import datetime
import os
from datetime import timedelta
from app.bootstrap.timebase import business_now


from app.bootstrap import helpers
from app.bootstrap.global_vars import BASE_DIR





class Config:
    APP_NAME = helpers.load_config('basic', 'app_name', '定时任务调度')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get('WFS_SECRET_KEY')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_NAME = os.environ.get('WFS_SESSION_COOKIE_NAME', 'session')
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
            "run_date": (business_now() + datetime.timedelta(seconds=2)).strftime('%Y-%m-%d %H:%M:%S'),
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

FLASK_ENV = helpers.get_runtime_env(default='production')


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
MPCM_ACCESS_TOKEN = _load_runtime_value('runtime', 'mpcm_access_token', 'WFS_MPCM_ACCESS_TOKEN')
WFS_ENABLE_SCHEDULER = _load_runtime_bool('runtime', 'enable_scheduler', 'WFS_ENABLE_SCHEDULER', True)
WFS_SCHEDULER_CONTROL_URL = _load_runtime_value('runtime', 'scheduler_control_url', 'WFS_SCHEDULER_CONTROL_URL', '')
