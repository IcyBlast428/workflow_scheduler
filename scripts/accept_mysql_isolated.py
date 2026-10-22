"""Explicit MySQL acceptance in a newly created and finally removed database.

Requires WFS_TEST_MYSQL=true and local MySQL administrative credentials. Never
reuses an existing database, managed profile or production configuration.
"""
import concurrent.futures
import contextlib
import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get('WFS_TEST_MYSQL') != 'true':
        raise SystemExit('Set WFS_TEST_MYSQL=true to run against a dedicated LOCAL test server.')
    import pymysql
    from werkzeug.security import generate_password_hash
    database = 'wfs_acceptance_' + uuid.uuid4().hex
    profile = dict(id='platform', dialect='mysql', host='127.0.0.1',
                   port=int(os.environ.get('WFS_MYSQL_TEST_PORT', '33080')),
                   user=os.environ.get('WFS_MYSQL_TEST_USER', 'root'),
                   password=os.environ.get('WFS_MYSQL_TEST_PASSWORD', ''),
                   database=database, charset='utf8mb4', tls='disabled', ssl_ca='', revision=0)
    with contextlib.closing(pymysql.connect(host=profile['host'], port=profile['port'],
                                         user=profile['user'], password=profile['password'], autocommit=True)) as control:
        with control.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
        try:
            with tempfile.TemporaryDirectory(prefix='wfs-mysql-acceptance-') as temporary:
                os.environ.update(WFS_ENV='development', WFS_ENABLE_SCHEDULER='false', WFS_SCHEDULER_CONTROL_URL='',
                                  WFS_DATA_DIR=temporary, WFS_LOG_DIR=str(Path(temporary)/'logs'),
                                  WFS_SECRET_KEY='isolated-mysql-test-key',
                                  WFS_ADMIN_PASSWORD_HASH=generate_password_hash('mysql-test-password'))
                os.environ.pop('WFS_LOCAL_DB_PATH', None)
                os.environ.pop('WFS_IGNORE_MANAGED_DATABASE', None)
                from app.bootstrap import connection_settings as settings
                result = settings.probe(profile, initialize=True)
                assert result['ready'], result
                settings.save(profile)
                settings.activate_at_app_start()
                from app.bootstrap.database import GaussDB
                from app.bootstrap import global_vars
                global_vars.TASK_DIR = Path(temporary)/'jobs'
                task = global_vars.TASK_DIR/'mysql'/'sample'
                task.mkdir(parents=True)
                script = task/'main.py'
                script.write_text('print("MySQL 中文执行验收")\n', encoding='utf-8')
                from app import create_app
                from app.bootstrap.schedule_config import save_schedule, load_schedule
                from app.bootstrap import operations
                from app.bootstrap.execution import execute_py
                from app.bootstrap.run_summary import backfill
                from app.bootstrap.failure_totals import load_totals
                from app.bootstrap.history import archive_batch
                from app.bootstrap.timebase import business_now
                from scripts.migrate import main as migrate
                app = create_app()
                app.testing = True
                migrate()
                pid = 'mysql__sample'
                config = save_schedule(pid, {'schedule_type':'every_hour', 'main_file':'main.py', 'enabled':False})
                assert load_schedule(pid)['version'] == config['version']
                with GaussDB() as db:
                    assert db.dialect == 'MySQL'
                    db.execute_sql('INSERT INTO wfs_job_stats(pid,task_name,failed_times) VALUES(?,?,0)', params=(pid, '中文任务'))
                    db.begin_transaction()
                    db.execute_sql('UPDATE wfs_job_stats SET failed_times=99 WHERE pid=?', params=(pid,))
                    db.set_rollback()
                    assert db.execute_query_sql('SELECT failed_times FROM wfs_job_stats WHERE pid=?', params=(pid,))[0][0] == 0
                    db.execute_query_sql("SELECT DATE_FORMAT(NOW(),'%Y-%m-%d'), ? AS value", params=('50%? 中文',))
                assert execute_py(script, pid) == 0
                # Concurrent durable completions and a repeat backfill must not
                # double-count rows or lose cumulative failures.
                def complete(index):
                    run = operations.create_run(pid, source='manual', actor='acceptance')
                    record = operations.update_run(run, status='failed', state=2, start_time=operations.now(), end_time=operations.now())
                    operations.save_history(record)
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(complete, range(8)))
                backfill(); backfill()
                assert dict(load_totals())[pid] == 8
                operations.maintenance()
                with GaussDB() as db:
                    assert db.execute_query_sql('SELECT SUM(executions) FROM wfs_run_summary WHERE pid=?', params=(pid,))[0][0] == 9
                client = app.test_client()
                login = client.post('/api/user/login', json={'username':'admin','password':'mysql-test-password','portal':'admin'})
                assert login.status_code == 200, login.json
                headers = {'X-CSRF-Token':login.json['data']['csrf_token']}
                for endpoint in ['/api/taskinfo/state', '/api/taskinfo/dashboard', '/api/taskinfo/matrix', '/api/taskinfo/detail?pid='+pid, '/api/admin/users', '/api/admin/runtime', '/api/admin/database-connections']:
                    response = client.get(endpoint)
                    assert response.status_code == 200, (endpoint,response.status_code,response.json)
                for endpoint in ['/api/taskinfo/taskLogs','/api/taskinfo/systemLogs','/api/taskinfo/groups']:
                    response = client.post(endpoint, headers=headers)
                    assert response.status_code == 200, (endpoint,response.status_code,response.json)
                # Force the matrix aggregation branch (including FLOOR bins).
                from unittest.mock import patch
                from app.bootstrap import execution_matrix
                with patch.object(execution_matrix,'MAX_MARKS',1):
                    response = client.get('/api/taskinfo/matrix?date='+business_now().date().isoformat())
                    assert response.status_code == 200, response.json
                    assert response.json['data']['aggregated'], response.json
                viewer = client.post('/api/admin/users', headers=headers, json={'username':'mysql-viewer','password':'mysql-viewer-password','role':'viewer','enabled':True})
                assert viewer.status_code == 200, viewer.json
                reader = app.test_client()
                viewer_login = reader.post('/api/user/login', json={'username':'mysql-viewer','password':'mysql-viewer-password'})
                assert viewer_login.status_code == 200, viewer_login.json
                assert reader.get('/api/admin/database-connections').status_code == 403
                # Failed login counters use the same transaction policy.
                assert reader.post('/api/user/login',json={'username':'mysql-viewer','password':'wrong'}).status_code == 401
                ended = business_now()-dt.timedelta(days=100)
                with GaussDB() as db:
                    db.execute_sql('INSERT INTO wfs_run_history(id,pid,state,start_time,end_time) VALUES(?,?,2,?,?)',params=('old',pid,ended-dt.timedelta(seconds=2),ended))
                assert archive_batch(business_now()-dt.timedelta(days=90)) == 1
                assert dict(load_totals())[pid] == 9
                # Verify that the task-side factory consumes a managed business
                # profile and supports punctuation in parameter values.
                settings.save(dict(profile,id='mysql_orders'))
                from app.common.database import NewDB
                with NewDB('mysql_orders') as business:
                    assert business.execute_query_sql('SELECT %(value)s',params={'value':'中文 @ / % ?'})[0][0] == '中文 @ / % ?'
                NewDB.dispose_pool('mysql_orders')
                from sqlalchemy import event
                engine = NewDB('mysql_orders').get_engine()
                physical = []
                event.listen(engine,'connect',lambda connection,record:physical.append(1))
                for index in range(50):
                    with NewDB('mysql_orders') as business:
                        assert business.query('SELECT ?', (index,))[0][0] == index
                assert len(physical) == 1 and engine.pool.checkedout() == 0, physical
                with NewDB('mysql_orders') as business:
                    business.execute('CREATE TABLE newdb_probe(id int PRIMARY KEY) ENGINE=InnoDB')
                    try:
                        with business.transaction():
                            business.execute('INSERT INTO newdb_probe VALUES(?)',(1,))
                            raise RuntimeError('rollback acceptance')
                    except RuntimeError:
                        pass
                    assert business.query('SELECT COUNT(*) FROM newdb_probe') == [(0,)]
                print('NewDB MySQL: 50 handles reused one physical connection; transaction rollback PASSED.')
                script.write_text('import os\nassert "WFS_SECRET_KEY" not in os.environ\nassert "WFS_CONNECTIONS_KEY" not in os.environ\nfrom app.common.database import NewDB\nwith NewDB("mysql_orders") as db:\n    assert db.execute_query_sql("SELECT 42")[0][0] == 42\nprint("child business connection passed")\n', encoding='utf-8')
                assert execute_py(script, pid) == 0, operations.list_runs(pid)[0]
                print(f'MySQL {result["version"]}: schema, profiles, transactions, concurrent completion, summaries, history/archive, matrix, login, roles and business factory PASSED.')
        finally:
            with control.cursor() as cursor:
                cursor.execute(f'DROP DATABASE `{database}`')
            print('Removed only the newly created acceptance database.')


if __name__ == '__main__':
    main()
