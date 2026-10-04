"""Idempotent hourly counters written in the completion transaction."""
import datetime as dt
from collections import Counter
from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import state_status, is_failure


def summarize_row(db, identifier, pid, state, ended):
    suffix = ' FOR UPDATE' if db.dialect == 'PostgreSQL' else ''
    updated = db.execute_query_sql('SELECT summary_version FROM wfs_run_history WHERE id=? AND end_time=?'+suffix, params=(identifier,ended))
    if not updated or updated[0][0]:
        return
    original_ended = ended
    ended = dt.datetime.fromisoformat(str(ended))
    bucket = ended.replace(minute=0,second=0,microsecond=0)
    status = state_status(state)
    if db.dialect == 'PostgreSQL':
        _increment(db, Counter({(pid,bucket,status):1}), Counter({pid:1}) if is_failure(state) else Counter())
        db.execute_sql('UPDATE wfs_run_history SET summary_version=1 WHERE id=? AND end_time=?', params=(identifier,original_ended))
        return
    if not db._local_sqlite:
        db.execute_sql('LOCK TABLE wfs_run_summary,wfs_run_totals IN EXCLUSIVE MODE')
    if db.execute_query_sql('SELECT 1 FROM wfs_run_summary WHERE pid=? AND bucket=? AND status=?',params=(pid,bucket,status)):
        db.execute_sql('UPDATE wfs_run_summary SET executions=executions+1 WHERE pid=? AND bucket=? AND status=?',params=(pid,bucket,status))
    else:
        db.execute_sql('INSERT INTO wfs_run_summary(pid,bucket,status,executions) VALUES(?,?,?,1)',params=(pid,bucket,status))
    if is_failure(state):
        if db.execute_query_sql('SELECT 1 FROM wfs_run_totals WHERE pid=?',params=(pid,)):
            db.execute_sql('UPDATE wfs_run_totals SET failures=failures+1 WHERE pid=?',params=(pid,))
        else:
            db.execute_sql('INSERT INTO wfs_run_totals(pid,failures) VALUES(?,1)',params=(pid,))
    db.execute_sql('UPDATE wfs_run_history SET summary_version=1 WHERE id=? AND end_time=?', params=(identifier,original_ended))


def backfill(limit=500):
    with GaussDB() as db:
        db.begin_transaction()
        try:
            if not db._local_sqlite and db.dialect != 'PostgreSQL':
                db.execute_sql('LOCK TABLE wfs_run_summary,wfs_run_totals IN EXCLUSIVE MODE')
            suffix = '' if db._local_sqlite else ' FOR UPDATE SKIP LOCKED' if db.dialect == 'PostgreSQL' else ' FOR UPDATE'
            rows = db.execute_query_sql('SELECT id,pid,state,end_time FROM wfs_run_history WHERE summary_version=0 ORDER BY end_time,id LIMIT ?'+suffix, params=(limit,))
            groups,failures = Counter(),Counter()
            for identifier,pid,state,ended in rows:
                bucket=dt.datetime.fromisoformat(str(ended)).replace(minute=0,second=0,microsecond=0)
                groups[pid,bucket,state_status(state)]+=1
                if is_failure(state):
                    failures[pid]+=1
            for (pid,bucket,status),count in groups.items():
                if db.dialect == 'PostgreSQL':
                    continue
                if db.execute_query_sql('SELECT 1 FROM wfs_run_summary WHERE pid=? AND bucket=? AND status=?',params=(pid,bucket,status)):
                    db.execute_sql('UPDATE wfs_run_summary SET executions=executions+? WHERE pid=? AND bucket=? AND status=?',params=(count,pid,bucket,status))
                else:
                    db.execute_sql('INSERT INTO wfs_run_summary(pid,bucket,status,executions) VALUES(?,?,?,?)',params=(pid,bucket,status,count))
            for pid,count in failures.items():
                if db.dialect == 'PostgreSQL':
                    continue
                if db.execute_query_sql('SELECT 1 FROM wfs_run_totals WHERE pid=?',params=(pid,)):
                    db.execute_sql('UPDATE wfs_run_totals SET failures=failures+? WHERE pid=?',params=(count,pid))
                else:
                    db.execute_sql('INSERT INTO wfs_run_totals(pid,failures) VALUES(?,?)',params=(pid,count))
            if db.dialect == 'PostgreSQL':
                _increment(db, groups, failures)
            # Exact composite keys protect old installations that reused an ID.
            for offset in range(0,len(rows),200):
                group=rows[offset:offset+200]
                predicate=' OR '.join('(id=? AND end_time=?)' for _ in group)
                db.execute_sql('UPDATE wfs_run_history SET summary_version=1 WHERE '+predicate,
                               params=tuple(value for identifier,pid,state,ended in group for value in (identifier,ended)))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
    return len(rows)


def _increment(db, groups, failures):
    # Stable ordering prevents two backfill batches from locking shared rows in
    # opposite order. Unique keys plus history row locks preserve idempotency.
    for (pid,bucket,status),count in sorted(groups.items()):
        db.execute_sql('INSERT INTO wfs_run_summary(pid,bucket,status,executions) VALUES(?,?,?,?) '
                       'ON CONFLICT(pid,bucket,status) DO UPDATE SET executions=wfs_run_summary.executions+EXCLUDED.executions',
                       params=(pid,bucket,status,count))
    for pid,count in sorted(failures.items()):
        db.execute_sql('INSERT INTO wfs_run_totals(pid,failures) VALUES(?,?) '
                       'ON CONFLICT(pid) DO UPDATE SET failures=wfs_run_totals.failures+EXCLUDED.failures',params=(pid,count))


def coverage(db):
    pending = db.execute_query_sql('SELECT end_time FROM wfs_run_history WHERE summary_version=0 ORDER BY end_time LIMIT 1')
    return {'complete':not bool(pending), 'oldest_pending':str(pending[0][0]) if pending else ''}
