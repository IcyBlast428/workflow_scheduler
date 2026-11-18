"""GaussDB execution index with bounded JSON outage recovery.

JSON files are only temporary recovery spools while the platform database is unavailable;
normal records and indices live in GaussDB.
"""
import contextlib
import json
import os
from pathlib import Path
import re
import threading
import time
import logging
import uuid
from app.bootstrap.recovery_files import open_shared_read, replace_recovery
logger = logging.getLogger(__name__)
_run_id = re.compile(r'[a-f0-9]{32}')
_locks = tuple(threading.RLock() for _ in range(256))

def run_lock(run_id):
    if not _run_id.fullmatch(str(run_id)):
        raise ValueError('invalid run ID')
    return _locks[int(run_id[:2], 16)]

def _spool_ids(directory, limit):
    path = Path(directory)
    if not path.exists():
        return
    count = 0
    with os.scandir(path) as entries:
        for entry in entries:
            if limit is not None and count >= limit:
                break
            run_id, extension = os.path.splitext(entry.name)
            if extension != '.json' or not _run_id.fullmatch(run_id) or not entry.is_file(follow_symlinks=False):
                continue
            yield run_id
            count += 1

def _spooled(directory, limit=1000):
    path = Path(directory)
    return [
        record
        for run_id in _spool_ids(directory, limit)
        if (record := _load_spool(path / (run_id + '.json'), run_id)) is not None
    ]

def _spool(directory, record):
    if not _run_id.fullmatch(str(record.get('run_id', ''))):
        raise ValueError('invalid run ID')
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    temporary = path / (record['run_id'] + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as output:
            if os.name != 'nt':
                os.chmod(temporary, 384)
            json.dump(record, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        replace_recovery(temporary, path / (record['run_id'] + '.json'))
        if os.name != 'nt':
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)

def _records(directory, sql, params=(), *, spool_limit=1000):
    try:
        with connection(directory) as db:
            rows = [json.loads(row[0]) for row in db.execute(sql, params)]
    except Exception:
        logger.warning('GaussDB journal unavailable; retained recovery files remain pending', exc_info=True)
        rows = []
    # 未补写的恢复文件可能比数据库行更新；合并时必须让同 run_id 的文件覆盖旧行。
    by_id = {row['run_id']: row for row in rows}
    by_id.update({row['run_id']: row for row in _spooled(directory, spool_limit)})
    rows = list(by_id.values())
    return rows

@contextlib.contextmanager
def connection(directory):
    from app.bootstrap.auxiliary_store import gauss_store
    with gauss_store('journal') as db:
        yield db

def read_spooled(directory, run_id):
    if not _run_id.fullmatch(str(run_id)):
        raise ValueError('invalid run ID')
    pending_file = Path(directory) / (run_id + '.json')
    if pending_file.is_file() and (not pending_file.is_symlink()):
        return _load_spool(pending_file, run_id)
    return None

def _load_spool(path, run_id):
    try:
        with open_shared_read(path) as source:
            record = json.load(source)
        if isinstance(record, dict) and record.get('run_id') == run_id and all(
            isinstance(record.get(key), str) and record[key]
            for key in ('pid', 'status', 'created_at')
        ):
            return record
    except (ValueError, OSError):
        pass
    return None

def read(directory, run_id):
    record = read_spooled(directory, run_id)
    if record is not None:
        return record
    with connection(directory) as db:
        row = db.execute('SELECT payload FROM journal WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row[0]) if row else None

def read_many(directory, run_ids):
    """Look up a bounded set of run IDs after merging the recent lists."""
    records = {}
    missing = []
    for run_id in run_ids:
        record = read_spooled(directory, run_id)
        if record is None:
            missing.append(run_id)
        else:
            records[run_id] = record
    if missing:
        placeholders = ','.join('?' for _ in missing)
        try:
            with connection(directory) as db:
                for (payload,) in db.execute(f'SELECT payload FROM journal WHERE run_id IN ({placeholders})', tuple(missing)):
                    record = json.loads(payload)
                    records[record['run_id']] = record
        except Exception:
            logger.warning('GaussDB journal batch lookup unavailable', exc_info=True)
    return records

def write(directory, record, terminal):
    """先落可恢复文件，再写平台索引；索引写入失败时保留文件供后台重试。

    pending 同时涵盖执行状态未同步和终态历史未保存，
    不能仅因进程结束就把记录标为可清理。
    """
    with run_lock(record['run_id']):
        # Keep a durable local copy until the journal transaction commits.
        record['log_path'] = _log_path(record)
        _spool(directory, record)
        _write_index(directory, record, terminal)

def _log_path(record):
    run_id = record['run_id']
    return record.get('log_path') or f"logs/{record['created_at'][:10]}/{run_id[:2]}/{run_id}.log"

def _write_index(directory, record, terminal):
    pending = not record.get('db_synced') or (record['status'] in terminal and (not record.get('history_saved')))
    run_id = record['run_id']
    path = _log_path(record)
    record['log_path'] = path
    try:
        with connection(directory) as db:
            db.replace('journal',('run_id','pid','status','created_at','pending','retry_at','payload','log_path'),(run_id,record['pid'],record['status'],record['created_at'],int(pending),0,json.dumps(record,ensure_ascii=False),None if record.get('log_cleaned_at') else path))
    except Exception:
        logger.warning('GaussDB journal write deferred; recovery file retained', exc_info=True)
        return False
    (Path(directory) / (run_id + '.json')).unlink(missing_ok=True)
    return True

def recent(directory, pid=None, limit=50):
    rows = _records(directory, 'SELECT payload FROM journal ' + ('WHERE pid=? ' if pid else '') + 'ORDER BY created_at DESC LIMIT ?', (pid, limit) if pid else (limit,))
    return sorted((row for row in rows if not pid or row['pid'] == pid), key=lambda row: row['created_at'], reverse=True)[:limit]

def pending(directory, limit):
    return _records(directory, 'SELECT payload FROM journal WHERE pending=1 AND retry_at<=? ORDER BY retry_at,created_at LIMIT ?', (time.time(), limit))[:limit]

def defer(directory, run_id):
    with connection(directory) as db:
        db.execute('UPDATE journal SET retry_at=? WHERE run_id=?', (time.time() + 60, run_id))

def active(directory, *, spool_limit=1000):
    rows = _records(directory, "SELECT payload FROM journal WHERE status IN ('running','queued')", spool_limit=spool_limit)
    return [row for row in rows if row['status'] in ('running', 'queued')]

def expire(directory, cutoff, limit):
    # 仅清理已完成同步的旧终态记录；正在运行或仍待补写的内容不受年龄阈值淘汰。
    with connection(directory) as db:
        rows = db.execute("SELECT run_id,log_path FROM journal WHERE created_at<? AND pending=0 AND status NOT IN ('running','queued') ORDER BY created_at LIMIT ?", (cutoff, limit)).fetchall()
        for run_id, relative in rows:
            if not relative:
                db.execute('DELETE FROM journal WHERE run_id=?', (run_id,))
                continue
            path = (Path(directory) / relative).resolve()
            path.relative_to(Path(directory).resolve())
            path.unlink(missing_ok=True)
            db.execute('DELETE FROM journal WHERE run_id=?', (run_id,))
    return len(rows)

def recover_pending(directory, terminal, limit):
    recovered = []
    for run_id in _spool_ids(directory, limit):
        with run_lock(run_id):
            # A lifecycle update can replace or remove the file after enumeration.
            record = read_spooled(directory, run_id)
            if record is not None and _write_index(directory, record, terminal):
                recovered.append(record)
    return recovered

def health(directory):
    try:
        with connection(directory) as db:
            due = db.execute('SELECT COUNT(*),MIN(created_at) FROM journal WHERE pending=1').fetchone()
    except Exception:
        due = (0, None)
    files = _spooled(directory)
    oldest = min([value for value in [due[1], *[item['created_at'] for item in files]] if value], default='')
    recovery_bytes = 0
    for path in Path(directory).glob('*.json'):
        try:
            recovery_bytes += path.stat().st_size
        except FileNotFoundError:
            # A successful database write can remove a spool while health is sampled.
            continue
    return {'pending_writes': due[0] + len(files), 'oldest_pending': oldest, 'journal_bytes': recovery_bytes, 'pending_recovery_files': len(files), 'oldest_recovery_file': oldest}
