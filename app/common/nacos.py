"""Nacos 2.x 客户端：限时读取、进程内共享缓存，以及带版本校验的配置回写。"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import math
import os
import re
import socket
import threading
import time

import requests
from urllib3.exceptions import HTTPError as Urllib3Error
from urllib3.exceptions import ReadTimeoutError

MAX_DOCUMENT_BYTES = 1024 * 1024
_clients = OrderedDict()
_clients_lock = threading.Lock()


class NacosError(requests.HTTPError, RuntimeError):
    """对外只输出固定提示，不携带可能包含密码的 HTTP 响应或请求。"""


class NacosTimeout(NacosError, requests.Timeout):
    pass


class NacosProtocolError(NacosError, ValueError):
    pass


class NacosConflict(NacosError):
    pass


class NacosPublishUncertain(NacosError):
    pass


def _reset_after_fork():
    global _clients, _clients_lock
    _clients = OrderedDict()
    _clients_lock = threading.Lock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_after_fork)


class _ClientCache:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = ''
        self.token_expires = 0
        self.configs = OrderedDict()


def _request(method, url, *, timeout=10, verify=True, **kwargs):
    """不跟随重定向；流式限制响应大小，禁止第三方错误原文进入页面/日志。"""
    from app.bootstrap.runtime_metrics import record
    started = time.monotonic()
    response, deadline_timer = None, None
    deadline_expired = threading.Event()
    try:
        response = getattr(requests, method)(url=url, timeout=timeout, verify=verify,
                                             allow_redirects=False, stream=True, **kwargs)
        if time.monotonic() - started >= timeout:
            raise NacosTimeout('Nacos 请求超时，请检查服务连接。')
        if 300 <= response.status_code < 400:
            raise NacosError('Nacos 返回了重定向，请配置最终服务地址。')
        declared = response.headers.get('Content-Length', '')
        if declared.isdecimal() and int(declared) > MAX_DOCUMENT_BYTES:
            raise NacosProtocolError('Nacos 响应超过 1 MiB，请缩小配置内容。')
        # 已载入的 Response 兼容单元测试；真实网络始终分块读取。
        if isinstance(response._content, bytes):
            content = response._content
        else:
            raw = response.raw
            connection = getattr(raw, '_connection', None)
            transport = getattr(connection, 'sock', None)
            if transport is None:
                # HTTP/1.0 或 Connection: close 已从连接对象释放 socket，但响应仍持有它。
                buffered = getattr(getattr(raw, '_fp', None), 'fp', None)
                transport = getattr(getattr(buffered, 'raw', None), '_sock', None)
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise NacosTimeout('Nacos 请求超时，请检查服务连接。')
            if transport is not None:
                transport.settimeout(remaining)
                def expire():
                    deadline_expired.set()
                    try:
                        transport.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                # read timeout 仅限制空闲时间；截止定时器同时截断持续滴流/压缩块读取。
                deadline_timer = threading.Timer(remaining, expire)
                deadline_timer.daemon = True
                deadline_timer.start()
            reader = getattr(raw, 'read1', None)
            chunks, size = [], 0
            while True:
                if deadline_expired.is_set() or time.monotonic() - started >= timeout:
                    raise NacosTimeout('Nacos 请求超时，请检查服务连接。')
                # read1 优先返回已可用的数据；旧 urllib3 回退为逐字节读取。
                chunk = reader(4096, decode_content=True) if reader else raw.read(1, decode_content=True)
                if deadline_expired.is_set() or time.monotonic() - started >= timeout:
                    raise NacosTimeout('Nacos 请求超时，请检查服务连接。')
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    raise NacosProtocolError('Nacos 响应超过 1 MiB，请缩小配置内容。')
                chunks.append(chunk)
            content = b''.join(chunks)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise NacosProtocolError('Nacos 响应超过 1 MiB，请缩小配置内容。')
        response._content, response._content_consumed = content, True
        response.encoding = 'utf-8'
        return response
    except NacosError:
        raise
    except (requests.Timeout, ReadTimeoutError):
        raise NacosTimeout('Nacos 请求超时，请检查服务连接。') from None
    except (requests.RequestException, Urllib3Error, OSError, ValueError):
        if deadline_expired.is_set() or time.monotonic() - started >= timeout:
            raise NacosTimeout('Nacos 请求超时，请检查服务连接。') from None
        raise NacosError('Nacos 请求失败，请检查地址、网络和证书设置。') from None
    finally:
        if deadline_timer is not None:
            deadline_timer.cancel()
        if response is not None and response.raw is not None:
            response.close()
        metric = 'nacos:login' if url.endswith('/auth/login') else 'nacos:config'
        record(metric, (time.monotonic() - started) * 1000)


def _check_status(response):
    if response.status_code in (401, 403):
        raise NacosError('Nacos 认证失败或没有配置访问权限，请检查账号授权。')
    if response.status_code == 404:
        raise NacosError('Nacos 配置不存在，请检查 Namespace、Group 和 Data ID。')
    if not 200 <= response.status_code < 300:
        raise NacosError('Nacos 服务未能完成请求，请检查服务状态。')


def _document(content):
    try:
        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError()
                value[key] = item
            return value
        value = json.loads(content, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (TypeError, ValueError, RecursionError):
        raise NacosProtocolError('Nacos 数据库配置必须为有效 JSON 对象，字段不能重复。') from None


class Nacos:
    def __init__(self, config=None):
        from app.bootstrap import nacos_config
        value = nacos_config.saved() if config is None else {**nacos_config.defaults(), **config}
        value = nacos_config.validate(value, previous=value)
        self.url, self.username, self.password = value['url'], value['username'], value['password']
        self.auth_enabled = value['auth_enabled']
        self.config_ttl, self.timeout = value['config_ttl'], value['timeout']
        self.verify = value['ca_file'] or value['verify_tls']
        # 身份、认证和证书设置一并隔离，避免轮换密钥后仍命中旧配置。
        key = (self.url, self.username, self.password, self.auth_enabled, self.verify, self.config_ttl, self.timeout)
        with _clients_lock:
            if key not in _clients:
                _clients[key] = _ClientCache()
            self.cache = _clients[key]
            _clients.move_to_end(key)
            while len(_clients) > 32:
                _clients.popitem(last=False)

    @classmethod
    def clear_cache(cls):
        with _clients_lock:
            _clients.clear()

    def invalidate(self, tenant='', data_id='', group=''):
        with self.cache.lock:
            self.cache.configs.pop((tenant, data_id, group), None)
            self.cache.token = ''
            self.cache.token_expires = 0

    def _request(self, method, suffix, **kwargs):
        if not self.url:
            raise NacosError('尚未配置 Nacos 服务地址。')
        return _request(method, self.url + suffix, timeout=self.timeout, verify=self.verify, **kwargs)

    def _token(self):
        if not self.auth_enabled:
            return ''
        if self.cache.token and time.monotonic() < self.cache.token_expires:
            return self.cache.token
        response = self._request('post', '/v1/auth/login', data={'username': self.username, 'password': self.password})
        _check_status(response)
        try:
            payload = response.json()
            token, ttl = payload['accessToken'], float(payload.get('tokenTtl', 300))
            if (not isinstance(token, str) or not token or len(token) > 16384 or
                    any(ord(c) < 32 for c in token) or not math.isfinite(ttl) or ttl <= 0):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise NacosProtocolError('Nacos 认证响应无效，请检查版本和认证设置。') from None
        self.cache.token = token
        self.cache.token_expires = time.monotonic() + max(0, ttl - min(30, ttl * .1))
        return token

    def authenticate(self):
        """仅认证，不发布测试配置；关闭认证时还需指定配置做读取探测。"""
        with self.cache.lock:
            self.cache.token = ''
            self._token()
        return {'authenticated': self.auth_enabled}

    def test_connection(self, binding=None):
        """候选连接仅登录或读取指定配置，测试不会产生远端写入。"""
        if binding is not None:
            self.read_document(binding, force_refresh=True)
            return {'ready': True, 'verified': 'config_read'}
        if not self.auth_enabled:
            raise ValueError('未启用 Nacos 认证，请提供一份探测配置以验证只读连接。')
        self.authenticate()
        return {'ready': True, 'verified': 'authentication'}

    def _headers(self):
        token = self._token()
        return {'Authorization': 'Bearer ' + token} if token else {}

    def _raw(self, tenant, data_id, group, force_refresh=False):
        key = (tenant, data_id, group)
        with self.cache.lock:
            cached = self.cache.configs.get(key)
            if not force_refresh and cached and time.monotonic() - cached[0] < self.config_ttl:
                self.cache.configs.move_to_end(key)
                return cached[1]
            # TTL 失效或强刷失败时不降级返回旧密码/旧地址。
            self.cache.configs.pop(key, None)
            params = {'tenant': tenant, 'dataId': data_id, 'group': group}
            response = self._request('get', '/v1/cs/configs', params=params, headers=self._headers())
            if response.status_code in (401, 403) and self.auth_enabled:
                self.cache.token = ''
                self.cache.configs.clear()
                response = self._request('get', '/v1/cs/configs', params=params, headers=self._headers())
            if response.status_code in (401, 403):
                self.cache.token = ''
            _check_status(response)
            try:
                return response.content.decode('utf-8')
            except UnicodeDecodeError:
                raise NacosProtocolError('Nacos 配置必须使用 UTF-8 编码。') from None

    def _remember(self, key, content):
        self.cache.configs[key] = (time.monotonic(), content)
        self.cache.configs.move_to_end(key)
        while len(self.cache.configs) > 128:
            self.cache.configs.popitem(last=False)

    def get_nacos_configs(self, tenant='', data_id='', group='', *, force_refresh=False):
        """保留旧 JSON/text 读取入口；解析成功后才写入缓存。"""
        with self.cache.lock:
            content = self._raw(tenant, data_id, group, force_refresh)
            if data_id.endswith('.json'):
                value = _document(content)
            elif data_id.endswith('.text'):
                value = content
            else:
                raise ValueError('Unsupported Nacos configuration format')
            key = (tenant, data_id, group)
            if key not in self.cache.configs:
                self._remember(key, content)
            return deepcopy(value)

    def read_document(self, binding, force_refresh=False):
        from app.bootstrap.nacos_bindings import validate
        binding = validate(binding)
        key = (binding['namespace'], binding['data_id'], binding['group'])
        with self.cache.lock:
            content = self._raw(*key, force_refresh=force_refresh)
            document = _document(content)
            if key not in self.cache.configs:
                self._remember(key, content)
            return {'content': content, 'document': document,
                    'md5': hashlib.md5(content.encode('utf-8')).hexdigest()}

    def publish_document(self, binding, document, expected_md5):
        """Nacos 2.x casMd5 是请求头；单次写入之后必须只读核验，不盲目重试。"""
        from app.bootstrap.nacos_bindings import validate
        binding = validate(binding)
        if not isinstance(expected_md5, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', expected_md5):
            raise ValueError('保存前请先读取 Nacos 配置，缺少有效版本。')
        try:
            content = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
            _document(content)
            if len(content.encode('utf-8')) > MAX_DOCUMENT_BYTES:
                raise ValueError()
        except (TypeError, ValueError, RecursionError):
            raise ValueError('待发布配置必须为不超过 1 MiB 的有效 JSON 对象。') from None
        expected_md5 = expected_md5.lower()
        desired_md5 = hashlib.md5(content.encode('utf-8')).hexdigest()
        key = (binding['namespace'], binding['data_id'], binding['group'])
        with self.cache.lock:
            # 预读拒绝已经删除或变更的配置，CAS 头继续保护预读与写入之间的竞态。
            current = self.read_document(binding, force_refresh=True)
            if current['md5'] != expected_md5:
                raise NacosConflict('Nacos 配置已被其他人修改，请重新读取后再保存。')
            headers = {**self._headers(), 'casMd5': expected_md5}
            self.cache.configs.pop(key, None)
            uncertain, response = False, None
            try:
                response = self._request('post', '/v1/cs/configs', headers=headers,
                    data={'tenant': key[0], 'dataId': key[1], 'group': key[2], 'content': content, 'type': 'json'})
            except NacosError:
                # 网络/协议异常可能发生在服务器已提交之后，后续只读确认。
                uncertain = True
            finally:
                self.cache.configs.pop(key, None)
            if response is not None:
                try:
                    result = response.json()
                except ValueError:
                    result = None
                # 2.4 的 CAS 冲突是 HTTP 500 + errorCode=20005；兼容网关的 409。
                conflict = response.status_code == 409 or (isinstance(result, dict) and
                    (result.get('code') in (20005, '20005') or result.get('errorCode') in (20005, '20005')))
                if conflict:
                    raise NacosConflict('Nacos 配置已被其他人修改，请重新读取后再保存。')
                if 400 <= response.status_code < 500:
                    _check_status(response)
                uncertain = not (200 <= response.status_code < 300 and result is True)
            # Nacos 的发布落库与 GET 缓存更新并非同步：只短暂重读旧版本，绝不重发 POST。
            for delay in (0, .05, .15, .3):
                if delay:
                    time.sleep(delay)
                try:
                    verified = self.read_document(binding, force_refresh=True)
                except NacosError:
                    raise NacosPublishUncertain('无法确认 Nacos 写入结果，请重新读取配置核对；请勿直接重复提交。') from None
                if verified['md5'] == desired_md5:
                    return {'md5': desired_md5}
                self.cache.configs.pop(key, None)
                if verified['md5'] != expected_md5:
                    if not uncertain:
                        raise NacosConflict('Nacos 保存后配置再次发生变化，请重新读取后确认。')
                    break
            raise NacosPublishUncertain('无法确认 Nacos 写入结果，请重新读取配置核对；请勿直接重复提交。')
