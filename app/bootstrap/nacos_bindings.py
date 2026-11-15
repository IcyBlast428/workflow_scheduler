"""将每份 Nacos JSON 映射为统一连接字段，并保留不归平台管理的原字段。"""
import base64
from copy import deepcopy
import re

DEFAULT_FIELDS = {'host': 'host', 'port': 'port', 'database': 'db', 'user': 'user',
                  'password': 'password', 'schema': 'schema'}


def validate(binding):
    if not isinstance(binding, dict):
        raise ValueError('Nacos 配置定位必须为对象。')
    result = {}
    for key, default, limit in (('namespace', '', 128), ('group', 'DEFAULT_GROUP', 128), ('data_id', '', 255)):
        value = binding.get(key, default)
        if (not isinstance(value, str) or len(value) > limit or
                any(ord(c) < 32 for c in value) or '\\' in value):
            raise ValueError('Nacos Namespace、Group 或 Data ID 格式无效。')
        result[key] = value.strip()
    if not result['group'] or not result['data_id']:
        raise ValueError('请填写 Nacos Group 和 Data ID。')
    encoding = binding.get('password_encoding', 'plain')
    if encoding not in ('plain', 'base64'):
        raise ValueError('密码编码只能选择明文或 Base64。')
    result['password_encoding'] = encoding
    fields = binding.get('fields', {})
    if not isinstance(fields, dict) or set(fields) - set(DEFAULT_FIELDS):
        raise ValueError('Nacos 字段映射无效。')
    fields = {**DEFAULT_FIELDS, **fields}
    for field in fields.values():
        if (not isinstance(field, str) or not field.strip() or field != field.strip() or
                len(field) > 128 or any(ord(c) < 32 for c in field)):
            raise ValueError('Nacos 字段映射必须为非空 JSON 字段名。')
    if len(set(fields.values())) != len(fields):
        raise ValueError('Nacos 字段映射不能使用重复的 JSON 字段名。')
    result['fields'] = fields
    return result


def _values(binding, document):
    if not isinstance(document, dict):
        raise ValueError('Nacos 数据库配置必须为 JSON 对象。')
    value = {}
    for standard, field in binding['fields'].items():
        if standard == 'schema' and field not in document:
            continue
        if field not in document:
            raise ValueError('Nacos 数据库配置缺少受管连接字段，请检查字段映射。')
        candidate = document[field]
        if standard == 'port':
            if isinstance(candidate, str) and re.fullmatch(r'[0-9]{1,5}', candidate):
                candidate = int(candidate)
            if type(candidate) is not int or not 1 <= candidate <= 65535:
                raise ValueError('Nacos 数据库端口必须为 1 至 65535。')
        elif not isinstance(candidate, str) or len(candidate) > 4096:
            raise ValueError('Nacos 数据库连接字段必须为有效字符串。')
        if standard in ('host', 'database', 'user') and (not candidate.strip() or any(ord(c) < 32 for c in candidate)):
            raise ValueError('Nacos 数据库地址、库名和账号不能为空或包含控制字符。')
        if standard == 'password' and binding['password_encoding'] == 'base64':
            try:
                candidate = base64.b64decode(candidate, validate=True).decode('utf-8')
            except (ValueError, UnicodeError):
                raise ValueError('Nacos 密码不是有效的 UTF-8 Base64 内容，请检查编码设置。') from None
        if standard == 'password' and not candidate:
            raise ValueError('Nacos 数据库密码不能为空，请修复远端配置；不会使用本地旧密码。')
        value[standard] = candidate
    return value


def read(binding, force_refresh=False, client=None):
    from app.common.nacos import Nacos
    binding = validate(binding)
    result = (client or Nacos()).read_document(binding, force_refresh=force_refresh)
    return {'values': _values(binding, result['document']), 'md5': result['md5'],
            'document': deepcopy(result['document'])}


def merge(binding, document, values):
    """只修改明确提供的受管字段；密码编码显式选择，不猜测内容。"""
    binding = validate(binding)
    if not isinstance(document, dict) or not isinstance(values, dict) or set(values) - set(DEFAULT_FIELDS):
        raise ValueError('Nacos 配置和连接字段必须为有效对象。')
    result = deepcopy(document)
    for standard, value in values.items():
        if standard == 'password' and binding['password_encoding'] == 'base64':
            if not isinstance(value, str):
                raise ValueError('数据库密码必须为字符串。')
            value = base64.b64encode(value.encode('utf-8')).decode('ascii')
        result[binding['fields'][standard]] = value
    _values(binding, result)
    return result


def publish(binding, values, expected_md5, client=None):
    from app.common.nacos import Nacos, NacosConflict
    binding = validate(binding)
    if not isinstance(expected_md5, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', expected_md5):
        raise ValueError('保存前请先读取 Nacos 配置，缺少有效版本。')
    client = client or Nacos()
    current = client.read_document(binding, force_refresh=True)
    if current['md5'] != expected_md5.lower():
        raise NacosConflict('Nacos 配置已被其他人修改，请重新读取后再保存。')
    document = merge(binding, current['document'], values)
    return client.publish_document(binding, document, expected_md5)
