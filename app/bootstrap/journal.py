"""GaussDB execution index with bounded JSON outage recovery.

JSON files are only temporary recovery spools while the platform database is unavailable;
normal records and indices live in GaussDB.
"""
import contextlib
import json
import os
from pathlib import Path
import time
import logging
import uuid
from app.bootstrap.recovery_files import open_shared_read, replace_recovery
logger = logging.getLogger(__name__)

def _spooled(directory, limit=1000):
    records = []
    path = Path(directory)
    if not path.exists():
        return records
    with os.scandir(path) as entries:
        for index, entry in enumerate(entries):
            if index >= limit:
                break
            if not entry.name.endswith('.json') or not entry.is_file(follow_symlinks=False):
                continue
            try:
                with open_shared_read(entry.path) as source:
                    record = json.load(source)
                import re
                if re.fullmatch('[a-f0-9]{32}', record.get('run_id', '')) and entry.name == record['run_id'] + '.json':
                    records.append(record)
            except (ValueError, OSError):
                continue
    return records

def _spool(directory, record):
    import re
    if not re.fullmatch('[a-f0-9]{32}', str(record.get('run_id', ''))):
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

def _records(directory, sql, params=()):
    try:
        with connection(directory) as db:
            rows = [json.loads(row[0]) for row in db.execute(sql, params)]
    except Exception:
        logger.warning('GaussDB journal unavailable; retained recovery files remain pending', exc_info=True)
        rows = []
    by_id = {row['run_id']: row for row in rows}
    by_id.update({row['run_id']: row for row in _spooled(directory)})
    rows = list(by_id.values())
    return rows

@contextlib.contextmanager
def connection(directory):
    from app.bootstrap.auxiliary_store import gauss_store
    with gauss_store('journal') as db:
        yield db

def read(directory, run_id):
    import re
    if not re.fullmatch('[a-f0-9]{32}', str(run_id)):
        raise ValueError('invalid run ID')
    pending_file = Path(directory) / (run_id + '.json')
    if pending_file.is_file() and (not pending_file.is_symlink()):
        try:
            with open_shared_read(pending_file) as source:
                return json.load(source)
        except FileNotFoundError:
            pass
    with connection(directory) as db:
        row = db.execute('SELECT payload FROM journal WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row[0]) if row else None

def write(directory, record, terminal):
    pending = not record.get('db_synced') or (record['status'] in terminal and (not record.get('history_saved')))
    run_id = record['run_id']
    path = record.get('log_path') or f"logs/{record['created_at'][:10]}/{run_id[:2]}/{run_id}.log"
    record['log_path'] = path
    _spool(directory, record)
    try:
        with connection(directory) as db:
            db.replace('journal',('run_id','pid','status','created_at','pending','retry_at','payload','log_path'),(run_id,record['pid'],record['status'],record['created_at'],int(pending),0,json.dumps(record,ensure_ascii=False),'' if record.get('log_cleaned_at') else path))
    except Exception:
        logger.warning('GaussDB journal write deferred; recovery file retained', exc_info=True)
        return
    (Path(directory) / (run_id + '.json')).unlink(missing_ok=True)

def recent(directory, pid=None, limit=50):
    rows = _records(directory, 'SELECT payload FROM journal ' + ('WHERE pid=? ' if pid else '') + 'ORDER BY created_at DESC LIMIT ?', (pid, limit) if pid else (limit,))
    return sorted((row for row in rows if not pid or row['pid'] == pid), key=lambda row: row['created_at'], reverse=True)[:limit]

def pending(directory, limit):
    return _records(directory, 'SELECT payload FROM journal WHERE pending=1 AND retry_at<=? ORDER BY retry_at,created_at LIMIT ?', (time.time(), limit))[:limit]

def defer(directory, run_id):
    with connection(directory) as db:
        db.execute('UPDATE journal SET retry_at=? WHERE run_id=?', (time.time() + 60, run_id))

def active(directory):
    return [row for row in _records(directory, "SELECT payload FROM journal WHERE status IN ('running','queued')") if row['status'] in ('running', 'queued')]

def expire(directory, cutoff, limit):
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
    for record in _spooled(directory, limit):
        write(directory, record, terminal)
        if not (Path(directory) / (record['run_id'] + '.json')).exists():
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
