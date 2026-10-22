"""Bounded process-local engine cache; DBAPI connections never cross a fork."""
from collections import OrderedDict
import atexit
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool, QueuePool

_engines = OrderedDict()
_lock = threading.RLock()
_pid = os.getpid()
MAX_PROFILES = 32
IDLE_SECONDS = 300


def engine_for(config, url, connect_args, options=None):
    global _pid
    options = options or {}
    if config.get('pool_enabled', True):
        for name, value, low, high in [
            ('pool_size',options.get('poolSize',config.get('pool_size',3)),1,20),
            ('max_overflow',config.get('max_overflow',2),0,20),
            ('pool_recycle',options.get('poolRecycle',config.get('pool_recycle',600)),30,3600),
            ('pool_timeout',options.get('poolTimeout',config.get('pool_timeout',10)),1,120),
        ]:
            if not low <= int(value) <= high:
                raise ValueError(f'{name} must be between {low} and {high}')
    key = (config.get('dialect'), config.get('id'))
    certificate = None
    if config.get('ssl_ca'):
        try:
            stat = Path(config['ssl_ca']).stat()
            certificate = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
    signature = hashlib.sha256(json.dumps([config, str(url), options, certificate], sort_keys=True, default=str).encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        if _pid != os.getpid():
            for entry in _engines.values():
                entry['engine'].dispose(close=False)
            _engines.clear()
            _pid = os.getpid()
        for candidate, entry in list(_engines.items()):
            if now - entry['used'] > IDLE_SECONDS or candidate == key and entry['signature'] != signature:
                _engines.pop(candidate)['engine'].dispose()
        entry = _engines.get(key)
        if entry:
            entry['used'] = now
            _engines.move_to_end(key)
            return entry['engine']
        kwargs = dict(echo=False, hide_parameters=True, pool_pre_ping=True,
                      connect_args=connect_args, pool_reset_on_return='rollback')
        if config.get('pool_enabled', True):
            kwargs.update(poolclass=QueuePool,
                          pool_size=int(options.get('poolSize', config.get('pool_size', 3))),
                          max_overflow=int(config.get('max_overflow', 2)),
                          pool_recycle=int(options.get('poolRecycle', config.get('pool_recycle', 600))),
                          pool_timeout=int(options.get('poolTimeout', config.get('pool_timeout', 10))))
            if config.get('dialect') == 'sqlite' and url.database == ':memory:':
                kwargs.update(pool_size=1, max_overflow=0, pool_recycle=-1)
        else:
            kwargs['poolclass'] = NullPool
        engine = create_engine(url, **kwargs)
        _engines[key] = {'signature': signature, 'engine': engine, 'used': now}
        while len(_engines) > MAX_PROFILES:
            _engines.popitem(last=False)[1]['engine'].dispose()
        return engine


def dispose(db_id=None):
    with _lock:
        for key in list(_engines):
            if db_id is None or key[1] == db_id:
                _engines.pop(key)['engine'].dispose()


def _after_fork():
    global _lock, _pid
    _lock = threading.RLock()
    for entry in _engines.values():
        entry['engine'].dispose(close=False)
    _engines.clear()
    _pid = os.getpid()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)
atexit.register(dispose)
