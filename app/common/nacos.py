"""Nacos reads shared across database handles in the current process."""
from collections import OrderedDict
from copy import deepcopy
import json
import os
import threading
import time

import requests

_clients = OrderedDict()
_clients_lock = threading.Lock()


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


def _request(method, url, **kwargs):
    from app.bootstrap.runtime_metrics import record
    started = time.monotonic()
    try:
        return getattr(requests, method)(url=url, timeout=10, **kwargs)
    finally:
        record('nacos:login' if method == 'post' else 'nacos:config',
               (time.monotonic() - started) * 1000)


class Nacos:
    def __init__(self):
        self.url = os.environ.get('WFS_NACOS_URL', '').rstrip('/')
        self.username = os.environ.get('WFS_NACOS_USERNAME', '')
        self.password = os.environ.get('WFS_NACOS_PASSWORD', '')
        self.config_ttl = float(os.environ.get('WFS_NACOS_CONFIG_TTL_SECONDS', '60'))
        if not 0 <= self.config_ttl <= 3600:
            raise ValueError('WFS_NACOS_CONFIG_TTL_SECONDS must be between 0 and 3600')
        # Identity changes immediately select a different cache, including secret rotation.
        key = (self.url, self.username, self.password)
        with _clients_lock:
            if key not in _clients:
                _clients[key] = _ClientCache()
            self.cache = _clients[key]
            _clients.move_to_end(key)
            while len(_clients) > 32:
                _clients.popitem(last=False)

    @classmethod
    def clear_cache(cls):
        """Forget cached clients; subsequent handles fetch fresh credentials/config."""
        with _clients_lock:
            _clients.clear()

    def invalidate(self, tenant='', data_id='', group=''):
        """Invalidate one config and its auth token for this endpoint/identity."""
        with self.cache.lock:
            self.cache.configs.pop((tenant, data_id, group), None)
            self.cache.token = ''
            self.cache.token_expires = 0

    def _token(self):
        if self.cache.token and time.monotonic() < self.cache.token_expires:
            return self.cache.token
        if not all((self.url, self.username, self.password)):
            raise RuntimeError('Nacos credentials are not configured')
        response = _request('post', self.url + '/v1/auth/login',
                            data={'username': self.username, 'password': self.password})
        response.raise_for_status()
        payload = response.json()
        token = payload['accessToken']
        ttl = float(payload.get('tokenTtl', 300))
        if not isinstance(token, str) or not token or not 0 < ttl < float('inf'):
            raise ValueError('Invalid Nacos authentication response')
        self.cache.token = token
        self.cache.token_expires = time.monotonic() + max(0, ttl - min(30, ttl * .1))
        return token

    def get_nacos_configs(self, tenant='', data_id='', group='', *, force_refresh=False):
        key = (tenant, data_id, group)
        with self.cache.lock:
            cached = self.cache.configs.get(key)
            if not force_refresh and cached and time.monotonic() - cached[0] < self.config_ttl:
                self.cache.configs.move_to_end(key)
                return deepcopy(cached[1])
            self.cache.configs.pop(key, None)
            params = {'tenant': tenant, 'dataId': data_id, 'group': group}
            response = _request('get', self.url + '/v1/cs/configs', params=params,
                                headers={'Authorization': 'Bearer ' + self._token()})
            if response.status_code in (401, 403):
                self.cache.token = ''
                self.cache.configs.clear()
                response = _request('get', self.url + '/v1/cs/configs', params=params,
                                    headers={'Authorization': 'Bearer ' + self._token()})
            if response.status_code in (401, 403):
                self.cache.token = ''
            response.raise_for_status()
            if data_id.endswith('.json'):
                value = json.loads(response.text)
            elif data_id.endswith('.text'):
                value = response.text
            else:
                raise ValueError('Unsupported Nacos configuration format')
            self.cache.configs[key] = (time.monotonic(), deepcopy(value))
            self.cache.configs.move_to_end(key)
            while len(self.cache.configs) > 128:
                self.cache.configs.popitem(last=False)
            return value
