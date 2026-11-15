"""Bounded history storage policy; archival keeps every record in the same database."""
from contextlib import contextmanager
import datetime as dt
import json
import logging
import threading
import time

from app.bootstrap.timebase import business_now
from app.bootstrap.snapshot_cache import cached

logger = logging.getLogger(__name__)
DEFAULT = dict(revision=0, archive_enabled=False, online_days=90,
               archive_batch_size=200, archive_batches_per_cycle=10,
               archive_budget_seconds=5, success_excerpt_kib=2, failure_excerpt_kib=16)
_KEY = 'history-storage:policy'
_STATUS = 'history-storage:status'
_cycle_lock = threading.Lock()
_policy_generation = 0
_clock = time.monotonic


@contextmanager
def _store():
    from app.bootstrap.auxiliary_store import gauss_store
    with gauss_store('admission') as db:
        yield db


def _read(key, default):
    with _store() as db:
        row = db.execute('SELECT payload FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else dict(default)


def invalidate_policy():
    global _policy_generation
    _policy_generation += 1


def load():
    return cached(('history-storage-policy', _policy_generation), 5,
                  lambda: {**DEFAULT, **_read(_KEY, DEFAULT)}, mutable=False)


def save(form, actor):
    if not isinstance(form, dict) or type(form.get('revision')) is not int:
        raise ValueError('存储策略格式无效，请刷新后重试。')
    if type(form.get('archive_enabled')) is not bool:
        raise ValueError('请选择是否自动归档历史记录。')
    value = dict(archive_enabled=form['archive_enabled'])
    for key, low, high in [('online_days', 90, 3650), ('archive_batch_size', 1, 1000),
                           ('archive_batches_per_cycle', 1, 50), ('archive_budget_seconds', 1, 30),
                           ('success_excerpt_kib', 0, 16), ('failure_excerpt_kib', 1, 63)]:
        number = form.get(key, DEFAULT[key])
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f'{key} 应为 {low} 至 {high} 之间的整数。')
        value[key] = number
    with _store() as db:
        db.execute('BEGIN')
        row = db.execute('SELECT payload FROM settings WHERE key=?', (_KEY,)).fetchone()
        previous = json.loads(row[0]) if row else DEFAULT
        if previous['revision'] != form['revision']:
            raise RuntimeError('存储策略已被修改，请刷新后重试。')
        value.update(revision=previous['revision'] + 1, actor=actor, updated_at=str(business_now()))
        db.replace('settings', ('key', 'payload'), (_KEY, json.dumps(value, ensure_ascii=False)))
    invalidate_policy()
    return value


def snapshot():
    return {'policy': load(), 'status': _read(_STATUS, dict(last_run='', moved=0, batches=0,
            duration_ms=0, has_more=False, budget_exhausted=False, error='')),
            'archive_location': 'same_database', 'interval_seconds': 60, 'budget_scope': 'between_batches',
            'description': '归档将历史移入同一数据库的归档表，仍可查询；不会删除记录或释放数据库总空间。'}


def history_excerpt(record, output, policy=None):
    """Keep bounded UTF-8 text in SQL; the retained file and alert payload are unchanged."""
    policy = policy or load()
    kib = policy['success_excerpt_kib'] if record.get('state') == 0 else policy['failure_excerpt_kib']
    raw = output.encode('utf-8')
    budget = kib * 1024
    if len(raw) <= budget:
        return output
    # Errors normally appear at the end; successful logs retain the opening context.
    if record.get('state') == 0:
        excerpt = raw[:budget].decode('utf-8', errors='ignore')
    else:
        reason = str(record.get('reason') or '').encode('utf-8')[:min(1024, budget // 4)].decode('utf-8', errors='ignore')
        tail_budget = max(0, budget - len(reason.encode('utf-8')) - (1 if reason else 0))
        tail = raw[-tail_budget:].decode('utf-8', errors='ignore') if tail_budget else ''
        excerpt = (reason + '\n' if reason else '') + tail
    return excerpt + '\n[数据库仅保留日志摘要；完整保留日志请进入执行详情查看或下载。 / truncated summary]'


def run_cycle():
    """Called by the single scheduler once a minute; one transaction per bounded batch."""
    policy = load()
    if not policy['archive_enabled'] or not _cycle_lock.acquire(blocking=False):
        return None
    from app.bootstrap.history import archive_batch, archive_pending
    began = _clock()
    cutoff = business_now() - dt.timedelta(days=policy['online_days'])
    state = dict(last_run=str(business_now()), moved=0, batches=0, duration_ms=0,
                 has_more=False, budget_exhausted=False, error='')
    try:
        for _ in range(policy['archive_batches_per_cycle']):
            if _clock() - began >= policy['archive_budget_seconds']:
                state['budget_exhausted'] = True
                break
            moved = archive_batch(cutoff, policy['archive_batch_size'])
            state['moved'] += moved
            state['batches'] += 1
            if moved < policy['archive_batch_size']:
                break
        state['has_more'] = archive_pending(cutoff)
        if state['has_more'] and _clock() - began >= policy['archive_budget_seconds']:
            state['budget_exhausted'] = True
    except Exception:
        state['error'] = '本轮归档未完成，未提交的批次已保留原记录；请检查服务日志。'
        state['has_more'] = True
        logger.exception('bounded history archival failed')
    finally:
        state['duration_ms'] = round((_clock() - began) * 1000, 2)
        try:
            with _store() as db:
                db.replace('settings', ('key', 'payload'), (_STATUS, json.dumps(state, ensure_ascii=False)))
        finally:
            _cycle_lock.release()
    return state
