"""Compare bounded completion bursts, only in the fresh acceptance schema."""
import concurrent.futures
import json
import os
import time
import uuid
from unittest.mock import patch


def benchmark(count=100):
    if not os.environ.get('WFS_DB_ID','').startswith('wfstest_wfs_acceptance_') or os.environ.get('WFS_POSTGRES_TEST')!='true':
        raise RuntimeError('A fresh acceptance schema is required.')
    from app.bootstrap.database import GaussDB
    from app.bootstrap import operations
    report={}
    for mode in ('table-lock','postgres-row-upsert'):
        prefix='benchmark-'+uuid.uuid4().hex
        def complete(index):
            identifier=operations.create_run(prefix+f'-{index%10}',source='benchmark')
            record=operations.update_run(identifier,status='success',state=0,end_time=operations.now())
            began=time.perf_counter(); operations.save_history(record)
            if not operations.read_run(identifier)['history_saved']: raise RuntimeError('Completion was deferred.')
            return (time.perf_counter()-began)*1000
        began=time.perf_counter()
        if mode=='table-lock':
            context=patch.object(GaussDB,'dialect',property(lambda self:'GaussDB/DWS'))
        else:
            from contextlib import nullcontext
            context=nullcontext()
        with context,concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            durations=sorted(pool.map(complete,range(count)))
        with GaussDB() as db:
            total=db.execute_query_sql('SELECT SUM(executions) FROM wfs_run_summary WHERE pid LIKE ?',params=(prefix+'%',))[0][0]
        assert total==count,(mode,total)
        report[mode]={'records':count,'workers':8,'seconds':round(time.perf_counter()-began,3),'completion_p95_ms':round(durations[int(len(durations)*.95)],2),'max_ms':round(max(durations),2)}
    report['boundary']='One local bounded burst, not sustained production or GaussDB validation.'
    print('PostgreSQL completion benchmark: '+json.dumps(report))
    return report
