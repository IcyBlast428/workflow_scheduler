"""Collect encrypted platform and Nacos bootstrap evidence, never keys or target paths."""
import base64
import hashlib
import os
from pathlib import Path
import stat
import zipfile

NAMES = {'pending': 'bootstrap/platform-connection.enc', 'active': 'bootstrap/platform-active.enc',
         'nacos': 'bootstrap/nacos-connection.enc'}


def collect(data):
    """分别保存待生效密文与本次启动快照；不把外部路径或解密密钥写入清单。"""
    configured = os.environ.get('WFS_PLATFORM_CONFIG_FILE')
    active = os.environ.get('WFS_PLATFORM_ACTIVE_CONFIG_FILE')
    nacos = os.environ.get('WFS_NACOS_CONFIG_FILE')
    paths = {'pending': Path(configured) if configured else Path(data) / 'platform-connection.enc',
             'active': Path(active) if active else None,
             'nacos': Path(nacos) if nacos else Path(data) / 'nacos-connection.enc'}
    files, manifest = {}, {'automatic_restore': False, 'keys_included': False}
    for role, path in paths.items():
        roles = {'pending': 'saved_for_next_restart', 'active': 'service_start_snapshot',
                 'nacos': 'configuration_center_connection'}
        entry = {'included': False, 'role': roles[role]}
        manifest[role] = entry
        if path is None:
            continue
        if path.is_symlink():
            raise ValueError('平台连接备份不接受符号链接。')
        if not path.exists():
            if (role == 'pending' and configured) or (role == 'nacos' and nacos):
                raise ValueError('显式指定的引导连接配置文件不存在，备份未创建。')
            continue
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('平台连接配置文件类型或大小无效，备份未创建。')
        content = path.read_bytes()
        try:
            decoded = base64.b64decode(content, altchars=b'-_', validate=True)
        except (ValueError, TypeError):
            decoded = b''
        # 这里只检查密文封装格式；实际解密与目标核对属于回执计划，不承诺密钥可用。
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
        if role == 'nacos' and entry is None:
            continue  # 旧版本备份没有 Nacos 引导项，仍可正常校验和恢复。
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
    # 待生效文件不能证明当前连接目标；缺少生效证据时宁可不写数据库回执。
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
            frozen_nacos = options.get('_nacos_resolved')
            if frozen_nacos is not None:
                fields = ('host', 'port', 'database', 'schema', 'user', 'password')
                if not isinstance(frozen_nacos, dict) or any(key not in frozen_nacos for key in fields):
                    return skipped('active_configuration_target_could_not_be_verified')
                # 本次启动的实际连接才是证据；远端配置可能已经被编辑或切换。
                options = {**options, **{key: frozen_nacos[key] for key in fields}, 'source': 'direct'}
            elif options.get('source') == 'nacos':
                return skipped('nacos_configuration_has_no_frozen_active_evidence')
            baseline = {**platform_config.defaults(), **options}
            options = platform_config.validate(baseline, previous=baseline)
        else:
            # Even pre-bootstrap deployments must match the explicitly dumped
            # endpoint before writing a receipt through their service settings.
            options = platform_config.defaults()
        if options['source'] == 'nacos':
            return skipped('nacos_configuration_has_no_frozen_active_evidence')
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
        # 清单先于回执写入封装，None 表示将尝试写入，不能伪称数据库已经确认。
        return {'write_requested': True, 'written': None, 'reason': 'active_target_verified' if active_path else 'service_target_verified'}, options
    except Exception:
        return skipped('active_configuration_target_could_not_be_verified')
