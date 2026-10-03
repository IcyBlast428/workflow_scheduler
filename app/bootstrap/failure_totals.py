"""Fast cumulative counters with reconciliation after external archival.

Archival is deliberately unchanged. When its small rollup table changes, rebuild
counters once under the same lock used by completion writes, preserving totals.
"""
from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import FAILURE_SQL
from app.bootstrap.run_summary import coverage


def load_totals():
    with GaussDB() as db:
        db.begin_transaction()
        try:
            if not db._local_sqlite:
                db.execute_sql('LOCK TABLE wfs_run_summary,wfs_run_totals IN EXCLUSIVE MODE')
            full = not coverage(db)['complete']
            archives = dict(db.execute_query_sql('SELECT pid,archived_failures FROM wfs_history_rollup'))
            previous = {pid:int(archived) for pid,archived in db.execute_query_sql('SELECT pid,archived_failures FROM wfs_run_totals')}
            changed = any(int(value)!=previous.get(pid,0) for pid,value in archives.items()) or any(value and pid not in archives for pid,value in previous.items())
            if full or changed:
                rows = db.execute_query_sql(f'''SELECT pid,SUM(n) FROM (
SELECT pid,COUNT(*) AS n FROM wfs_run_history WHERE {FAILURE_SQL} GROUP BY pid
UNION ALL SELECT pid,archived_failures FROM wfs_history_rollup
) totals GROUP BY pid''')
                if not full:
                    db.execute_sql('DELETE FROM wfs_run_totals')
                    for pid,count in rows:
                        db.execute_sql('INSERT INTO wfs_run_totals(pid,failures,archived_failures) VALUES(?,?,?)',params=(pid,count,archives.get(pid,0)))
            else:
                rows = db.execute_query_sql('SELECT pid,failures FROM wfs_run_totals')
            db.set_commit()
            return rows
        except Exception:
            db.set_rollback()
            raise
