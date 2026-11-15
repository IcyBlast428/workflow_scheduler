"""Bounded process-local DBAPI pools with secret-free shared diagnostic snapshots."""
from collections import OrderedDict
import atexit
import hashlib
import json
import os
import math
import re
from pathlib import Path
import threading
import time
import uuid
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import TimeoutError as PoolTimeout

_entries = OrderedDict()
_guard = threading.RLock()
_flush_guard = threading.Lock()
_FILE = re.compile(r'^[0-9]+-[a-f0-9]{12}\.json$')
_last_flush = 0.0
_identity = uuid.uuid4().hex[:12]


def _after_fork():
    global _entries, _guard, _flush_guard, _last_flush, _identity
    # Never close inherited connections: their sockets belong to the parent.
    _entries = OrderedDict()
    _guard = threading.RLock()
    _flush_guard = threading.Lock()
    _last_flush = 0.0
    _identity = uuid.uuid4().hex[:12]


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def _directory():
    from app.bootstrap.global_vars import DATA_DIR
    return Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'platform-pools'


def _payload():
    with _guard:
        pools = []
        for key, entry in _entries.items():
            pool = entry['pool']
            pools.append(dict(id=key[:12], size=pool.size(), idle=pool.checkedin(),
                              in_use=pool.checkedout(), waiting=entry['waiting'],
                              limit=entry['limit'], acquired=entry['acquired'],
                              opened=entry['opened'], timeouts=entry['timeouts'],
                              reconnects=entry['reconnects']))
    return dict(pid=os.getpid(), at=time.time(), role='scheduler' if os.environ.get('WFS_ENABLE_SCHEDULER') == 'true' else 'web', pools=pools)


def _flush(force=False):
    global _last_flush
    if not _flush_guard.acquire(blocking=False):
        return
    temporary = None
    try:
        now = time.monotonic()
        if not force and now - _last_flush < 1:
            return
        directory = _directory(); directory.mkdir(parents=True, exist_ok=True)
        target = directory / f'{os.getpid()}-{_identity}.json'
        temporary = target.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            if os.name != 'nt': os.chmod(temporary, 0o600)
            json.dump(_payload(), stream)
        from app.bootstrap.recovery_files import replace_recovery
        replace_recovery(temporary, target)
        _last_flush = now
        # Old worker snapshots must not crowd live workers out of diagnostics.
        cutoff = time.time() - 120
        for item in directory.iterdir():
            if _FILE.fullmatch(item.name) and not item.is_symlink() and item.stat().st_mtime < cutoff:
                try: item.unlink()
                except OSError: pass
    except (OSError, ValueError):
        pass
    finally:
        if temporary is not None:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
        _flush_guard.release()


def _safe_snapshot(value, now):
    if not isinstance(value, dict) or type(value.get('pid')) is not int or value['pid'] <= 0:
        return None
    at = value.get('at')
    if type(at) not in (int, float) or not math.isfinite(at) or not 0 <= now - at < 60:
        return None
    if value.get('role') not in ('web', 'scheduler') or not isinstance(value.get('pools'), list):
        return None
    fields = ('size', 'idle', 'in_use', 'waiting', 'limit', 'acquired', 'opened', 'timeouts', 'reconnects')
    pools = []
    for item in value['pools'][:32]:
        if not isinstance(item, dict) or not re.fullmatch('[a-f0-9]{12}', str(item.get('id', ''))):
            return None
        if any(type(item.get(key)) is not int or item[key] < 0 for key in fields):
            return None
        pools.append({key: item[key] for key in ('id', *fields)})
    return dict(pid=value['pid'], at=at, role=value['role'], pools=pools)


def diagnostics():
    current = _payload()
    result = [current]
    try:
        candidates = sorted((p for p in _directory().iterdir() if _FILE.fullmatch(p.name) and not p.is_symlink()),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        for file in candidates[:128]:
            try:
                if file.stat().st_size > 65536: continue
                value = _safe_snapshot(json.loads(file.read_text(encoding='utf-8')), time.time())
                if value is None or value['pid'] == current['pid']: continue
                result.append(value)
            except (OSError, ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    from app.bootstrap.runtime_metrics import snapshot
    timings = {k: v for k, v in snapshot().items() if k in ('database:connect', 'database:pool_wait', 'database:query', 'database:write')}
    return {'processes': result, 'metrics': timings, 'stale_after_seconds': 60}


class Lease:
    def __init__(self, connection):
        self.connection, self.raw = connection, connection.dbapi_connection
    def close(self, broken=False):
        if self.connection is not None:
            connection, self.connection = self.connection, None
            try:
                if broken: connection.invalidate()
            finally:
                connection.close()
                _flush()


def acquire(identity, creator, settings):
    role = 'scheduler' if os.environ.get('WFS_ENABLE_SCHEDULER') == 'true' else 'web'
    size, overflow = settings[role + '_pool_size'], settings[role + '_max_overflow']
    key = hashlib.sha256(json.dumps([identity, size, overflow, settings['pool_timeout'], settings['pool_recycle']], sort_keys=True, default=str).encode()).hexdigest()
    with _guard:
        entry = _entries.get(key)
        if entry is None:
            entry = dict(waiting=0, acquired=0, opened=0, timeouts=0, reconnects=0, limit=size+overflow, used=time.monotonic())
            def connect():
                from app.bootstrap.runtime_metrics import measure
                with measure('database:connect'):
                    raw = creator()
                with _guard: entry['opened'] += 1
                return raw
            entry['pool'] = QueuePool(connect, pool_size=size, max_overflow=overflow,
                                      timeout=settings['pool_timeout'], recycle=settings['pool_recycle'],
                                      reset_on_return='rollback')
            _entries[key] = entry
        entry['used'] = time.monotonic()
        _entries.move_to_end(key)
        # Retire idle identities after rotation without interrupting active transactions.
        for candidate, old in list(_entries.items()):
            if candidate != key and old['pool'].checkedout() == 0 and old['waiting'] == 0 and (len(_entries) > 16 or time.monotonic()-old['used'] > 300):
                _entries.pop(candidate)['pool'].dispose()
        entry['waiting'] += 1
    try:
        from app.bootstrap.runtime_metrics import measure
        with measure('database:pool_wait'):
            lease = None
            for attempt in range(2):
                raw_lease = entry['pool'].connect()
                lease = Lease(raw_lease)
                try:
                    # Validate only the checkout; never retry a user's SQL/transaction.
                    if not lease.raw.autocommit:
                        lease.raw.rollback()
                        lease.raw.autocommit = True
                    cursor = lease.raw.cursor()
                    try: cursor.execute('SELECT 1')
                    finally: cursor.close()
                    break
                except Exception:
                    lease.close(broken=True)
                    with _guard: entry['reconnects'] += 1
                    if attempt: raise
            with _guard: entry['acquired'] += 1
            return lease
    except PoolTimeout:
        with _guard: entry['timeouts'] += 1
        raise RuntimeError('平台数据库连接池已满，请检查并发、慢查询与锁等待。') from None
    finally:
        with _guard: entry['waiting'] -= 1
        _flush()


def dispose():
    with _guard:
        for entry in _entries.values(): entry['pool'].dispose()
        _entries.clear()
    _flush(force=True)


atexit.register(dispose)
