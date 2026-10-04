"""Real PostgreSQL/ODBC acceptance; never redirects to SQLite."""
import datetime as dt
import os
import re
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
import concurrent.futures
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEST_SCHEMA = os.environ.get('WFS_DB_ID', '').removeprefix('wfstest_')
if os.environ.get('WFS_POSTGRES_TEST') != 'true' or not re.fullmatch(r'wfs(?:_acceptance_[a-f0-9]{32})?', TEST_SCHEMA) or os.environ.get('WFS_LOCAL_DB_PATH'):
    raise SystemExit('Only the dedicated PostgreSQL test database is allowed.')
os.environ['WFS_ENABLE_SCHEDULER'] = 'false'
from werkzeug.security import generate_password_hash
os.environ['WFS_ADMIN_PASSWORD_HASH'] = generate_password_hash('pg-acceptance-password',method='scrypt')
from app import create_app
from app.bootstrap.database import GaussDB
from app.bootstrap.history import archive_batch, RUN_COLUMNS
from app.bootstrap.schedule_config import save_schedule, load_schedule
from app.bootstrap.execution import execute_py
from app.bootstrap import operations
from app.bootstrap import execution_matrix as matrix
from app.api.task import views


class PostgreSQLAcceptance(unittest.TestCase):
    def setUp(self):
        self.pid = 'pgtest_'+uuid.uuid4().hex
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        login = self.client.post('/api/user/login',json={'username':'admin','password':'pg-acceptance-password'})
        self.assertEqual(login.status_code,200)
        self.headers = {'X-CSRF-Token':login.json['data']['csrf_token']}

    def tearDown(self):
        with GaussDB() as db:
            for table in ('wfs_run_history','wfs_run_history_archive','wfs_history_rollup','wfs_job_stats','wfs_executions','wfs_task_config','wfs_config_versions','wfs_config_application','wfs_run_summary','wfs_run_totals','wfs_notifications','wfs_alert_incidents'):
                db.execute_sql(f'DELETE FROM {table} WHERE pid=?',params=(self.pid,))

    def insert(self, identifier, when, text='中文 ODBC 日志', state=0):
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)',params=(identifier,self.pid,self.pid,'test','test','test',state,text,when-dt.timedelta(seconds=2),when))

    def query(self, **params):
        response = self.client.post('/api/taskinfo/taskLogs',headers=self.headers,query_string={'taskid':self.pid,**params})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['code'],20000,response.json)
        return response.json['data']

    def test_connection_transaction_unicode_and_server_timeout(self):
        with GaussDB() as db:
            self.assertFalse(db._local_sqlite)
            row = db.execute_query_sql('SELECT current_database(),current_schema(),version()')[0]
            self.assertEqual(tuple(row[:2]),('wfstest',TEST_SCHEMA))
            self.assertTrue(row[2].startswith('PostgreSQL 18.1'))
            db.begin_transaction()
            db.execute_sql('INSERT INTO wfs_job_stats(pid,task_name) VALUES(?,?)',params=(self.pid,"中文 ' ? ;"))
            self.assertEqual(db.execute_query_sql('SELECT task_name FROM wfs_job_stats WHERE pid=?',params=(self.pid,))[0][0],"中文 ' ? ;")
            db.set_rollback()
            self.assertFalse(db.execute_query_sql('SELECT 1 FROM wfs_job_stats WHERE pid=?',params=(self.pid,)))
            db.conn.autocommit = True
            db.execute_sql('SET statement_timeout=50')
            with self.assertRaises(Exception):
                db.execute_query_sql('SELECT pg_sleep(0.2)')
            self.assertEqual(db.execute_query_sql('SELECT 1')[0][0],1)

    def test_real_row_lock_blocks_other_connection(self):
        with GaussDB() as first, GaussDB() as second:
            first.execute_sql('INSERT INTO wfs_job_stats(pid,task_name) VALUES(?,?)',params=(self.pid,self.pid))
            first.begin_transaction()
            first.execute_query_sql('SELECT pid FROM wfs_job_stats WHERE pid=? FOR UPDATE',params=(self.pid,))
            second.execute_sql('SET statement_timeout=200')
            with self.assertRaises(Exception):
                second.execute_query_sql('SELECT pid FROM wfs_job_stats WHERE pid=? FOR UPDATE',params=(self.pid,))
            first.set_rollback()
            self.assertEqual(second.execute_query_sql('SELECT pid FROM wfs_job_stats WHERE pid=? FOR UPDATE',params=(self.pid,))[0][0],self.pid)

    def test_cursor_same_second_and_incremental_marker(self):
        stamp = dt.datetime.now().replace(microsecond=0)+dt.timedelta(minutes=1)
        identifiers = [self.pid+f'-{index:03}' for index in range(17)]
        for identifier in identifiers:
            self.insert(identifier,stamp)
        result = self.query(pagesize=5)
        seen = [row['logid'] for row in result['data']]
        while result['has_more']:
            result = self.query(pagesize=5,cursor=result['next_cursor'])
            seen.extend(row['logid'] for row in result['data'])
        self.assertEqual(seen,list(reversed(identifiers)))
        self.assertEqual(views._latest_log_marker()['count'],17)

    def test_archive_roundtrip_and_mismatch_rolls_back(self):
        stamp = (dt.datetime.now()-dt.timedelta(days=120)).replace(microsecond=0)
        self.insert(self.pid,stamp,state=1)
        cutoff = dt.datetime.now()-dt.timedelta(days=90)
        self.assertEqual(archive_batch(cutoff,20),1)
        self.assertEqual(archive_batch(cutoff,20),0)
        dates = [(stamp-dt.timedelta(days=1)).isoformat(' '),(stamp+dt.timedelta(days=1)).isoformat(' ')]
        result = self.query(scope='all',**{'datetimeval[]':dates})
        self.assertEqual(len(result['data']),1)
        row = result['data'][0]
        detail = self.client.post('/api/taskinfo/taskLogDetail',headers=self.headers,query_string={'id':row['logid'],'end_time':row['datetime'],'pid':self.pid})
        self.assertEqual(detail.json['data'],'中文 ODBC 日志')
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT archived_failures FROM wfs_history_rollup WHERE pid=?',params=(self.pid,))[0][0],1)
        for suffix in ('a','b'):
            self.insert(self.pid+suffix,stamp)
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history_archive({RUN_COLUMNS}) SELECT {RUN_COLUMNS} FROM wfs_run_history WHERE id=?',params=(self.pid+'b',))
            db.execute_sql('UPDATE wfs_run_history_archive SET tasklog=? WHERE id=?',params=('mismatch',self.pid+'b'))
        with self.assertRaisesRegex(RuntimeError,'verification'):
            archive_batch(cutoff,20)
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history WHERE pid=?',params=(self.pid,))[0][0],2)

    def test_matrix_raw_and_aggregated_real_odbc(self):
        day = dt.date.today()-dt.timedelta(days=1)
        stamp = dt.datetime.combine(day,dt.time(1))
        specs = [{'pid':self.pid,'task_name':'PostgreSQL 矩阵测试','group_name':'测试'}]
        for i in range(12):
            self.insert(uuid.uuid4().hex,stamp+dt.timedelta(seconds=i),state=1 if i==3 else 0)
        with patch.object(matrix,'discover_task_specs',return_value=specs), patch.object(matrix.scheduler,'get_job',return_value=None):
            raw = self.client.get('/api/taskinfo/matrix',query_string={'date':day.isoformat()})
            self.assertEqual(raw.status_code,200,raw.json)
            self.assertEqual(raw.json['data']['total_executions'],12)
            self.assertFalse(raw.json['data']['aggregated'])
            with patch.object(matrix,'MAX_MARKS',5):
                grouped = self.client.get('/api/taskinfo/matrix',query_string={'date':day.isoformat()})
            self.assertEqual(grouped.status_code,200,grouped.json)
            result=grouped.json['data']
            self.assertTrue(result['aggregated'])
            self.assertLessEqual(len(result['records']),5)
            row=result['records'][0]
            self.assertEqual((row['count'],row['failed'],row['status']),(12,1,'failed'))
            logs=self.query(pagesize=100,**{'datetimeval[]':[row['query_start'],row['query_end']]})
            self.assertEqual(len(logs['data']),12)

    def test_schedule_identity_and_version_with_real_odbc(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary)/'main.py').write_text('print("schedule acceptance")\n')
            spec={'pid':self.pid,'group_name':'pgtest','folder_name':'fixture','task_dir':temporary,'main_file':'main.py'}
            with patch('app.bootstrap.schedule_config.resolve_task_spec',return_value=spec):
                first=save_schedule(self.pid,{'pid':self.pid,'updated_by':'test','version':0,'main_file':'main.py','schedule_type':'interval_minutes','interval_minutes':3,'enabled':False})
                self.assertEqual(first['version'],1)
                self.assertNotIn('pid',first['form'])
                with GaussDB() as db:
                    stored=json.loads(db.execute_query_sql('SELECT schedule_json FROM wfs_task_config WHERE pid=?',params=(self.pid,))[0][0])
                    stored.update(pid='previous-task',updated_by='legacy')
                    db.execute_sql('UPDATE wfs_task_config SET schedule_json=? WHERE pid=?',params=(json.dumps(stored),self.pid))
                loaded=load_schedule(self.pid)
                self.assertNotIn('pid',loaded['form'])
                self.assertEqual(loaded['form']['version'],1)
                second=save_schedule(self.pid,dict(loaded['form'],interval_minutes=5))
                self.assertEqual(second['version'],2)
                with self.assertRaisesRegex(RuntimeError,'配置已被其他操作修改'):
                    save_schedule(self.pid,dict(first['form'],interval_minutes=6))
                self.assertEqual(load_schedule(self.pid)['form']['interval_minutes'],5)

    def test_actual_worker_result_is_written_once(self):
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_job_stats(pid,task_name) VALUES(?,?)',params=(self.pid,self.pid))
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary)/'main.py'
            script.write_text('print("PostgreSQL worker 中文成功")\n',encoding='utf-8')
            self.assertEqual(execute_py(script,self.pid),0)
        record = operations.list_runs(self.pid)[0]
        self.assertEqual(record['status'],'success')
        operations.save_history(record)
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT tasklog,state FROM wfs_run_history WHERE id=?',params=(record['run_id'],))
            self.assertEqual(len(rows),1)
            self.assertIn('中文成功',rows[0][0])
            self.assertEqual(rows[0][1],0)

    def test_parallel_completion_summaries_and_idempotence(self):
        def complete(index):
            identifier=operations.create_run(self.pid,self.pid)
            record=operations.update_run(identifier,status='failed' if index%2 else 'success',state=index%2,end_time=operations.now())
            operations.save_history(record)
            operations.save_history(operations.read_run(identifier))
            self.assertTrue(operations.read_run(identifier)['history_saved'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(complete,range(12)))
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT SUM(executions) FROM wfs_run_summary WHERE pid=?',params=(self.pid,))[0][0],12)
            self.assertEqual(db.execute_query_sql('SELECT failures FROM wfs_run_totals WHERE pid=?',params=(self.pid,))[0][0],6)


    def test_backfill_skips_locked_history_and_counts_each_record_once(self):
        from app.bootstrap import run_summary
        stamp=dt.datetime.now().replace(microsecond=0)
        identifiers=[uuid.uuid4().hex for _ in range(3)]
        for identifier in identifiers: self.insert(identifier,stamp,state=1)
        with GaussDB() as locked:
            locked.begin_transaction()
            try:
                locked.execute_query_sql('SELECT id FROM wfs_run_history WHERE id=? FOR UPDATE',params=(identifiers[0],))
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    self.assertGreaterEqual(pool.submit(run_summary.backfill,100).result(timeout=5),2)
            finally: locked.set_commit()
        run_summary.backfill(100);run_summary.backfill(100)
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT SUM(executions) FROM wfs_run_summary WHERE pid=?',params=(self.pid,))[0][0],3)
            self.assertEqual(db.execute_query_sql('SELECT failures FROM wfs_run_totals WHERE pid=?',params=(self.pid,))[0][0],3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
