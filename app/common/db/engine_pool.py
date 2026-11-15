"""业务引擎缓存，每个任务进程独立持有自己的连接池。

同一进程内重复创建 NewDB 可复用引擎；不同执行进程之间不会复用连接。
缓存的是引擎和池，不是可由多个线程同时使用的单个连接/事务。
"""
from collections import OrderedDict
import atexit
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool, QueuePool

_engines = OrderedDict()
_lock = threading.RLock()
_pid = os.getpid()
MAX_PROFILES = 32
IDLE_SECONDS = 300


def engine_for(config, url, connect_args, options=None):
    """按类型与连接标识复用引擎；配置或证书变化时为后续借用换用新池。"""
    global _pid
    options = options or {}
    if config.get('pool_enabled', True):
        for name, value, low, high in [
            ('pool_size',options.get('poolSize',config.get('pool_size',1)),1,20),
            ('max_overflow',config.get('max_overflow',1),0,20),
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
    # 指纹包含完整配置（含密码）及证书元信息；不可把原始输入输出到监测接口。
    signature = hashlib.sha256(json.dumps([config, str(url), options, certificate], sort_keys=True, default=str).encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        if _pid != os.getpid():
            for entry in _engines.values():
                entry['engine'].dispose(close=False)
            _engines.clear()
            _pid = os.getpid()
        # dispose 关闭池内空闲连接，不强行关闭已经借出的连接；旧句柄仍自行归还。
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
                          pool_size=int(options.get('poolSize', config.get('pool_size', 1))),
                          max_overflow=int(config.get('max_overflow', 1)),
                          pool_recycle=int(options.get('poolRecycle', config.get('pool_recycle', 600))),
                          pool_timeout=int(options.get('poolTimeout', config.get('pool_timeout', 10))))
        else:
            kwargs['poolclass'] = NullPool
        engine = create_engine(url, **kwargs)
        entry = {'signature': signature, 'engine': engine, 'used': now, 'enabled': bool(config.get('pool_enabled', True)),
                 'created': 0, 'checkouts': 0, 'invalidations': 0, 'timeouts': 0, 'active': 0, 'wait_max_ms': 0.0, 'wait_last_ms': 0.0,
                 'pool_size': int(kwargs.get('pool_size', 0)), 'max_overflow': int(kwargs.get('max_overflow', 0))}
        def count(name):
            def observed(*args):
                with _lock:
                    entry[name] += 1
            return observed
        event.listen(engine, 'connect', count('created'))
        def checkout(*args):
            with _lock:
                entry['checkouts'] += 1
                entry['active'] += 1
        def checkin(*args):
            with _lock:
                entry['active'] = max(0, entry['active'] - 1)
        event.listen(engine, 'checkout', checkout)
        event.listen(engine, 'checkin', checkin)
        event.listen(engine, 'invalidate', count('invalidations'))
        _engines[key] = entry
        while len(_engines) > MAX_PROFILES:
            _engines.popitem(last=False)[1]['engine'].dispose()
        return engine


def dispose(db_id=None):
    """淘汰指定或全部引擎缓存；普通 NewDB.close() 不应调用此操作。"""
    with _lock:
        for key in list(_engines):
            if db_id is None or key[1] == db_id:
                _engines.pop(key)['engine'].dispose()


def _after_fork():
    # 子进程重建锁并丢弃继承的池；close=False 避免干扰父进程的连接。
    global _lock, _pid
    _lock = threading.RLock()
    for entry in _engines.values():
        entry['engine'].dispose(close=False)
    _engines.clear()
    _pid = os.getpid()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)
atexit.register(dispose)


def record_wait(engine, milliseconds, timed_out=False):
    """Only bounded counters, never SQL/parameters/credentials."""
    with _lock:
        for entry in _engines.values():
            if entry['engine'] is engine:
                value = round(max(0.0, milliseconds), 2)
                entry['wait_last_ms'] = value
                entry['wait_max_ms'] = max(entry['wait_max_ms'], value)
                entry['timeouts'] += int(timed_out)
                break


def snapshot():
    """This process only; task subprocess pools are not a global shared pool."""
    with _lock:
        result = []
        for (dialect, identifier), entry in _engines.items():
            if str(identifier).startswith('@probe-'):
                continue
            pool = entry['engine'].pool
            value = {name: entry[name] for name in ('enabled', 'created', 'checkouts', 'invalidations', 'timeouts',
                                                     'wait_max_ms', 'wait_last_ms', 'pool_size', 'max_overflow')}
            value.update(id=identifier, dialect=dialect, pid=os.getpid(),
                         active=pool.checkedout() if entry['enabled'] else entry['active'],
                         idle=pool.checkedin() if entry['enabled'] else 0,
                         overflow=max(0, pool.overflow()) if entry['enabled'] else 0)
            result.append(value)
        return result
