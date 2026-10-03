"""100 real task subprocesses in a disposable local environment."""
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='wfs-pipeline-') as temporary:
        root=Path(temporary)
        os.environ.update(WFS_ENV='development',WFS_ENABLE_SCHEDULER='false',WFS_LOCAL_DB_PATH=str(root/'database.sqlite3'),WFS_DATA_DIR=str(root/'data'))
        from app.bootstrap.execution import execute_py
        from app.bootstrap import operations
        from app.bootstrap.database import GaussDB
        from app.bootstrap.global_vars import runnings
        fast=root/'fast.py';fast.write_text('import time\ntime.sleep(.01)\nprint("short success")\n')
        slow=root/'slow.py';slow.write_text('import time\ntime.sleep(.2)\nprint("long success")\n')
        failure=root/'failure.py';failure.write_text('raise RuntimeError("expected test failure")\n')
        timeout=root/'timeout.py';timeout.write_text('import time\ntime.sleep(30)\n')
        def run(index):
            script=timeout if index%25==0 else failure if index%10==0 else slow if index%3==0 else fast
            return execute_py(script,f'benchmark-{index:03}',timeout_seconds=1 if script==timeout else 10)
        started=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(run,range(100)))
        operations.maintenance()
        with GaussDB() as db:
            counts=dict(db.execute_query_sql('SELECT status,SUM(executions) FROM wfs_run_summary GROUP BY status'))
            history=db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history')[0][0]
        assert len(results)==history==sum(counts.values())==100,(results,history,counts)
        assert not runnings.count()
        report={'real_task_subprocesses':100,'parallel_workers':8,'seconds':round(time.perf_counter()-started,2),'results':counts,
                'remaining_reservations':runnings.count(),'lock_objects':len(operations._locks),
                'boundary':'One bounded local burst, not a sustained production load test.'}
        print(json.dumps(report,indent=2))
