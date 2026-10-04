"""Durable execution journal, audit and housekeeping for the single scheduler."""
from app.bootstrap.timebase import business_now

import datetime as dt
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import uuid
import signal
import shutil
from app.bootstrap import journal
from app.bootstrap.execution_state import is_failure, SKIPPED

from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import DATA_DIR

logger = logging.getLogger(__name__)
TERMINAL = {'success', 'failed', 'timed_out', 'cancelled', 'interrupted', 'skipped', 'missed'}
_locks = tuple(threading.RLock() for _ in range(256))
_directory = Path(DATA_DIR) / 'executions'
_started = False
_start_lock = threading.Lock()
_service_state = {'ready': False, 'error': '', 'heartbeat': ''}


def now():
    return business_now().isoformat(' ', timespec='microseconds')


def run_path(run_id, suffix='json'):
    if not re.fullmatch(r'[a-f0-9]{32}', str(run_id)):
        raise ValueError('invalid execution identifier')
    if suffix == 'json':
        return _directory / f'{run_id}.json'  # Legacy lookup only; new records use WAL.
    record = journal.read(_directory, run_id)
    relative = record.get('log_path') if record else f'{run_id}.{suffix}'
    path = (_directory / relative).resolve()
    path.relative_to(_directory.resolve())
    if suffix == 'log':
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_run(run_id):
    run_path(run_id)  # Validate before touching the index.
    indexed = journal.read(_directory, run_id)
    if indexed is not None:
        return indexed
    path = run_path(run_id)
    if path.is_file():
        record = json.loads(path.read_text(encoding='utf-8'))
        record.setdefault('log_path',run_id+'.log')
        return record
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT payload FROM wfs_executions WHERE run_id=?', params=(run_id,))
    if not rows:
        raise ValueError('execution not found')
    return json.loads(rows[0][0])


def _write_file(record):
    journal.write(_directory, record, TERMINAL)


def _persist_record(record):
    payload = json.dumps(record, ensure_ascii=False)
    with GaussDB() as db:
        if db.execute_query_sql('SELECT 1 FROM wfs_executions WHERE run_id=?', params=(record['run_id'],)):
            db.execute_sql('UPDATE wfs_executions SET status=?, payload=? WHERE run_id=?', params=(record['status'], payload, record['run_id']))
        else:
            db.execute_sql('INSERT INTO wfs_executions(run_id,pid,status,created_at,payload) VALUES(?,?,?,?,?)',
                           params=(record['run_id'], record['pid'], record['status'], record['created_at'], payload))


def update_run(run_id, persist=True, **changes):
    with _locks[int(run_id[:2], 16)]:
        record = read_run(run_id)
        record.update(changes, heartbeat=now())
        if persist:
            record['db_synced'] = False
        _write_file(record)
        if persist:
            try:
                _persist_record(record)
                record['db_synced'] = True
                _write_file(record)
            except Exception:
                logger.exception('execution %s retained in local journal; database sync deferred', run_id)
        return record


def create_run(pid, name='', source='scheduled', actor='scheduler', **fields):
    _directory.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(_directory).free < int(os.environ.get('WFS_MIN_FREE_MB','100')) * 1024 * 1024:
        raise RuntimeError('日志目录剩余空间不足，暂不启动新执行。')
    run_id = uuid.uuid4().hex
    record = dict(run_id=run_id, pid=pid, task_name=name or pid, source=source, actor=actor,
                  status='queued', created_at=now(), start_time='', end_time='', heartbeat=now(),
                  process_id=None, state=None, reason='', log_truncated=False, history_saved=False,
                  scheduler_pid=os.getpid(), **fields)
    _write_file(record)
    try:
        _persist_record(record)
        record['db_synced'] = True
        _write_file(record)
    except Exception:
        logger.exception('queued execution retained in journal: %s', run_id)
    return run_id


def list_runs(pid=None, limit=50):
    limit = min(100, max(1, int(limit)))
    rows = []
    try:
        with GaussDB() as db:
            sql = 'SELECT payload FROM wfs_executions'
            params = []
            if pid:
                sql += ' WHERE pid=?'
                params.append(pid)
            rows = db.execute_query_sql(sql + ' ORDER BY created_at DESC LIMIT ?', params=tuple(params + [limit]))
    except Exception:
        logger.exception('execution listing uses local journal while database is unavailable')
    records = {item['run_id']: item for row in rows for item in [json.loads(row[0])]}
    for record in journal.recent(_directory, pid, limit):
        records[record['run_id']] = record
    for run_id in list(records):
        indexed = journal.read(_directory, run_id)
        if indexed:
            records[run_id] = indexed
    return sorted(records.values(), key=lambda item: item['created_at'], reverse=True)[:limit]


def read_log(run_id, offset=0):
    record = read_run(run_id)
    path = run_path(run_id, 'log')
    offset = max(0, int(offset))
    data = b''
    if path.is_file():
        with path.open('rb') as source:
            source.seek(offset)
            data = source.read(64 * 1024)
            # Do not split a valid UTF-8 character between polling responses.
            import codecs
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            content = decoder.decode(data, final=record['status'] in TERMINAL and source.tell() >= path.stat().st_size)
            pending = decoder.getstate()[0]
            if pending:
                data = data[:-len(pending)]
    if not path.is_file():
        content = ''
    return dict(record=record, content=content, next_offset=offset + len(data),
                has_more=path.is_file() and path.stat().st_size > offset + len(data))


def save_history(record):
    """Idempotent completion: inserts and statistics update share a transaction."""
    if record.get('history_saved') or record['status'] not in TERMINAL:
        return
    try:
        path = run_path(record['run_id'], 'log')
        if path.exists():
            with path.open('rb') as log:
                output = log.read(63 * 1024).decode('utf-8', errors='replace')
        else:
            output = ''
        output = record.get('reason', '') + '\n' + output
        if record.get('log_truncated') or path.exists() and path.stat().st_size >= 63 * 1024:
            output += '\nTask output was truncated at 63 KiB; retained log can be downloaded.'
        with GaussDB() as db:
            db.begin_transaction()
            try:
                if not db.execute_query_sql('SELECT 1 FROM wfs_run_history WHERE id=?', params=(record['run_id'],)):
                    db.execute_sql('INSERT INTO wfs_run_history(id,pid,taskname,dirname,group_name,folder_name,state,tasklog,start_time,end_time) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   params=(record['run_id'], record['pid'], record['task_name'], record.get('dir_name',''), record.get('group_name',''), record.get('folder_name',''), record.get('state',1), output, record.get('start_time') or record['created_at'], record['end_time']))
                    if record.get('state') == 0:
                        db.execute_sql('UPDATE wfs_job_stats SET last_status=0, last_sms_alarm=NULL, failed_times=0 WHERE pid=?', params=(record['pid'],))
                    elif not is_failure(record.get('state')):
                        db.execute_sql('UPDATE wfs_job_stats SET last_status=? WHERE pid=?', params=(record.get('state'), record['pid']))
                    else:
                        db.execute_sql('UPDATE wfs_job_stats SET last_status=?, failed_times=failed_times+1 WHERE pid=?', params=(record.get('state',1), record['pid']))
                    from app.bootstrap.run_summary import summarize_row
                    # Old GaussDB schemas use timestamp(0); read the stored key
                    # rather than comparing an unrounded microsecond timestamp.
                    stored_end = db.execute_query_sql('SELECT end_time FROM wfs_run_history WHERE id=?',params=(record['run_id'],))[0][0]
                    summarize_row(db, record['run_id'], record['pid'], record.get('state'), stored_end)
                    from app.bootstrap.notifications import enqueue_result
                    enqueue_result(db, record, output)
                db.set_commit()
            except Exception:
                db.set_rollback()
                raise
        update_run(record['run_id'], history_saved=True)
        from app.bootstrap.snapshot_cache import invalidate
        invalidate()
    except Exception:
        logger.exception('completion retained for retry: %s', record['run_id'])


def audit(actor, action, target, outcome='success', details=''):
    entry = dict(id=uuid.uuid4().hex, actor=actor or 'unknown', action=action, target=target or '',
                 outcome=outcome, details=str(details)[:4000], created_at=now())
    try:
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_audit(id,actor,action,target,outcome,details,created_at) VALUES(?,?,?,?,?,?,?)', params=tuple(entry.values()))
    except Exception:
        logger.exception('audit write deferred')
        directory = Path(DATA_DIR) / 'audit-spool'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (entry['id'] + '.json')).write_text(json.dumps(entry), encoding='utf-8')


def mark_ready(error=''):
    _service_state.update(ready=not bool(error), error=str(error), heartbeat=now())


def service_state():
    return dict(_service_state)


def _recover_record(record):
    if record['status'] in TERMINAL:
        return
    process_id = record.get('process_id')
    if process_id and os.name != 'nt':
        proc = Path(f'/proc/{process_id}')
        try:
            if proc.exists() and record.get('process_identity') == proc.joinpath('stat').read_text().split()[21] and b'worker.py' in proc.joinpath('cmdline').read_bytes():
                os.killpg(process_id, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            logger.warning('orphan process cleanup unavailable: %s', process_id)
    result = update_run(record['run_id'], status='interrupted', state=-1, end_time=now(), reason='调度服务重启，执行未正常完成；请确认业务数据后再补跑。')
    save_history(result)


def maintenance(recover=False):
    batch = max(1, min(5000, int(os.environ.get('WFS_MAINTENANCE_BATCH', '500'))))
    deadline = time.monotonic() + max(1, int(os.environ.get('WFS_MAINTENANCE_SECONDS', '10')))
    if recover:
        # Known active IDs protect orphan recovery during a large legacy import.
        with GaussDB() as db:
            rows = db.execute_query_sql("SELECT run_id FROM wfs_executions WHERE status IN ('running','queued')")
        for (run_id,) in rows:
            _recover_record(read_run(run_id))
        for record in journal.active(_directory):
            _recover_record(record)
    for record in journal.import_legacy(_directory, TERMINAL, batch):
        if record['status'] not in TERMINAL:
            _recover_record(record)
    processed = 0
    for record in journal.pending(_directory, batch):
        if time.monotonic() >= deadline:
            break
        try:
            with _locks[int(record['run_id'][:2], 16)]:
                record = read_run(record['run_id'])
                if not record.get('db_synced'):
                    _persist_record(record)
                    record['db_synced'] = True
                    _write_file(record)
                save_history(record)
                if not read_run(record['run_id']).get('history_saved') and record['status'] in TERMINAL:
                    journal.defer(_directory, record['run_id'])
            processed += 1
        except Exception:
            journal.defer(_directory, record['run_id'])
            logger.exception('journal maintenance failed: %s', record['run_id'])
    days = max(60, int(os.environ.get('WFS_LOG_RETENTION_DAYS', '90')))
    expired = journal.expire(_directory, (business_now()-dt.timedelta(days=days)).isoformat(' '), batch)
    _service_state['maintenance'] = {'processed':processed, 'expired':expired, 'completed_at':now()}
    from app.bootstrap.run_summary import backfill
    backfill(batch)
    directory = Path(DATA_DIR) / 'audit-spool'
    import itertools
    for path in itertools.islice(directory.glob('*.json'), batch):
        try:
            entry = json.loads(path.read_text())
            with GaussDB() as db:
                if not db.execute_query_sql('SELECT 1 FROM wfs_audit WHERE id=?', params=(entry['id'],)):
                    db.execute_sql('INSERT INTO wfs_audit(id,actor,action,target,outcome,details,created_at) VALUES(?,?,?,?,?,?,?)', params=tuple(entry.values()))
            path.unlink()
        except Exception:
            logger.exception('audit recovery failed')
    cutoff = business_now() - dt.timedelta(days=int(os.environ.get('WFS_HISTORY_RETENTION_DAYS', '90')))
    with GaussDB() as db:
        # History must be archived and verified before removal. Never purge it here.
        for table, column in (('wfs_executions','created_at'), ('wfs_audit','created_at')):
            key = 'run_id' if table == 'wfs_executions' else 'id'
            db.execute_sql(f'DELETE FROM {table} WHERE {key} IN (SELECT {key} FROM {table} WHERE {column} < ? ORDER BY {column} LIMIT ?)', params=(cutoff,batch))
        db.execute_sql('DELETE FROM wfs_login_limits WHERE window_start < ?', params=(business_now() - dt.timedelta(minutes=15),))
        versions_to_keep = max(20,int(os.environ.get('WFS_CONFIG_VERSIONS_KEEP','100')))
        for pid, version in db.execute_query_sql('SELECT pid,version FROM wfs_task_config'):
            db.execute_sql('DELETE FROM wfs_config_versions WHERE pid=? AND version<=?', params=(pid,version - versions_to_keep))
        pending = db.execute_query_sql('SELECT c.pid FROM wfs_task_config c LEFT JOIN wfs_config_application a ON c.pid=a.pid WHERE a.pid IS NULL OR c.version<>a.version OR a.status<>?', params=('applied',))
    if _service_state['ready']:
        from app.bootstrap.core import aps_start
        for (pid,) in pending:
            try:
                aps_start(task_pid=pid, action='refresh')
            except Exception:
                logger.exception('configuration reconciliation failed: %s', pid)


def start_operations():
    global _started
    with _start_lock:
        if _started:
            return
        _directory.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            import fcntl
            global _lease
            _lease = (_directory.parent / '.scheduler.lock').open('a')
            fcntl.flock(_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            maintenance(recover=True)
        except Exception:
            if os.name != 'nt':
                _lease.close()
            raise
        _started = True
    def loop():
        while True:
            _service_state['heartbeat'] = now()
            try:
                maintenance()
            except Exception:
                logger.exception('operations maintenance unavailable')
            time.sleep(60)
    threading.Thread(target=loop, name='wfs-journal', daemon=True).start()
    from app.bootstrap.notifications import start_notifications
    start_notifications()
