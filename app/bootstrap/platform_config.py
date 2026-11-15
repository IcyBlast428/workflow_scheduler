"""Encrypted bootstrap settings, staged on disk and pinned for the process lifetime."""
import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

_active = {}
_guard = threading.RLock()
FIELDS = {
    'web_pool_size': (5, 1, 32), 'web_max_overflow': (3, 0, 32),
    'scheduler_pool_size': (10, 1, 64), 'scheduler_max_overflow': (5, 0, 32),
    'pool_timeout': (10, 1, 120), 'pool_recycle': (600, 30, 3600),
    'query_timeout': (10, 1, 3600), 'connect_timeout': (10, 1, 60),
}


def path():
    from app.bootstrap.global_vars import DATA_DIR
    data = Path(os.environ.get('WFS_DATA_DIR', DATA_DIR))
    return Path(os.environ.get('WFS_PLATFORM_CONFIG_FILE', str(data / 'platform-connection.enc')))


def defaults(environment=None):
    environment = os.environ if environment is None else environment
    query_timeout = int(environment.get('WFS_DB_QUERY_TIMEOUT_SECONDS', FIELDS['query_timeout'][0]))
    if not 1 <= query_timeout <= 3600:
        raise ValueError('WFS_DB_QUERY_TIMEOUT_SECONDS must be between 1 and 3600')
    value = dict(revision=0, source='service', host='', port=8000, database='', schema='wfs',
                user='', password='', driver=environment.get('WFS_DB_DRIVER', 'DWS'),
                db_id=environment.get('WFS_DB_ID', 'wfsscheduler_wfs'),
                **{key: value[0] for key, value in FIELDS.items()})
    value['query_timeout'] = query_timeout
    return value


def _cipher(environment=None):
    from cryptography.fernet import Fernet
    environment = os.environ if environment is None else environment
    secret = environment.get('WFS_CONNECTIONS_KEY') or environment.get('WFS_SECRET_KEY')
    if not secret:
        raise ValueError('保存平台连接前，请配置固定的 WFS_CONNECTIONS_KEY 或 WFS_SECRET_KEY。')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('wfs:platform:v1:' + secret).encode()).digest()))


def saved(target=None, environment=None):
    target = path() if target is None else Path(target)
    if not target.exists():
        return defaults(environment)
    if target.is_symlink() or target.stat().st_size > 65536:
        raise ValueError('平台连接配置文件无效。')
    try:
        value = json.loads(_cipher(environment).decrypt(target.read_bytes()))
        if not isinstance(value, dict) or type(value.get('revision')) is not int:
            raise ValueError()
        baseline = {**defaults(environment), **value}
        return validate(baseline, previous=baseline)
    except Exception:
        raise ValueError('平台连接配置无法读取或解密，请核对配置文件和原加密密钥。') from None


def active():
    # A staged edit must never split live workers between two databases.
    frozen = os.environ.get('WFS_PLATFORM_ACTIVE_CONFIG_FILE')
    key = (os.getpid(), str(path()), frozen)
    with _guard:
        if key not in _active:
            if os.environ.get('WFS_POSTGRES_TEST') == 'true':
                _active[key] = defaults()
            else:
                if frozen and not Path(frozen).is_file():
                    raise ValueError('当前服务的平台连接快照丢失，请完整重启服务。')
                _active[key] = saved(frozen)
        return deepcopy(_active[key])


def public(value):
    allowed = set(defaults()) - {'password'}
    return {**{k: v for k, v in value.items() if k in allowed}, 'password_set': bool(value.get('password'))}


def validate(form, previous=None):
    if not isinstance(form, dict):
        raise ValueError('平台连接配置必须为对象。')
    previous = saved() if previous is None else previous
    value = {**defaults(), **previous}
    if type(form.get('revision')) is not int or form['revision'] != previous['revision']:
        raise RuntimeError('平台连接已被修改，请刷新后重试。')
    source = form.get('source', previous['source'])
    if source not in ('service', 'direct'):
        raise ValueError('请选择服务配置或自定义连接。')
    value['source'] = source
    for key, (_, low, high) in FIELDS.items():
        number = form.get(key, value[key])
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f'{key} 应为 {low} 至 {high} 之间的整数。')
        value[key] = number
    for key in ('driver', 'db_id', 'host', 'database', 'schema', 'user'):
        text = form.get(key, value[key])
        if not isinstance(text, str) or len(text) > 253 or any(ord(c) < 32 for c in text):
            raise ValueError('连接字段格式无效。')
        value[key] = text.strip()
    password = form.get('password', '')
    if not isinstance(password, str) or len(password) > 1024:
        raise ValueError('密码格式无效。')
    value['password'] = password or previous.get('password', '')
    if not value['driver'] or any(c in value['driver'] for c in ';{}\\/'):
        raise ValueError('请填写已安装的 ODBC 驱动名称。')
    if source == 'service':
        if not re.fullmatch(r'[A-Za-z0-9]+_[A-Za-z_][A-Za-z0-9_]*', value['db_id']):
            raise ValueError('服务数据库标识应为 database_schema。')
    else:
        if not re.fullmatch(r'[A-Za-z0-9_.:-]+', value['host']):
            raise ValueError('数据库地址只能填写主机名或 IP。')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$-]*', value['database']):
            raise ValueError('数据库名称格式无效。')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value['schema']):
            raise ValueError('Schema 名称格式无效。')
        if not value['user'] or not value['password']:
            raise ValueError('请填写数据库账号和密码。')
        port = form.get('port', value['port'])
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('端口应为 1 至 65535 之间的整数。')
        value['port'] = port
    return value


@contextmanager
def _file_lock():
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix('.lock')
    if lock_path.is_symlink():
        raise ValueError('平台配置锁文件无效。')
    with _guard, lock_path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def save(value):
    active()  # Pin the old target even if this is the process's first operation.
    with _file_lock():
        previous = saved()
        if value['revision'] != previous['revision']:
            raise RuntimeError('平台连接已被修改，请刷新后重试。')
        updated = {**validate(value, previous=previous), 'revision': previous['revision'] + 1}
        target = path()
        temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                if os.name != 'nt': os.chmod(temporary, 0o600)
                stream.write(_cipher().encrypt(json.dumps(updated, ensure_ascii=False).encode()))
                stream.flush(); os.fsync(stream.fileno())
            from app.bootstrap.recovery_files import replace_recovery
            replace_recovery(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return public(updated)


def snapshot():
    current, pending = active(), saved()
    return {'active': public(current), 'saved': public(pending),
            'restart_required': current['revision'] != pending['revision'],
            'test_environment': os.environ.get('WFS_POSTGRES_TEST') == 'true'}


def _after_fork():
    global _active, _guard
    _active = {}
    _guard = threading.RLock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


@contextmanager
def frozen_service_config(data, environment):
    """Keep every Web/Scheduler worker, including replacements, on one target."""
    directory = Path(data) / 'platform-runtime'
    source = environment.get('WFS_PLATFORM_CONFIG_FILE', str(Path(data) / 'platform-connection.enc'))
    value = saved(source, environment)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ('service-' + uuid.uuid4().hex + '.enc')
    try:
        with target.open('xb') as stream:
            if os.name != 'nt': os.chmod(target, 0o600)
            stream.write(_cipher(environment).encrypt(json.dumps(value, ensure_ascii=False).encode()))
            stream.flush(); os.fsync(stream.fileno())
        yield str(target)
    finally:
        target.unlink(missing_ok=True)
