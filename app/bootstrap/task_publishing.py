"""Shared administrator-maintained task examples and encrypted pip settings."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit
import uuid

from app.bootstrap.global_vars import DATA_DIR

DEFAULT_INDEX = 'http://nexus.immp.icbc/repository/pypi-hosted/simple/'
LANGUAGES = {'python', 'sql', 'bash', 'json', 'plaintext'}


class PublishingError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@contextmanager
def store():
    path = Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'task-publishing.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        if os.name != 'nt':
            path.chmod(0o600)
        connection.execute('CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL)')
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _cipher():
    # Separate purpose-derived key: task children cannot decrypt these settings.
    from app.bootstrap.connection_settings import _cipher as configuration_cipher
    return configuration_cipher('task-publishing')


def _read(connection, name):
    row = connection.execute('SELECT revision,payload FROM settings WHERE name=?', (name,)).fetchone()
    if not row:
        return None
    if name == 'repository':
        from cryptography.fernet import InvalidToken
        try:
            payload = _cipher().decrypt(row[1])
        except InvalidToken:
            raise PublishingError('发布配置无法解密，请恢复原配置密钥。') from None
    else:
        payload = row[1]
    return {**json.loads(payload), 'revision': row[0]}


def _write(connection, name, payload, revision):
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    if name == 'repository':
        encoded = _cipher().encrypt(encoded)
    connection.execute('INSERT OR REPLACE INTO settings(name,revision,payload) VALUES(?,?,?)', (name, revision, encoded))


def repository():
    with store() as connection:
        return _read(connection, 'repository') or dict(mode='offline', index_url=DEFAULT_INDEX,
            username='', password='', ca_bundle='', revision=0)


def public_repository(value=None):
    value = repository() if value is None else value
    return {**{key: item for key, item in value.items() if key != 'password'}, 'password_set': bool(value.get('password'))}


def index_url(value):
    if not isinstance(value, str) or not value or len(value) > 1000 or any(ord(c) <= 32 for c in value):
        raise PublishingError('请填写完整的 Nexus pip 索引地址。')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise PublishingError('仓库地址无效。') from None
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or '\\' in value
            or (port is not None and not 1 <= port <= 65535)):
        raise PublishingError('仓库地址只允许 HTTP/HTTPS，不要在地址中填写账号、密码、参数或片段。')
    path = parsed.path.rstrip('/')
    if not path.endswith('/simple'):
        path += '/simple'
    return urlunsplit((parsed.scheme, parsed.netloc, path + '/', '', ''))


def save_repository(form):
    with store() as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = _read(connection, 'repository') or dict(revision=0, password='')
        if type(form.get('revision')) is not int or form['revision'] != previous['revision']:
            raise PublishingError('仓库设置已被其他管理员修改，请刷新后重试。', 409)
        mode = form.get('mode')
        if not isinstance(mode, str) or mode not in {'offline', 'nexus'}:
            raise PublishingError('请选择离线或 Nexus 安装模式。')
        url = index_url(form.get('index_url') or DEFAULT_INDEX)
        username = _text(form, 'username', 100, required=False)
        password = _text(form, 'password', 1024, required=False, strip=False) or previous.get('password', '')
        if not username:
            password = ''
        if username and not password:
            raise PublishingError('认证账号需要填写密码；无需认证时请清空账号。')
        ca = _text(form, 'ca_bundle', 1024, required=False)
        if any(ord(c) < 32 for c in username + password + ca):
            raise PublishingError('认证信息和 CA 路径不能包含控制字符。')
        if ca and (not Path(ca).is_file() or urlsplit(url).scheme != 'https'):
            raise PublishingError('CA 证书仅用于 HTTPS，且需在 Web 和调度服务的同一路径可读。')
        value = dict(mode=mode, index_url=url, username=username, password=password, ca_bundle=ca)
        revision = previous['revision'] + 1
        _write(connection, 'repository', value, revision)
        return public_repository(dict(value, revision=revision))


def _text(form, key, maximum, required=True, strip=True):
    value = form.get(key, '')
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise PublishingError(f'{key} 内容或长度无效。')
    value = value.strip() if strip else value
    if required and not value:
        raise PublishingError('请填写示例类型、文件名和代码。')
    return value


def _seeds():
    root = Path(__file__).resolve().parents[2] / 'examples/tasks'
    entries = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
    for entry in entries:
        entry['code'] = (root / entry.pop('source')).read_text(encoding='utf-8')
        entry['revision'] = 0
    return entries


def examples():
    with store() as connection:
        saved = _read(connection, 'examples')
    return saved['items'] if saved else _seeds()


def save_example(form):
    identifier = form.get('id')
    if identifier is not None and (not isinstance(identifier, str) or identifier and not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identifier)):
        raise PublishingError('示例编号无效。')
    language = form.get('language')
    if not isinstance(language, str) or language not in LANGUAGES:
        raise PublishingError('示例语言无效。')
    value = {key: _text(form, key, bound, required=key in {'title', 'filename', 'code'}, strip=key != 'code')
             for key, bound in [('title',60), ('filename',100), ('description',1000), ('note',2000), ('code',65536)]}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', value['filename']):
        raise PublishingError('下载文件名只允许字母、数字、点、连字符或下划线。')
    if type(form.get('database', False)) is not bool:
        raise PublishingError('数据库说明开关无效。')
    value.update(language=language, database=form.get('database', False))
    with store() as connection:
        connection.execute('BEGIN IMMEDIATE')
        saved = _read(connection, 'examples') or {'items': _seeds(), 'revision': 0}
        items = copy.deepcopy(saved['items'])
        previous = next((item for item in items if item['id'] == identifier), None)
        if identifier and not previous:
            raise PublishingError('示例不存在，请刷新后重试。', 404)
        revision = previous['revision'] if previous else 0
        if type(form.get('revision')) is not int or form['revision'] != revision:
            raise PublishingError('此示例已被修改；编辑内容已保留，请刷新并核对后重试。', 409)
        if any(item['title'] == value['title'] and item['id'] != identifier for item in items):
            raise PublishingError('示例类型名称已存在。')
        if not previous and len(items) >= 100:
            raise PublishingError('最多维护 100 个示例类型。')
        value.update(id=identifier or 'example_' + uuid.uuid4().hex, revision=revision + 1)
        if previous:
            items[items.index(previous)] = value
        else:
            items.append(value)
        _write(connection, 'examples', {'items': items}, saved['revision'] + 1)
    return value
