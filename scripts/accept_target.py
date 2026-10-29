"""Read-only target deployment checks; never mutates production tasks or tables."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def check(url,database=False):
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or parsed.username or parsed.password: raise ValueError('请使用不含凭据的 HTTP/HTTPS 服务地址。')
    report={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'checks':{},'database_write_tested':False}
    try:
        with urllib.request.urlopen(url.rstrip('/')+'/api/user/ready',timeout=10) as response:
            data=json.load(response)['data'];report['checks']['readiness']=bool(data['ready'])
    except Exception:report['checks']['readiness']=False
    if database:
        from app.bootstrap.database import GaussDB
        with GaussDB() as db:
            db.execute_query_sql('SELECT 1')
            report['database']=db.dialect
            report['checks']['database_read']=True
            for table in ('wfs_job_stats','wfs_executions','wfs_notifications','wfs_task_releases'):
                db.execute_query_sql('SELECT 1 FROM '+table+' LIMIT 1')
            report['checks']['required_tables']=True
    report['passed']=all(report['checks'].values())
    report['not_verified']=['real notification delivery','private GitLab permissions and certificates','database write/transaction/failover','restore and business reconciliation']
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--database',action='store_true');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report=check(args.url,args.database)
    with open(args.output,'x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print('Target read-only checks: '+('passed' if report['passed'] else 'failed'));sys.exit(0 if report['passed'] else 1)
