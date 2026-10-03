"""Two million synthetic history rows in the dedicated local PostgreSQL database."""
import datetime as dt
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if os.environ.get('WFS_POSTGRES_TEST')!='true' or os.environ.get('WFS_DB_ID')!='wfstest_wfs' or os.environ.get('WFS_LOCAL_DB_PATH'):
    raise SystemExit('Dedicated PostgreSQL test database required.')
from app.bootstrap.database import GaussDB

rows=2_000_000
with GaussDB() as db:
    existing=db.execute_query_sql("SELECT COUNT(*) FROM wfs_run_history WHERE group_name='postgres-volume-test'")[0][0]
    if existing not in (0,rows):
        raise SystemExit('Unexpected partial capacity-test dataset; inspect it before continuing.')
    if existing==0:
        db.execute_sql('SET statement_timeout=300000')
        started=time.perf_counter()
        db.execute_sql("""INSERT INTO wfs_run_history(id,pid,taskname,dirname,group_name,folder_name,state,tasklog,start_time,end_time)
            SELECT md5('wfs-pg-volume:'||g::text), 'volume__task_'||lpad((g%100)::text,3,'0'),
              '容量测试任务 '||lpad((g%100)::text,3,'0'),'synthetic','postgres-volume-test','synthetic',
              CASE WHEN g%1000=0 THEN 1 ELSE 0 END,'合成容量测试日志；非真实业务数据。',
              date_trunc('second',localtimestamp)-interval '5 minutes'-(g-1)*interval '1.296 seconds'-interval '2 seconds',
              date_trunc('second',localtimestamp)-interval '5 minutes'-(g-1)*interval '1.296 seconds'
            FROM generate_series(1,2000000) AS g""")
        print(f'Inserted {rows} synthetic rows in {time.perf_counter()-started:.2f}s',flush=True)
        db.execute_sql('ANALYZE wfs_run_history')
    newest=db.execute_query_sql("SELECT MAX(end_time) FROM wfs_run_history WHERE group_name='postgres-volume-test'")[0][0]
    lower=newest-dt.timedelta(days=7)
    anchor=db.execute_query_sql('SELECT end_time,id FROM wfs_run_history ORDER BY end_time DESC,id DESC LIMIT 1 OFFSET 1000000')[0]
    cases={
      'recent_page':('SELECT id,pid,state,end_time FROM wfs_run_history WHERE end_time>=? AND end_time<=? ORDER BY end_time DESC,id DESC LIMIT 20',(lower,newest)),
      'task_page':('SELECT id,pid,state,end_time FROM wfs_run_history WHERE pid=? AND end_time>=? AND end_time<=? ORDER BY end_time DESC,id DESC LIMIT 20',('volume__task_001',lower,newest)),
      'deep_cursor':('SELECT id,pid,state,end_time FROM wfs_run_history WHERE end_time<=? AND (end_time<? OR (end_time=? AND id<?)) ORDER BY end_time DESC,id DESC LIMIT 20',(anchor[0],anchor[0],anchor[0],anchor[1])),
    }
    result={'database':'PostgreSQL 18.1','driver':'PostgreSQL Unicode / pyodbc','synthetic_rows':rows,'cases':{}}
    for name,(sql,params) in cases.items():
        durations=[]
        for _ in range(5):
            start=time.perf_counter(); data=db.execute_query_sql(sql,params=params); durations.append((time.perf_counter()-start)*1000)
        plan=db.execute_query_sql('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+sql,params=params)[0][0]
        result['cases'][name]={'rows_returned':len(data),'median_ms':round(statistics.median(durations),2),'max_ms':round(max(durations),2),'plan':json.loads(plan)}
        print(f'{name}: median={statistics.median(durations):.2f}ms; max={max(durations):.2f}ms',flush=True)
    result['database_size']=db.execute_query_sql("SELECT pg_size_pretty(pg_database_size(current_database()))")[0][0]
    output=ROOT/'data'/'postgres-history-benchmark.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Report: {output}')
