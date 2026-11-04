"""Indexed local recovery journal, independent of platform DB availability.

WAL + FULL synchronization protects committed records. A fixed number of locks
is used by operations; completed records never allocate permanent Python locks.
Old JSON journals are imported in bounded batches, without blocking startup.
"""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import logging
import uuid
from app.bootstrap.auxiliary_store import enabled

logger = logging.getLogger(__name__)


def _spooled(directory, limit=1000):
    records=[]
    path=Path(directory)
    if not path.exists(): return records
    with os.scandir(path) as entries:
        for index, entry in enumerate(entries):
            if index >= limit: break
            if not entry.name.endswith('.json') or not entry.is_file(follow_symlinks=False): continue
            try:
                record=json.loads(Path(entry.path).read_text(encoding='utf-8'))
                import re
                if re.fullmatch('[a-f0-9]{32}',record.get('run_id','')) and entry.name==record['run_id']+'.json':
                    records.append(record)
            except (ValueError,OSError): continue
    return records


def _spool(directory, record):
    import re
    if not re.fullmatch('[a-f0-9]{32}',str(record.get('run_id',''))):
        raise ValueError('invalid run ID')
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    temporary=path/(record['run_id']+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as output:
            if os.name!='nt': os.chmod(temporary,0o600)
            json.dump(record,output,ensure_ascii=False)
            output.flush();os.fsync(output.fileno())
        os.replace(temporary,path/(record['run_id']+'.json'))
        if os.name!='nt':
            descriptor=os.open(path,os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
    finally: temporary.unlink(missing_ok=True)


def _records(directory, sql, params=()):
    try:
        with connection(directory) as db:
            rows=[json.loads(row[0]) for row in db.execute(sql,params)]
    except Exception:
        if not enabled(): raise
        logger.warning('GaussDB journal unavailable; retained recovery files remain pending',exc_info=True)
        rows=[]
    if enabled():
        by_id={row['run_id']:row for row in rows}
        by_id.update({row['run_id']:row for row in _spooled(directory)})
        rows=list(by_id.values())
    return rows

_init_lock = threading.Lock()
_initialized = set()
_scans = {}


@contextlib.contextmanager
def connection(directory):
    from app.bootstrap.auxiliary_store import enabled, gauss_store
    if enabled():
        with gauss_store('journal') as db:
            yield db
        return
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'journal.sqlite3'
    with _init_lock:
        if str(path) not in _initialized or not path.exists():
            with contextlib.closing(sqlite3.connect(path, timeout=10)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.executescript('''
CREATE TABLE IF NOT EXISTS journal (
 run_id TEXT PRIMARY KEY, pid TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, pending INTEGER NOT NULL, retry_at REAL NOT NULL DEFAULT 0,
 payload TEXT NOT NULL, log_path TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS journal_pid_time ON journal(pid,created_at DESC);
CREATE INDEX IF NOT EXISTS journal_time ON journal(created_at);
CREATE INDEX IF NOT EXISTS journal_pending ON journal(pending,retry_at,created_at);
CREATE INDEX IF NOT EXISTS journal_status ON journal(status,created_at);
''')
                db.commit()
            _initialized.add(str(path))
    with contextlib.closing(sqlite3.connect(path, timeout=10)) as db:
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def read(directory, run_id):
    if enabled():
        import re
        if not re.fullmatch('[a-f0-9]{32}',str(run_id)): raise ValueError('invalid run ID')
        pending_file=Path(directory)/(run_id+'.json')
        if pending_file.is_file() and not pending_file.is_symlink():
            return json.loads(pending_file.read_text(encoding='utf-8'))
    with connection(directory) as db:
        row = db.execute('SELECT payload FROM journal WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def write(directory, record, terminal):
    pending = not record.get('db_synced') or (record['status'] in terminal and not record.get('history_saved'))
    run_id = record['run_id']
    path = record.get('log_path') or f"logs/{record['created_at'][:10]}/{run_id[:2]}/{run_id}.log"
    record['log_path'] = path
    if enabled(): _spool(directory,record)
    try:
        with connection(directory) as db:
            db.execute('''INSERT INTO journal(run_id,pid,status,created_at,pending,retry_at,payload,log_path)
VALUES(?,?,?,?,?,0,?,?) ON CONFLICT(run_id) DO UPDATE SET
 status=excluded.status,pending=excluded.pending,retry_at=0,payload=excluded.payload''',
                       (run_id, record['pid'], record['status'], record['created_at'], int(pending), json.dumps(record, ensure_ascii=False), path))
    except Exception:
        if not enabled(): raise
        logger.warning('GaussDB journal write deferred; recovery file retained',exc_info=True)
        return
    if enabled(): (Path(directory)/(run_id+'.json')).unlink(missing_ok=True)


def recent(directory, pid=None, limit=50):
    rows=_records(directory,'SELECT payload FROM journal '+('WHERE pid=? ' if pid else '')+
                  'ORDER BY created_at DESC LIMIT ?', (pid,limit) if pid else (limit,))
    return sorted((row for row in rows if not pid or row['pid']==pid), key=lambda row:row['created_at'],reverse=True)[:limit]


def pending(directory, limit):
    return _records(directory,'SELECT payload FROM journal WHERE pending=1 AND retry_at<=? ORDER BY retry_at,created_at LIMIT ?', (time.time(),limit))[:limit]


def defer(directory, run_id):
    with connection(directory) as db:
        db.execute('UPDATE journal SET retry_at=? WHERE run_id=?', (time.time()+60, run_id))


def active(directory):
    return [row for row in _records(directory,"SELECT payload FROM journal WHERE status IN ('running','queued')") if row['status'] in ('running','queued')]


def expire(directory, cutoff, limit):
    with connection(directory) as db:
        rows = db.execute('SELECT run_id,log_path FROM journal WHERE created_at<? AND pending=0 '
                          "AND status NOT IN ('running','queued') ORDER BY created_at LIMIT ?", (cutoff, limit)).fetchall()
        for run_id, relative in rows:
            path = (Path(directory) / relative).resolve()
            path.relative_to(Path(directory).resolve())
            path.unlink(missing_ok=True)
            db.execute('DELETE FROM journal WHERE run_id=?', (run_id,))
    return len(rows)


def import_legacy(directory, terminal, limit):
    """Persist before removing old JSON; preserve old flat log paths."""
    key = str(directory)
    Path(directory).mkdir(parents=True,exist_ok=True)
    scan = _scans.get(key)
    if scan is None:
        scan = _scans[key] = os.scandir(directory)
    imported = []
    for _ in range(limit):
        try:
            entry = next(scan)
        except StopIteration:
            scan.close()
            _scans.pop(key, None)
            break
        if not entry.name.endswith('.json') or not entry.is_file(follow_symlinks=False):
            continue
        path = Path(entry.path)
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            import re
            if not re.fullmatch('[a-f0-9]{32}', record.get('run_id', '')) or path.stem != record['run_id']:
                continue
            if enabled():
                write(directory, record, terminal)
                if not path.exists(): imported.append(record)
                continue
            if read(directory, record['run_id']) is None:
                record['log_path'] = record['run_id']+'.log'
                write(directory, record, terminal)
                imported.append(record)
            path.unlink()
        except (OSError, ValueError, KeyError, TypeError):
            # Invalid legacy files remain available for manual inspection.
            continue
    return imported


def health(directory):
    try:
        with connection(directory) as db:
            due = db.execute('SELECT COUNT(*),MIN(created_at) FROM journal WHERE pending=1').fetchone()
    except Exception:
        if not enabled(): raise
        due=(0,None)
    files=_spooled(directory) if enabled() else []
    oldest=min([value for value in [due[1],*[item['created_at'] for item in files]] if value],default='')
    return {'pending_writes': due[0]+len(files), 'oldest_pending': oldest,
            'legacy_scan_in_progress': str(directory) in _scans,
            'journal_bytes': sum(p.stat().st_size for p in Path(directory).glob('journal.sqlite3*')),
            'pending_recovery_files':len(files), 'oldest_recovery_file':oldest}
