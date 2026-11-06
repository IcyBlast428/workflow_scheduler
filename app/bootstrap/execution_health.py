"""A cached, SQL-aggregated completion window, separate from sampled latencies."""
import datetime as dt
import os
from collections import Counter

from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import state_status
from app.bootstrap.snapshot_cache import cached
from app.bootstrap.timebase import business_now


def completion_summary(rows):
    counts = Counter()
    for state, count in rows:
        counts[state_status(state)] += int(count)
    failed = counts['failed'] + counts['timed_out']
    attempts = counts['success'] + failed
    return {'counts': dict(counts), 'completed': sum(counts.values()),
            'attempts': attempts, 'failures': failed,
            'failure_rate': round(failed / attempts * 100, 2) if attempts else None}


def execution_health():
    def query():
        end = business_now()
        start = end - dt.timedelta(hours=24)
        with GaussDB() as db:
            rows = db.execute_query_sql(
                'SELECT state,COUNT(*) FROM wfs_run_history WHERE end_time>=? AND end_time<? GROUP BY state',
                params=(str(start), str(end)))
        return {**completion_summary(rows), 'from': str(start), 'to': str(end), 'cache_seconds': 30}
    key = ('execution_health', os.environ.get('WFS_DB_ID'), os.environ.get('WFS_DB_CONFIG_FILE'))
    return cached(key, 30, query, mutable=False)
