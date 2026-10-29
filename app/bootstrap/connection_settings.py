"""Encrypted connection profiles, independent of the platform database.

Platform selection is frozen on first use in each process. Restart every Web
and Scheduler worker together after saving; business profiles are read when a
task opens a new connection. SQLite transactions protect concurrent edits.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from contextlib import contextmanager

from app.bootstrap.global_vars import DATA_DIR

_active = {}
_lock = threading.Lock()
PROFILE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,99}')


def _path():
    return Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'database-connections.sqlite3'


def _key(scope):
    secret = os.environ.get('WFS_CONNECTIONS_KEY') or os.environ.get('WFS_SECRET_KEY')
    if not secret and scope == 'business' and os.environ.get('WFS_TASK_DATABASE_KEY'):
        return os.environ['WFS_TASK_DATABASE_KEY'].encode()
    if not secret:
        raise ValueError('请先配置 WFS_SECRET_KEY 或独立的 WFS_CONNECTIONS_KEY。')
    key = hashlib.sha256(b'wfs:database-connections:v1:' + scope.encode() + b'\0' + secret.encode()).digest()
    return base64.urlsafe_b64encode(key)


def _cipher(scope):
    from cryptography.fernet import Fernet
    return Fernet(_key(scope))


def task_database_key():
    return _key('business').decode() if _path().exists() else ''


@contextmanager
def _store():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        if os.name != 'nt':
            path.chmod(0o600)
        db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL)')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _decode(payload, identifier):
    from cryptography.fernet import InvalidToken
    try:
        return json.loads(_cipher('platform' if identifier in {'platform','@active-platform'} else 'business').decrypt(payload))
    except InvalidToken:
        raise ValueError('连接配置无法解密，请恢复原加密密钥；配置文件未被改写。') from None


def profiles():
    with _store() as db:
        rows = db.execute("SELECT id,revision,payload FROM profiles WHERE id NOT LIKE '@%' ORDER BY id").fetchall()
    return {identifier: {**_decode(payload, identifier), 'revision': revision} for identifier, revision, payload in rows}


def business_profile(identifier):
    scoped = os.environ.get('WFS_TASK_CONNECTIONS_JSON')
    if scoped is not None:
        profile = json.loads(scoped).get(identifier)
        if identifier == 'platform' or not profile:
            raise PermissionError('此任务未获授权使用业务连接：' + str(identifier))
        if not profile.get('enabled',True): raise PermissionError('业务连接已停用：'+identifier)
        return profile
    if identifier == 'platform' or not isinstance(identifier, str) or not PROFILE_ID.fullmatch(identifier) or not _path().exists():
        return None
    with _store() as db:
        row = db.execute('SELECT payload FROM profiles WHERE id=?', (identifier,)).fetchone()
    value=_decode(row[0],identifier) if row else None
    if value and not value.get('enabled',True): raise PermissionError('业务连接已停用：'+identifier)
    return value


def active_platform():
    if os.environ.get('WFS_IGNORE_MANAGED_DATABASE', '').lower() == 'true':
        return None
    key = str(_path().resolve())
    with _lock:
        if key not in _active:
            # No file is created merely by starting a legacy deployment.
            if _path().exists():
                with _store() as db:
                    row = db.execute("SELECT payload FROM profiles WHERE id='@active-platform'").fetchone()
                _active[key] = _decode(row[0], '@active-platform') if row else None
            else:
                _active[key] = None
        return copy.deepcopy(_active[key])


def activate_at_app_start():
    """Only app startup promotes a pending platform profile.

    A new task subprocess must keep reading the old active profile after an
    administrator saves a pending edit. Stop ALL services before restarting.
    """
    if os.environ.get('WFS_IGNORE_MANAGED_DATABASE', '').lower() == 'true' or not _path().exists():
        return
    with _store() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT revision,payload FROM profiles WHERE id='platform'").fetchone()
        if row:
            profile = {**_decode(row[1], 'platform'), 'revision': row[0]}
            payload = _cipher('platform').encrypt(json.dumps(profile, ensure_ascii=False).encode())
            db.execute("INSERT OR REPLACE INTO profiles(id,revision,payload) VALUES('@active-platform',?,?)", (row[0], payload))


def public_profile(profile):
    return {**{key: value for key, value in profile.items() if key != 'password'},
            'password_set': bool(profile.get('password'))}


def validate(form):
    if not isinstance(form, dict):
        raise ValueError('连接信息必须为对象。')
    identifier = form.get('id')
    if not isinstance(identifier, str) or not PROFILE_ID.fullmatch(identifier):
        raise ValueError('连接标识应以字母开头，最多 100 位，仅使用字母、数字、下划线或连字符。')
    previous = profiles().get(identifier, {})
    from app.common.db.catalog import DATABASES, normalize
    dialect = normalize(form.get('dialect', previous.get('dialect', 'mysql')))
    if dialect not in DATABASES or identifier == 'platform' and dialect != 'mysql':
        raise ValueError('平台库仅支持 MySQL/PolarDB；请为业务库选择已支持的数据库类型。')
    local = dialect == 'sqlite'
    result = {'id': identifier, 'dialect': dialect, 'charset': 'utf8mb4'}
    for key, maximum in [('host', 253), ('database', 64), ('user', 100)]:
        value = '' if local and key != 'database' else form.get(key)
        if local and key != 'database':
            result[key] = ''; continue
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 33 for c in value):
            raise ValueError('请填写有效的数据库地址、库名和用户名。')
        result[key] = value.strip()
    pattern = r'[A-Za-z0-9_][A-Za-z0-9_.-]*' if local else r'[A-Za-z0-9_$.-]+'
    if any(c in result['host'] for c in '/\\@?#') or not re.fullmatch(pattern, result['database']) or local and '..' in result['database']:
        raise ValueError('地址请只填主机名或 IP；数据库名称请使用字母、数字、下划线、美元符号或连字符。')
    try:
        raw_port = form.get('port')
        port = int(DATABASES[dialect]['port'] or 1) if raw_port in (None, '') else int(raw_port)
        revision = int(form.get('revision', 0))
    except (ValueError, TypeError):
        raise ValueError('端口或配置版本无效。') from None
    if not 1 <= port <= 65535 or revision < 0:
        raise ValueError('端口应在 1 至 65535 之间。')
    password = form.get('password', '')
    if not isinstance(password, str) or len(password) > 1024:
        raise ValueError('密码格式或长度无效。')
    result.update(port=port, revision=revision, password='' if local else password or previous.get('password', ''))
    if not result['password'] and not local:
        raise ValueError('新连接必须填写数据库密码。')
    mode = 'disabled' if local else form.get('tls', previous.get('tls', 'disabled'))
    if mode not in {'verify_identity', 'disabled'}:
        raise ValueError('TLS 配置无效。')
    ca = form.get('ssl_ca', '')
    if not isinstance(ca, str) or len(ca) > 1024 or '\x00' in ca:
        raise ValueError('CA 证书路径无效。')
    if mode == 'verify_identity' and (not ca or not Path(ca).is_file()):
        raise ValueError('启用 TLS 时请填写此服务器上有效的 CA 证书文件路径。')
    result.update(tls=mode, ssl_ca=ca if mode == 'verify_identity' else '')
    for key, default, minimum, maximum in [('pool_size',3,1,20),('max_overflow',2,0,20),('pool_recycle',600,30,3600),('pool_timeout',10,1,120)]:
        try:
            value = int(form.get(key, previous.get(key, default)))
        except (TypeError, ValueError):
            raise ValueError('连接池参数无效。') from None
        if not minimum <= value <= maximum:
            raise ValueError(f'{key} 应在 {minimum} 至 {maximum} 之间。')
        result[key] = value
    for key,maximum in [('name',100),('purpose',500),('owner',100),('environment',30)]:
        value=form.get(key,previous.get(key,''))
        if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 for c in value):
            raise ValueError('连接说明格式无效。')
        result[key]=value.strip()
    result['enabled']=form.get('enabled',previous.get('enabled',True))
    if type(result['enabled'])is not bool: raise ValueError('连接启用状态无效。')
    if identifier=='platform' and not result['enabled']: raise ValueError('不能在此停用平台库。')
    result['pool_enabled'] = form.get('pool_enabled', previous.get('pool_enabled', True))
    if not isinstance(result['pool_enabled'], bool):
        raise ValueError('连接池开关必须为布尔值。')
    return result


def save(profile):
    """Compare-and-swap the revision, without ever returning plaintext secrets."""
    with _store() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision FROM profiles WHERE id=?', (profile['id'],)).fetchone()
        version = row[0] if row else 0
        if version != profile['revision']:
            raise RuntimeError('连接信息已被修改，请刷新后重试。')
        payload = _cipher('platform' if profile['id'] == 'platform' else 'business').encrypt(json.dumps(profile, ensure_ascii=False).encode())
        db.execute('INSERT OR REPLACE INTO profiles(id,revision,payload) VALUES(?,?,?)',
                   (profile['id'], version + 1, payload))
    return {**public_profile(profile), 'revision': version + 1}


def connect_mysql(profile):
    import pymysql
    options = dict(host=profile['host'], port=int(profile['port']), user=profile['user'],
                   password=profile['password'], database=profile['database'], charset='utf8mb4',
                   autocommit=True, connect_timeout=5, read_timeout=10, write_timeout=10,
                   local_infile=False)
    if profile.get('tls') == 'verify_identity':
        options.update(ssl_ca=profile['ssl_ca'], ssl_verify_cert=True, ssl_verify_identity=True)
    else:
        options['ssl_disabled'] = True
    return pymysql.connect(**options)


def schema_check(connection):
    """Read-only schema check; normal saves never execute DDL."""
    schema = Path(__file__).with_name('mysql_schema.sql').read_text(encoding='utf-8')
    tables = re.findall(r'CREATE TABLE IF NOT EXISTS (wfs_\w+)\s*\((.*?)\) ENGINE', schema, re.S)
    missing = []
    with connection.cursor() as cursor:
        for table, definition in tables:
            cursor.execute('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s AND engine=%s', (table, 'InnoDB'))
            if cursor.fetchone()[0] != 1:
                missing.append(table)
                continue
            expected = set(re.findall(r'(?:^|,)\s*([a-z_]\w*)\s+(?:varchar|datetime|int|bigint|longtext|text)\b', definition))
            cursor.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s', (table,))
            actual = {row[0] for row in cursor.fetchall()}
            missing.extend(f'{table}.{column}' for column in sorted(expected - actual))
        if 'wfs_platform_lock' not in missing:
            cursor.execute('SELECT id FROM wfs_platform_lock WHERE id=1')
            if not cursor.fetchone():
                missing.append('wfs_platform_lock: row 1')
    return missing


def probe(profile, initialize=False):
    if profile['id'] != 'platform':
        if initialize:
            raise ValueError('初始化仅适用于平台库。')
        return probe_business(profile)
    from contextlib import closing
    import pymysql
    try:
        with closing(connect_mysql(profile)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT VERSION(), DATABASE(), @@read_only')
                version, database, read_only = cursor.fetchone()
                major = re.match(r'^(\d+)\.', version)
                if profile['id'] == 'platform' and (not major or int(major[1]) < 8 or 'MariaDB' in version):
                    raise ValueError('平台数据库适配目标为 MySQL 8.0 及以上，请核对 PolarDB 的 MySQL 兼容版本。')
                if read_only:
                    raise ValueError('请使用允许写入的主地址或集群地址，当前连接为只读。')
                if initialize:
                    cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'wfs\\_%'")
                    if cursor.fetchone()[0]:
                        raise ValueError('此库已有平台表，请先核对结构；初始化仅支持没有平台表的新库。')
                    # MySQL DDL commits implicitly. Keep schema idempotent and
                    # never report that a failed initialization was rolled back.
                    from scripts.migrate import statements
                    for statement in statements(Path(__file__).with_name('mysql_schema.sql')):
                        cursor.execute(statement)
            missing = schema_check(connection) if profile['id'] == 'platform' else []
            return {'connected': True, 'ready': not missing, 'version': version,
                    'database': database, 'missing': missing}
    except pymysql.MySQLError as exc:
        # Driver text may include usernames, SQL or secrets. Never return it.
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else 0
        raise ValueError(f'数据库连接或初始化失败（错误码 {code}）。请检查地址、白名单、账号权限和 TLS 配置；初始化失败时请先核对已建表。') from None


def probe_business(profile):
    import uuid
    from app.common.db.factory import adapter_for
    from app.common.db.engine_pool import dispose
    identifier = '@probe-' + uuid.uuid4().hex
    adapter = None
    try:
        adapter = adapter_for({**profile, 'id': identifier, 'pool_enabled': False})
        sql = {'sqlite': 'SELECT sqlite_version()', 'mysql': 'SELECT VERSION()',
               'postgresql': 'SELECT version()', 'clickhouse': 'SELECT version()'}[profile['dialect']]
        version = adapter.execute_query_sql(sql)[0][0]
        return {'connected': True, 'ready': True, 'version': str(version), 'database': profile['database'], 'missing': []}
    except RuntimeError:
        raise ValueError('当前服务缺少此数据库的驱动，请先按页面提示安装对应驱动。') from None
    except Exception:
        raise ValueError('数据库连接测试失败。请核对地址、网络、驱动、账户权限和加密设置。') from None
    finally:
        if adapter is not None:
            adapter.close()
        dispose(identifier)
