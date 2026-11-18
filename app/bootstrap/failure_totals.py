"""Read cumulative failures, including online rows still awaiting summary backfill."""
from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import FAILURE_SQL


def _counts(db):
    # A single statement sees each completion on exactly one side of backfill.
    rows = db.execute_query_sql(f"""
        SELECT pid,SUM(failures),SUM(expected_archive),SUM(actual_archive)
        FROM (
            SELECT pid,failures,archived_failures AS expected_archive,0 AS actual_archive
            FROM wfs_run_totals
            UNION ALL
            SELECT pid,0,0,archived_failures FROM wfs_history_rollup
            UNION ALL
            SELECT pid,COUNT(*),0,0 FROM wfs_run_history
            WHERE summary_version=0 AND {FAILURE_SQL} GROUP BY pid
        ) counts GROUP BY pid
    """)
    return ([(pid, failures) for pid, failures, _, _ in rows],
            [pid for pid, _, expected, actual in rows if expected != actual])


def load_totals():
    with GaussDB() as db:
        rows, changed = _counts(db)
        if not changed:
            return rows
        # Older/external archive jobs may only update the rollup. Serialize repair
        # with archive and completion writes, then recheck after acquiring the lock.
        db.begin_transaction()
        try:
            db.execute_sql('LOCK TABLE wfs_history_rollup,wfs_run_totals IN SHARE ROW EXCLUSIVE MODE')
            rows, changed = _counts(db)
            for offset in range(0, len(changed), 200):
                pids = tuple(changed[offset:offset + 200])
                places = ','.join('?' for _ in pids)
                db.execute_sql(f'DELETE FROM wfs_run_totals WHERE pid IN ({places})', params=pids)
                db.execute_sql(f"""
                    INSERT INTO wfs_run_totals(pid,failures,archived_failures)
                    SELECT pid,SUM(failures),SUM(archived_failures) FROM (
                        SELECT pid,COUNT(*) AS failures,0 AS archived_failures FROM wfs_run_history
                        WHERE pid IN ({places}) AND summary_version=1 AND {FAILURE_SQL}
                        GROUP BY pid
                        UNION ALL
                        SELECT pid,archived_failures,archived_failures FROM wfs_history_rollup
                        WHERE pid IN ({places})
                    ) repaired GROUP BY pid
                """, params=pids + pids)
            if changed:
                rows, _ = _counts(db)
            db.set_commit()
            return rows
        except Exception:
            db.set_rollback()
            raise
