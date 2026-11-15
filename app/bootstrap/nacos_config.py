"""Nacos 引导连接：独立于平台数据库加密保存，避免启动时的循环依赖。"""
import base64
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit, urlunsplit
import uuid

_guard = threading.RLock()


def path():
    from app.bootstrap.global_vars import DATA_DIR
    data = Path(os.environ.get('WFS_DATA_DIR', DATA_DIR))
    return Path(os.environ.get('WFS_NACOS_CONFIG_FILE', str(data / 'nacos-connection.enc')))


def defaults(environment=None):
    env = os.environ if environment is None else environment
    ttl = float(env.get('WFS_NACOS_CONFIG_TTL_SECONDS', '60'))
    if not math.isfinite(ttl) or not 0 <= ttl <= 3600:
        raise ValueError('Nacos 配置缓存时间应为 0 至 3600 秒。')
    return dict(revision=0, url=env.get('WFS_NACOS_URL', '').rstrip('/'),
                username=env.get('WFS_NACOS_USERNAME', ''), password=env.get('WFS_NACOS_PASSWORD', ''),
                auth_enabled=True, verify_tls=True, ca_file='', timeout=10, config_ttl=ttl)


def _cipher(environment=None):
    from cryptography.fernet import Fernet
    env = os.environ if environment is None else environment
    secret = env.get('WFS_CONNECTIONS_KEY') or env.get('WFS_SECRET_KEY')
    if not secret:
        raise ValueError('保存 Nacos 连接前，请配置固定的 WFS_CONNECTIONS_KEY 或 WFS_SECRET_KEY。')
    key = hashlib.sha256(('wfs:nacos:v1:' + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def validate(form, previous=None):
    """密码留空保留；更换服务地址时必须明确重新填写密码。"""
    if not isinstance(form, dict):
        raise ValueError('Nacos 连接配置必须为对象。')
    previous = saved() if previous is None else previous
    if type(form.get('revision')) is not int or form['revision'] != previous.get('revision', 0):
        raise RuntimeError('Nacos 连接已被修改，请刷新后重试。')
    value = {**defaults(), **previous}
    for key in ('url', 'username', 'ca_file'):
        text = form.get(key, value[key])
        if not isinstance(text, str) or len(text) > 2048 or any(ord(c) < 32 for c in text):
            raise ValueError('Nacos 连接字段格式无效。')
        value[key] = text.strip()
    if value['url']:
        try:
            parsed = urlsplit(value['url'])
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or '\\' in value['url']
                    or any(c.isspace() for c in value['url'])):
                raise ValueError()
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
            value['url'] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))
        except ValueError:
            raise ValueError('Nacos 地址应为 HTTP 或 HTTPS 服务地址，可包含 /nacos 路径，不可包含账号或查询参数。') from None
    for key in ('auth_enabled', 'verify_tls'):
        candidate = form.get(key, value[key])
        if type(candidate) is not bool:
            raise ValueError('Nacos 开关必须为布尔值。')
        value[key] = candidate
    for key, low, high in (('timeout', 1, 60), ('config_ttl', 0, 3600)):
        candidate = form.get(key, value[key])
        if type(candidate) not in (int, float) or not math.isfinite(candidate) or not low <= candidate <= high:
            raise ValueError(f'Nacos {key} 应为 {low} 至 {high} 秒。')
        value[key] = candidate
    password = form.get('password', '')
    if not isinstance(password, str) or len(password) > 4096:
        raise ValueError('Nacos 密码格式无效。')
    endpoint_changed = value['url'] != previous.get('url', '').rstrip('/')
    if endpoint_changed and previous.get('password') and not password and value['auth_enabled']:
        raise ValueError('更换 Nacos 地址时请重新填写密码，防止将原密码发送给其他服务。')
    # 切到匿名端点时丢弃原密码，避免先关闭认证换地址、再启用认证来复用旧凭据。
    value['password'] = password or ('' if endpoint_changed else previous.get('password', ''))
    if not value['verify_tls'] and value['ca_file']:
        raise ValueError('使用自定义 CA 文件时必须启用 TLS 证书校验。')
    if value['url'] and value['auth_enabled'] and (not value['username'] or not value['password']):
        raise ValueError('启用 Nacos 认证后，请填写用户名和密码。')
    # 不接收表单中的未知字段，防止密文文件成为任意配置的传递入口。
    return {key: value[key] for key in defaults()}


def saved(target=None, environment=None):
    target = path() if target is None else Path(target)
    if target.is_symlink():
        raise ValueError('Nacos 连接配置文件无效。')
    if not target.exists():
        return defaults(environment)
    if target.stat().st_size > 65536:
        raise ValueError('Nacos 连接配置文件无效。')
    try:
        value = json.loads(_cipher(environment).decrypt(target.read_bytes()))
        if not isinstance(value, dict) or type(value.get('revision')) is not int or value['revision'] < 0:
            raise ValueError()
        baseline = {**defaults(environment), **value}
        return validate(baseline, previous=baseline)
    except Exception:
        raise ValueError('Nacos 连接配置无法读取或解密，请核对配置文件和原加密密钥。') from None


def public(value):
    return {**{key: value[key] for key in defaults() if key != 'password' and key in value},
            'password_set': bool(value.get('password'))}


@contextmanager
def _file_lock():
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix('.lock')
    if lock_path.is_symlink() or target.is_symlink():
        raise ValueError('Nacos 配置文件无效。')
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


def save(profile):
    with _file_lock():
        previous = saved()
        updated = validate(profile, previous=previous)
        updated['revision'] = previous['revision'] + 1
        target = path()
        temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                if os.name != 'nt':
                    os.chmod(temporary, 0o600)
                stream.write(_cipher().encrypt(json.dumps(updated, ensure_ascii=False).encode()))
                stream.flush(); os.fsync(stream.fileno())
            from app.bootstrap.recovery_files import replace_recovery
            replace_recovery(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    # 活跃任务持有自己的连接快照；后续读取应重新认证，不能沿用旧端点缓存。
    from app.common.nacos import Nacos
    Nacos.clear_cache()
    return public(updated)


def snapshot():
    return {'saved': public(saved()), 'source': 'file' if path().exists() else 'environment'}


def _after_fork():
    global _guard
    _guard = threading.RLock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def version_token(profile=None):
    """Opaque identity for a preview: bind it to endpoint AND credentials.

    HMAC avoids exposing an offline password-checking hash in browser responses.
    Environment-only settings are covered too, where the file revision stays 0.
    """
    import hmac
    profile = saved() if profile is None else profile
    secret = os.environ.get('WFS_CONNECTIONS_KEY') or os.environ.get('WFS_SECRET_KEY')
    if not secret:
        raise ValueError('请先配置固定的 WFS_CONNECTIONS_KEY 或 WFS_SECRET_KEY。')
    payload = json.dumps(profile, sort_keys=True, ensure_ascii=True).encode()
    return hmac.new(('wfs:nacos:preview:' + secret).encode(), payload, hashlib.sha256).hexdigest()
