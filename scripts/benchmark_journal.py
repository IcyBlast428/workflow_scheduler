"""Disposable journal scale test; creates no production/task records."""
import argparse
import datetime as dt
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.bootstrap import journal, operations


def benchmark(rows,files):
    with tempfile.TemporaryDirectory(prefix='wfs-scale-') as temporary:
        root=Path(temporary)
        started=time.perf_counter()
        with journal.connection(root) as db:
            for offset in range(0,rows,5000):
                batch=[]
                for i in range(offset,min(rows,offset+5000)):
                    identifier=f'{i:032x}';pid=f'task-{i%100:03}';created=(dt.datetime(2026,1,1)+dt.timedelta(seconds=i)).isoformat(' ')
                    record={'run_id':identifier,'pid':pid,'created_at':created,'status':'success','db_synced':True,'history_saved':True}
                    batch.append((identifier,pid,'success',created,0,json.dumps(record),'unused.log'))
                db.executemany('INSERT INTO journal(run_id,pid,status,created_at,pending,payload,log_path) VALUES(?,?,?,?,?,?,?)',batch)
        for i in range(files):
            directory=root/'logs'/f'{i%256:02x}'
            directory.mkdir(exist_ok=True,parents=True)
            (directory/f'{i:032x}.log').touch()
        build_seconds=time.perf_counter()-started
        timings=[]
        with patch.object(operations,'_directory',root):
            for _ in range(20):
                began=time.perf_counter();assert len(journal.recent(root,'task-050',50))==50;timings.append((time.perf_counter()-began)*1000)
            began=time.perf_counter();assert journal.pending(root,500)==[];pending_ms=(time.perf_counter()-began)*1000
        with journal.connection(root) as db:
            plan=[row[-1] for row in db.execute('EXPLAIN QUERY PLAN SELECT payload FROM journal WHERE pid=? ORDER BY created_at DESC LIMIT 50',('task-050',))]
        assert any('journal_pid_time' in line for line in plan),plan
        return {'indexed_records':rows,'task_count':100,'actual_log_files':files,'build_seconds':round(build_seconds,2),
                'recent_median_ms':round(statistics.median(timings),2),'recent_p95_ms':round(sorted(timings)[18],2),
                'pending_ms':round(pending_ms,2),'lock_objects':len(operations._locks),'plan':plan,
                'boundary':'Synthetic local journal/read test; not a production scheduler throughput guarantee.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows',type=int,default=1000000)
    parser.add_argument('--files',type=int,default=10000)
    parser.add_argument('--output')
    args=parser.parse_args()
    if not 5000<=args.rows<=10000000 or not 0<=args.files<=1000000:
        parser.error('rows: 5000..10000000; files: 0..1000000')
    result=benchmark(args.rows,args.files)
    if args.output:
        Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
