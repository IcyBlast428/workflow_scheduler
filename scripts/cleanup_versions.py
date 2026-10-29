"""Full reference scan and explicit clean-up, only while Scheduler is stopped."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment-file',required=True);parser.add_argument('--data',required=True)
    parser.add_argument('--keep',type=int,default=20);parser.add_argument('--scan-seconds',type=int,default=120)
    parser.add_argument('--preview');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--fingerprint');parser.add_argument('--confirm')
    args=parser.parse_args()
    from scripts.service_config import read_environment
    values,removed=read_environment(args.environment_file)
    for key in removed:os.environ.pop(key,None)
    os.environ.update(values,WFS_DATA_DIR=str(Path(args.data).resolve()),WFS_ENABLE_SCHEDULER='false',WFS_SCHEDULER_CONTROL_URL='')
    if not 1<=args.scan_seconds<=600:raise ValueError('容量扫描时间应在 1–600 秒。')
    data=Path(args.data).resolve()
    with (data/'.scheduler.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from app.bootstrap import admission,version_cleanup
        from app.bootstrap.database import GaussDB
        if not admission.maintenance()['enabled']:raise ValueError('请先在平台进入维护模式，再停止服务。')
        protected=set();last='';rows_checked=0
        with GaussDB() as db:
            while True:
                rows=db.execute_query_sql('SELECT run_id,payload FROM wfs_executions WHERE run_id>? ORDER BY run_id LIMIT 2000',params=(last,))
                if not rows:break
                for identifier,payload in rows:
                    record=json.loads(payload)
                    if record.get('status') in ('running','queued'):raise ValueError('存在未完成执行记录，请先核对恢复状态。')
                    version=(record.get('code_version') or {}).get('task_release')
                    if version:protected.add((record['pid'],version))
                last=rows[-1][0];rows_checked+=len(rows)
        plan=version_cleanup.plan(args.keep,full_references=protected,scan_seconds=args.scan_seconds)
        plan['execution_rows_checked']=rows_checked
        if args.preview:
            with open(args.preview,'x',encoding='utf-8') as output:json.dump(plan,output,ensure_ascii=False,indent=2)
        if args.execute:
            result=version_cleanup.execute({'keep':args.keep,'fingerprint':args.fingerprint,'confirm':args.confirm},'offline-maintenance',full_references=protected,scan_seconds=args.scan_seconds)
            print('Cleaned '+str(len(result['cleaned']))+' unreferenced releases')
        elif not args.preview:raise ValueError('请指定新的预览文件，或明确执行已核对的计划。')
        else:print('Preview complete; no files removed. Execution rows checked: '+str(rows_checked))

if __name__=='__main__':main()
