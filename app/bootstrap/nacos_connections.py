"""Coordinate a database edit with a single Nacos JSON document.

A remote publish and the local encrypted registration are two separate writes.
Never claim they are atomic: callers must report a confirmed remote publish even
when the subsequent local save fails, and must never retry a write blindly.
"""
import re
from app.bootstrap import nacos_bindings, nacos_config


def context(form):
    """Pin one endpoint for the entire read/probe/publish operation."""
    from app.common.nacos import Nacos, NacosConflict
    import hmac
    settings = nacos_config.saved()
    token = nacos_config.version_token(settings)
    expected = form.get('nacos_settings_token')
    if not isinstance(expected, str) or not hmac.compare_digest(token, expected):
        raise NacosConflict('Nacos 服务设置已变化或尚未读取，请重新读取数据库配置。')
    return {'client': Nacos(config=settings), 'token': token}


def check_context(value):
    import hmac
    from app.common.nacos import NacosConflict
    if not value or not hmac.compare_digest(nacos_config.version_token(), value['token']):
        raise NacosConflict('Nacos 服务设置已变化，请重新读取数据库配置。')


def prepare(form, previous, session=None):
    """Resolve the current secret and reject stale previews before probing a DB."""
    if not isinstance(form, dict):
        raise ValueError('连接信息必须为对象。')
    if form.get('revision', 0) != previous.get('revision', 0):
        raise RuntimeError('连接信息已被修改，请刷新后重试。')
    if form.get('source', previous.get('source', 'direct')) != 'nacos':
        return form
    binding = nacos_bindings.validate(form.get('nacos', previous.get('nacos')))
    expected = form.get('nacos_md5')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{32}', expected):
        raise ValueError('请先读取 Nacos 配置，再测试或保存。')
    session = session or context(form)
    check_context(session)
    remote = nacos_bindings.read(binding, force_refresh=True, client=session['client'])
    if remote['md5'] != expected:
        from app.common.nacos import NacosConflict
        raise NacosConflict('Nacos 配置已被修改，请重新读取后再保存。')
    # The preview never exposes the password. Blank retains the CURRENT remote
    # password, never a secret from a different local connection or old binding.
    password = form.get('password', '')
    if not isinstance(password, str):
        raise ValueError('密码格式无效。')
    return {**remote['values'], **form, 'nacos': binding,
            'password': password or remote['values']['password']}


def publish(profile, session=None):
    if profile.get('source') != 'nacos':
        return False
    check_context(session)
    fields = ('host', 'port', 'database', 'user', 'password', 'schema')
    values = {key: profile[key] for key in fields if key in profile}
    result = nacos_bindings.publish(profile['nacos'], values, profile['nacos_md5'], client=session['client'])
    profile['nacos_md5'] = result['md5']
    return True
