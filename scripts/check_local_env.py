"""Read-only startup checks. Never prints environment values or credentials."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description='检查当前环境，配置应由启动脚本加载。')
    parser.add_argument('--database',action='store_true',help='同时检查数据库连接和迁移表')
    args=parser.parse_args()
    checks=[]
    def add(name,ok,message): checks.append({'name':name,'ok':bool(ok),'message':message})
    add('Python',sys.version_info>=(3,12),f'{sys.version_info.major}.{sys.version_info.minor}；生产基准 3.12')
    for module in ('flask','apscheduler','pytz','pyodbc'):
        add('依赖 '+module,importlib.util.find_spec(module) is not None,'已安装' if importlib.util.find_spec(module) else '缺少依赖')
    data=Path(os.environ.get('WFS_DATA_DIR',str(ROOT/'data')))
    existing=data
    while not existing.exists(): existing=existing.parent
    free=shutil.disk_usage(existing).free//1024**2
    add('数据目录',os.access(existing,os.W_OK),f'剩余 {free} MiB')
    add('前端产物',(ROOT/'app/dist/index.html').exists(),'已构建' if (ROOT/'app/dist/index.html').exists() else '需要构建前端')
    for key,default in [('WFS_PORT','18008'),('WFS_CONTROL_PORT','18009')]:
        port=int(os.environ.get(key,default))
        with socket.socket() as probe:
            probe.settimeout(.3); listening=probe.connect_ex(('127.0.0.1',port))==0
        # An occupied port can belong to this running project: report rather than stop it.
        add('端口 '+str(port),True,'已有服务监听，请核对项目服务状态' if listening else '可用')
    if args.database:
        try:
            tables = ('wfs_schema_migrations','wfs_task_config','wfs_run_history','wfs_executions')
            if os.environ.get('WFS_LOCAL_DB_PATH'):
                path = Path(os.environ['WFS_LOCAL_DB_PATH']).expanduser().resolve()
                connection = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
                try:
                    for table in tables:
                        connection.execute(f'SELECT 1 FROM {table} LIMIT 0')
                finally:
                    connection.close()
                dialect = 'SQLite'
            else:
                from app.bootstrap.database import GaussDB
                with GaussDB() as db:
                    for table in tables:
                        db.execute_query_sql(f'SELECT 1 FROM {table} LIMIT 0')
                    dialect = db.dialect
            add('数据库',True,dialect+' · 连接及基础迁移表正常')
        except Exception:
            add('数据库',False,'连接或迁移检查未通过，请核对配置与服务日志')
    print(json.dumps({'checks':checks,'timezone':'Asia/Shanghai（UTC+8）','scheduler':'必须保持单实例；用 local_service.sh status 核对'},ensure_ascii=False,indent=2))
    return 0 if all(item['ok'] for item in checks) else 1


if __name__=='__main__': raise SystemExit(main())
