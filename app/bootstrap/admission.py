"""Persistent single-host admission policy and conservative request receipts.

A pending receipt is never automatically replayed after a crash: callers must
inspect execution records. This provides duplicate prevention, not exactly-once
business side effects. All scheduling processes must share WFS_DATA_DIR.
"""
from collections import OrderedDict
from copy import deepcopy
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from app.bootstrap.timebase import business_now
lock = threading.RLock()
_policy_lock = threading.RLock()
_policy_cache = OrderedDict()
_policy_inflight = {}
_policy_generation = 0
_POLICY_TTL_SECONDS = 5
_POLICY_CACHE_LIMIT = 512


def _policy_marker():
    from app.bootstrap.global_vars import DATA_DIR
    return Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'policy-cache.version'


def _policy_version(path):
    try:
        # A small shared token gives all Web/Scheduler processes immediate
        # invalidation after a successful save, without a database round trip.
        from app.bootstrap.recovery_files import open_shared_read
        with open_shared_read(path) as source:
            return source.read(128)
    except FileNotFoundError:
        return ''
    except (OSError, UnicodeError):
        # If the shared invalidation channel cannot be read, bypass the cache.
        return None


def clear_policy_cache():
    global _policy_generation
    with _policy_lock:
        _policy_generation += 1
        _policy_cache.clear()


def invalidate_policy_cache():
    """Call after a committed settings change; share no settings or secrets."""
    clear_policy_cache()
    path = _policy_marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='ascii') as target:
            target.write(uuid.uuid4().hex)
        from app.bootstrap.recovery_files import replace_recovery
        replace_recovery(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _reset_policy_after_fork():
    global lock, _policy_lock, _policy_cache, _policy_inflight, _policy_generation
    lock = threading.RLock()
    _policy_lock = threading.RLock()
    _policy_cache = OrderedDict()
    _policy_inflight = {}
    _policy_generation = 0


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_policy_after_fork)

@contextmanager
def store():
    from app.bootstrap.auxiliary_store import gauss_store
    with gauss_store('admission') as db:
        yield db

def _read_policy(key):
    with store() as db:
        row = db.execute('SELECT payload FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def policy(key, default, *, fresh=False):
    # Authorization grants, notification delivery and other mutable receipts
    # always go straight to the database. Only operational settings are cached.
    cached_key = key == 'maintenance' or key.startswith(('dispatch:', 'task:', 'groups:', 'release:'))
    if not cached_key:
        value = _read_policy(key)
        return default if value is None else value
    path = _policy_marker()
    cache_key = (str(path), key)
    pending = None
    while True:
        version = _policy_version(path)
        with _policy_lock:
            entry = _policy_cache.get(cache_key)
            if not fresh and version is not None and entry and entry[0] == version and entry[1] > time.monotonic():
                _policy_cache.move_to_end(cache_key)
                return deepcopy(default if entry[2] is None else entry[2])
            generation = _policy_generation
            if fresh:
                break
            pending = _policy_inflight.get(cache_key)
            if pending is None:
                pending = _policy_inflight[cache_key] = (threading.Event(), threading.get_ident())
                break
            if pending[1] == threading.get_ident():
                raise RuntimeError('recursive operational policy read')
        # Only requests for this key wait. Other settings and invalidations
        # remain available while the database is slow.
        pending[0].wait()
    try:
        value = _read_policy(key)
        # A save during this read must not publish the old value as fresh.
        unchanged = version is not None and _policy_version(path) == version
        with _policy_lock:
            if unchanged and generation == _policy_generation:
                _policy_cache[cache_key] = (version, time.monotonic() + _POLICY_TTL_SECONDS, deepcopy(value))
                _policy_cache.move_to_end(cache_key)
                while len(_policy_cache) > _POLICY_CACHE_LIMIT:
                    _policy_cache.popitem(last=False)
        return deepcopy(default if value is None else value)
    finally:
        if not fresh:
            with _policy_lock:
                _policy_inflight.pop(cache_key, None)
                pending[0].set()


def maintenance(*, fresh=False):
    return policy('maintenance', dict(enabled=False, revision=0, reason='', actor='', updated_at=''), fresh=fresh)


def set_maintenance(enabled, revision, reason, actor):
    if not isinstance(enabled, bool) or not isinstance(reason, str) or len(reason) > 500:
        raise ValueError('维护状态或原因无效。')
    with lock:
        with store() as db:
            db.execute('BEGIN')
            row = db.execute("SELECT payload FROM settings WHERE key='maintenance'").fetchone()
            current = json.loads(row[0]) if row else {'revision': 0}
            if revision != current['revision']:
                raise RuntimeError('维护状态已变化，请刷新。')
            value = dict(enabled=enabled, revision=revision + 1, reason=reason.strip(), actor=actor, updated_at=str(business_now()))
            db.replace('settings', ('key', 'payload'), ('maintenance', json.dumps(value)))
        invalidate_policy_cache()
    return value

class CapacityUnavailable(ValueError):
    pass

class PlanCancelled(ValueError):
    pass

class MaintenanceClosed(RuntimeError):
    pass

def ensure_open(*, fresh=False):
    if maintenance(fresh=fresh)['enabled']:
        raise MaintenanceClosed('平台处于维护模式，暂不接受新的执行。')

def manual_request(actor, pid, key, submit):
    if not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{16,100}', key):
        raise ValueError('执行请求编号无效，请刷新后重试。')
    with lock:
        closed = maintenance()['enabled']
        with store() as db:
            db.execute('BEGIN')
            row = db.execute('SELECT pid,status,run_id,message FROM receipts WHERE actor=? AND key=?', (actor, key)).fetchone()
            if row:
                if row[0] != pid:
                    raise RuntimeError('请求编号已用于其他任务。')
                if row[1] == 'accepted':
                    return dict(run_id=row[2], replayed=True, message='已找到原执行记录')
                raise RuntimeError(row[3] or '原请求结果待核对，请查看执行记录；不会重复启动。')
            if closed:
                raise MaintenanceClosed('平台处于维护模式，暂不接受新的执行。')
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?)', (actor, key, pid, 'pending', '', '', str(business_now())))
        try:
            run_id = submit()
        except (CapacityUnavailable, MaintenanceClosed, PlanCancelled):
            with store() as db:
                db.execute('DELETE FROM receipts WHERE actor=? AND key=?', (actor, key))
            raise
        except Exception:
            with store() as db:
                db.execute("UPDATE receipts SET status='unknown',message=? WHERE actor=? AND key=?", ('执行未确认，请核对任务记录后发起新请求。', actor, key))
            raise
        with store() as db:
            db.execute("UPDATE receipts SET status='accepted',run_id=? WHERE actor=? AND key=?", (run_id, actor, key))
        return dict(run_id=run_id, replayed=False, message='任务已排队')

def grant(pid):
    return policy('connections:' + pid, dict(mode='restricted', connections=[], revision=0))

def save_grant(pid, form, actor):
    from app.bootstrap.connection_settings import profiles
    ids = form.get('connections', [])
    mode = form.get('mode')
    if mode not in ('restricted',) or not isinstance(ids, list) or len(ids) > 100 or any((not isinstance(i, str) for i in ids)):
        raise ValueError('连接授权格式无效。')
    available = profiles()
    if any((i == 'platform' or i not in available for i in ids)):
        raise ValueError('请选择已配置的业务连接。')
    with store() as db:
        db.execute('BEGIN')
        row = db.execute('SELECT payload FROM settings WHERE key=?', ('connections:' + pid,)).fetchone()
        old = json.loads(row[0]) if row else {'revision': 0}
        if form.get('revision') != old['revision']:
            raise RuntimeError('授权已变化，请刷新。')
        value = dict(mode=mode, connections=sorted(set(ids)), revision=old['revision'] + 1, actor=actor, updated_at=str(business_now()))
        db.replace('settings', ('key', 'payload'), ('connections:' + pid, json.dumps(value)))
    return value

def connection_environment(pid):
    access = grant(pid)
    from app.bootstrap.connection_settings import business_profile
    selected = {}
    for identifier in access['connections']:
        profile = business_profile(identifier)
        if not profile:
            raise ValueError('任务授权连接已不存在：' + identifier)
        selected[identifier] = profile
    payload = json.dumps(selected, ensure_ascii=True)
    if len(payload) > 60000:
        raise ValueError('任务授权连接信息过多，请减少授权范围。')
    return payload
