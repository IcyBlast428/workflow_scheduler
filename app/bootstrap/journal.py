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

_init_lock = threading.Lock()
_initialized = set()
_scans = {}


@contextlib.contextmanager
def connection(directory):
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
    with connection(directory) as db:
        row = db.execute('SELECT payload FROM journal WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def write(directory, record, terminal):
    pending = not record.get('db_synced') or (record['status'] in terminal and not record.get('history_saved'))
    run_id = record['run_id']
    path = record.get('log_path') or f"logs/{record['created_at'][:10]}/{run_id[:2]}/{run_id}.log"
    record['log_path'] = path
    with connection(directory) as db:
        db.execute('''INSERT INTO journal(run_id,pid,status,created_at,pending,retry_at,payload,log_path)
VALUES(?,?,?,?,?,0,?,?) ON CONFLICT(run_id) DO UPDATE SET
 status=excluded.status,pending=excluded.pending,retry_at=0,payload=excluded.payload''',
                   (run_id, record['pid'], record['status'], record['created_at'], int(pending), json.dumps(record, ensure_ascii=False), path))


def recent(directory, pid=None, limit=50):
    with connection(directory) as db:
        rows = db.execute('SELECT payload FROM journal ' + ('WHERE pid=? ' if pid else '') +
                          'ORDER BY created_at DESC LIMIT ?', (pid, limit) if pid else (limit,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def pending(directory, limit):
    with connection(directory) as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT payload FROM journal WHERE pending=1 AND retry_at<=? ORDER BY retry_at,created_at LIMIT ?', (time.time(), limit))]


def defer(directory, run_id):
    with connection(directory) as db:
        db.execute('UPDATE journal SET retry_at=? WHERE run_id=?', (time.time()+60, run_id))


def active(directory):
    with connection(directory) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM journal WHERE status IN ('running','queued')")]


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
    with connection(directory) as db:
        due = db.execute('SELECT COUNT(*),MIN(created_at) FROM journal WHERE pending=1').fetchone()
    return {'pending_writes': due[0], 'oldest_pending': due[1] or '',
            'legacy_scan_in_progress': str(directory) in _scans,
            'journal_bytes': sum(p.stat().st_size for p in Path(directory).glob('journal.sqlite3*'))}
