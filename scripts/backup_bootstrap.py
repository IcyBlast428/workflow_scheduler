"""Collect only encrypted platform bootstrap evidence, never keys or target paths."""
import base64
import hashlib
import os
from pathlib import Path
import stat
import zipfile

NAMES = {'pending': 'bootstrap/platform-connection.enc', 'active': 'bootstrap/platform-active.enc'}


def collect(data):
    configured = os.environ.get('WFS_PLATFORM_CONFIG_FILE')
    active = os.environ.get('WFS_PLATFORM_ACTIVE_CONFIG_FILE')
    paths = {'pending': Path(configured) if configured else Path(data) / 'platform-connection.enc',
             'active': Path(active) if active else None}
    files, manifest = {}, {'automatic_restore': False, 'keys_included': False}
    for role, path in paths.items():
        entry = {'included': False, 'role': 'saved_for_next_restart' if role == 'pending' else 'service_start_snapshot'}
        manifest[role] = entry
        if path is None:
            continue
        if path.is_symlink():
            raise ValueError('平台连接备份不接受符号链接。')
        if not path.exists():
            if role == 'pending' and configured:
                raise ValueError('显式指定的平台连接配置文件不存在，备份未创建。')
            continue
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('平台连接配置文件类型或大小无效，备份未创建。')
        content = path.read_bytes()
        try:
            decoded = base64.b64decode(content, altchars=b'-_', validate=True)
        except (ValueError, TypeError):
            decoded = b''
        if len(decoded) < 73 or decoded[0] != 0x80:
            raise ValueError('平台连接配置不是有效的密文格式，拒绝把明文配置加入备份。')
        name = NAMES[role]
        files[name] = content
        entry.update(included=True, archive_path=name, sha256=hashlib.sha256(content).hexdigest())
    return files, manifest


def write(archive, files):
    for name, content in files.items():
        entry = zipfile.ZipInfo(name)
        entry.create_system = 3
        entry.external_attr = (stat.S_IFREG | 0o600) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, content)


def verify(archive, manifest):
    configuration = manifest.get('platform_configuration')
    if configuration is None:
        return  # Older platform archives contain no bootstrap evidence.
    if not isinstance(configuration, dict):
        raise ValueError('平台连接备份清单无效。')
    for role, name in NAMES.items():
        entry = configuration.get(role)
        if not isinstance(entry, dict) or type(entry.get('included')) is not bool:
            raise ValueError('平台连接备份清单无效。')
        if not entry['included']:
            continue
        if entry.get('archive_path') != name:
            raise ValueError('平台连接备份路径无效。')
        try:
            if archive.getinfo(name).file_size > 65536:
                raise ValueError('平台连接备份内容过大。')
            digest = hashlib.sha256(archive.read(name)).hexdigest()
        except KeyError:
            raise ValueError('平台连接备份内容缺失。') from None
        if digest != entry.get('sha256'):
            raise ValueError('平台连接备份摘要校验失败。')


def receipt_plan(files, manifest, *, database, schema, host, port, container=None):
    """Authorize a receipt only against an independently verified dump endpoint."""
    def skipped(reason):
        return {'write_requested': False, 'written': False, 'reason': reason}, None
    active_path = os.environ.get('WFS_PLATFORM_ACTIVE_CONFIG_FILE')
    if not active_path:
        if manifest['pending']['included']:
            return skipped('pending_configuration_is_not_active_evidence')
    if active_path and not manifest['active']['included']:
        return skipped('active_configuration_unavailable')
    if container:
        return skipped('container_dump_endpoint_not_verified')
    try:
        import json
        from app.bootstrap import platform_config
        if active_path:
            options = json.loads(platform_config._cipher().decrypt(files[NAMES['active']]))
            baseline = {**platform_config.defaults(), **options}
            options = platform_config.validate(baseline, previous=baseline)
        else:
            # Even pre-bootstrap deployments must match the explicitly dumped
            # endpoint before writing a receipt through their service settings.
            options = platform_config.defaults()
        if options['source'] == 'service':
            # Resolve service configuration without opening a database connection.
            from app.bootstrap.database import GaussDB, _split_db_id
            from app.bootstrap.helpers import get_runtime_env
            db_name, namespace = _split_db_id(options['db_id'])
            reader = object.__new__(GaussDB)
            reader.current_env = get_runtime_env()
            resolved = reader._GaussDB__get_db_config(db_name, namespace)
            password = resolved.get('password', '')
            if password and reader.current_env == 'production':
                password = base64.b64decode(password).decode('utf-8')
            options = {**options, 'source': 'direct', 'host': resolved['host'],
                       'port': int(resolved['port']), 'database': resolved['db'],
                       'schema': namespace, 'user': resolved['user'], 'password': password}
        expected = (str(host).lower().rstrip('.'), int(port), database, schema)
        actual = (str(options['host']).lower().rstrip('.'), int(options['port']), options['database'], options['schema'])
        if actual != expected:
            return skipped('active_configuration_does_not_match_dump_target')
        # Freeze the resolved endpoint for the receipt; do not re-read a staged
        # profile or resolve a changing service address again during the write.
        options = platform_config.validate(options, previous=options)
        return {'write_requested': True, 'written': None, 'reason': 'active_target_verified' if active_path else 'service_target_verified'}, options
    except Exception:
        return skipped('active_configuration_target_could_not_be_verified')
