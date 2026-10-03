"""Failure recovery, configuration concurrency and permission acceptance."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_local_integration as shared
from app import create_app
from app.bootstrap import operations as ops
from app.bootstrap.database import GaussDB
from app.bootstrap.execution import execute_py, _resource_limit
from app.bootstrap.global_vars import RunningState
from app.bootstrap.schedule_config import load_schedule, save_schedule
from app.settings import AUTH_ADMIN_PASSWORD_HASH
from scripts import migrate


class OperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.testing = True

    def client(self, username='admin', address='127.0.0.2'):
        client = self.app.test_client()
        response = client.post('/api/user/login', json={'username':username,'password':'test-password'}, environ_overrides={'REMOTE_ADDR':address})
        self.assertEqual(response.status_code, 200)
        return client, {'X-CSRF-Token':response.json['data']['csrf_token']}

    def test_completion_database_failure_recovers_exactly_once(self):
        pid = 'durable-recovery'
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_job_stats(pid,task_name,failed_times) VALUES(?,?,0)', params=(pid,pid))
        script = Path(shared._tmp.name) / 'durable.py'
        script.write_text('print("durable result")\n', encoding='utf-8')
        with patch.object(ops, 'GaussDB', side_effect=RuntimeError('database offline')):
            with self.assertLogs(ops.logger, level='ERROR'):
                self.assertEqual(execute_py(script, pid), 0)
        record = ops.list_runs(pid)[0]
        self.assertFalse(record['history_saved'])
        ops.maintenance()
        ops.maintenance()
        self.assertTrue(ops.read_run(record['run_id'])['history_saved'])
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history WHERE id=?', params=(record['run_id'],))[0][0], 1)
            self.assertEqual(db.execute_query_sql('SELECT failed_times FROM wfs_job_stats WHERE pid=?', params=(pid,))[0][0], 0)

    @unittest.skipIf(os.name == 'nt', 'Linux orphan process recovery')
    def test_restart_marks_interrupted_and_cleans_verified_orphan(self):
        script = Path(shared._tmp.name) / 'orphan.py'
        script.write_text('import time\ntime.sleep(60)\n')
        worker = Path(ops.__file__).with_name('worker.py')
        process = subprocess.Popen([sys.executable, str(worker), str(script)], start_new_session=True)
        run_id = ops.create_run('orphan-recovery')
        try:
            identity = Path(f'/proc/{process.pid}/stat').read_text().split()[21]
            ops.update_run(run_id, status='running', process_id=process.pid, process_identity=identity)
            ops.maintenance(recover=True)
            self.assertEqual(ops.read_run(run_id)['status'], 'interrupted')
            self.assertEqual(process.wait(timeout=5), -9)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()

    def test_utf8_log_chunk_boundary_and_download(self):
        run_id = ops.create_run('utf8-output')
        content = '中' * 30000
        ops.run_path(run_id,'log').write_bytes(content.encode())
        ops.update_run(run_id, status='success',state=0,end_time=ops.now())
        first = ops.read_log(run_id)
        second = ops.read_log(run_id, first['next_offset'])
        self.assertTrue(first['has_more'])
        self.assertEqual(first['content'] + second['content'], content)
        client, _ = self.client()
        download = client.get('/api/taskinfo/run-download', query_string={'run_id':run_id})
        self.assertEqual(download.data.decode(), content)
        download.close()
        self.assertEqual(client.get('/api/taskinfo/run',query_string={'run_id':'../../etc/passwd'}).status_code, 404)

    def test_full_log_cap_keeps_draining_process(self):
        script = Path(shared._tmp.name) / 'capped.py'
        script.write_text('print("x" * 1000000)\n')
        with patch.dict(os.environ, {'WFS_RUN_LOG_MAX_BYTES':'1024'}):
            self.assertEqual(execute_py(script,'log-cap',timeout_seconds=10), 0)
        record = ops.list_runs('log-cap')[0]
        self.assertTrue(record['log_truncated'])
        self.assertEqual(ops.run_path(record['run_id'],'log').stat().st_size, 1024)

    def test_global_concurrency_and_resource_ceiling(self):
        state = RunningState()
        with patch.dict(os.environ, {'WFS_MAX_ACTIVE_RUNS':'2','WFS_TASK_MEMORY_MB':'64'}):
            self.assertIsNotNone(state.claim('a'))
            self.assertIsNotNone(state.claim('b'))
            self.assertIsNone(state.claim('c'))
            self.assertEqual(_resource_limit({'memory_mb':0},'memory_mb','WFS_TASK_MEMORY_MB',0), 64)
            self.assertEqual(_resource_limit({'memory_mb':128},'memory_mb','WFS_TASK_MEMORY_MB',0), 64)

    def test_journal_failure_does_not_leak_execution_capacity(self):
        from app.bootstrap.global_vars import runnings
        from app.bootstrap import core
        with patch('app.bootstrap.execution.create_run',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                execute_py('unused.py','disk-full')
        self.assertFalse(runnings.is_running('disk-full'))
        with patch.object(core,'create_run',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                core.call_task_once('testJob__test_job1')
        self.assertFalse(runnings.is_running('testJob__test_job1'))

    @unittest.skipIf(os.name == 'nt', 'Linux resource limits')
    def test_worker_memory_limit_is_enforced(self):
        script = Path(shared._tmp.name) / 'memory.py'
        script.write_text('value = bytearray(512 * 1024 * 1024)\n')
        self.assertNotEqual(execute_py(script,'memory-limit',timeout_seconds=10,limits={'memory_mb':64}), 0)
        record = ops.list_runs('memory-limit')[0]
        self.assertIn('MemoryError', ops.read_log(record['run_id'])['content'])

    def test_version_conflict_history_and_restore(self):
        pid = 'testJob__test_job1'
        first = save_schedule(pid, {'schedule_type':'every_hour','enabled':False,'main_file':'main.py','owner':'original'})
        second = save_schedule(pid, dict(first['form'], owner='edited'))
        with self.assertRaises(RuntimeError):
            save_schedule(pid, dict(first['form'], owner='stale'))
        self.assertEqual(load_schedule(pid)['form']['owner'],'edited')
        client, headers = self.client()
        with patch('app.bootstrap.core.aps_start'):
            response = client.post('/api/taskinfo/restore',json={'pid':pid,'restore_version':first['version'],'version':second['version']},headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['data']['form']['owner'],'original')
        self.assertGreater(response.json['data']['version'],second['version'])
        detail = client.get('/api/taskinfo/detail',query_string={'pid':pid})
        self.assertEqual(detail.status_code,200)
        self.assertGreater(len(detail.json['data']['versions']),1)

    def test_schedule_json_does_not_leak_request_identity_into_form(self):
        pid='testJob__test_job1'
        first=save_schedule(pid,{'pid':pid,'updated_by':'admin','schedule_type':'every_hour','enabled':False,'main_file':'main.py'})
        self.assertNotIn('pid',first['form'])
        self.assertNotIn('updated_by',first['form'])
        with GaussDB() as db:
            stored=json.loads(db.execute_query_sql('SELECT schedule_json FROM wfs_task_config WHERE pid=?',params=(pid,))[0][0])
            self.assertNotIn('pid',stored)
            # Existing deployments can still have these fields in historical JSON.
            stored.update(pid='another-task',updated_by='old-client')
            db.execute_sql('UPDATE wfs_task_config SET schedule_json=? WHERE pid=?',params=(json.dumps(stored),pid))
        loaded=load_schedule(pid)
        self.assertNotIn('pid',loaded['form'])
        self.assertNotIn('updated_by',loaded['form'])
        self.assertEqual(loaded['form']['version'],first['version'])
        second=save_schedule(pid,dict(loaded['form'],task_name='correct task'))
        self.assertEqual(second['version'],first['version']+1)

    def test_saved_configuration_reports_failed_application(self):
        pid = 'testJob__test_job1'
        client, headers = self.client()
        form = dict(load_schedule(pid)['form'], pid=pid)
        with patch('app.bootstrap.core.aps_start',side_effect=RuntimeError('registration offline')):
            response = client.put('/api/taskinfo/schedule',json=form,headers=headers)
        self.assertEqual(response.json['code'],20000)
        self.assertEqual(response.json['data']['application']['status'],'failed')
        self.assertEqual(load_schedule(pid)['application']['status'],'failed')

    def test_refresh_registers_saved_version_and_preserves_other_statistics(self):
        from app.bootstrap import core
        pid = 'testJob__test_job1'
        saved = save_schedule(pid,dict(load_schedule(pid)['form'],enabled=False))
        with GaussDB() as db:
            before = db.execute_query_sql('SELECT COUNT(*) FROM wfs_job_stats')[0][0]
        core.aps_start(task_pid=pid,action='refresh')
        applied = load_schedule(pid)['application']
        self.assertEqual(applied['status'],'applied')
        self.assertEqual(applied['version'],saved['version'])
        with GaussDB() as db:
            self.assertGreaterEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_job_stats')[0][0],before)

    def test_role_policy_and_disabled_account(self):
        with GaussDB() as db:
            for name, role in [('accept-viewer','viewer'),('accept-operator','operator')]:
                db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)',params=(name,AUTH_ADMIN_PASSWORD_HASH,role))
        viewer, headers = self.client('accept-viewer')
        self.assertEqual(viewer.get('/api/taskinfo/state').status_code,200)
        self.assertEqual(viewer.get('/api/admin/users').status_code,403)
        self.assertEqual(viewer.post('/api/taskinfo/editTask',headers=headers).status_code,403)
        operator, operator_headers = self.client('accept-operator')
        self.assertEqual(operator.put('/api/taskinfo/schedule',json={},headers=operator_headers).status_code,403)
        self.assertEqual(operator.post('/api/taskinfo/groups',headers=operator_headers).status_code,200)
        with GaussDB() as db:
            db.execute_sql('UPDATE wfs_users SET enabled=0 WHERE username=?', params=('accept-viewer',))
        self.assertEqual(viewer.get('/api/user/info').status_code,401)
        self.assertEqual(viewer.post('/api/taskinfo/editTask',headers=headers).status_code,401)

    def test_resource_metrics_restore_and_incremental_cursor(self):
        from app.bootstrap.system_metrics import _CpuMonitor
        path = Path(shared._tmp.name)/'test-metrics.json'
        monitor = _CpuMonitor()
        monitor._path = path
        with patch('app.bootstrap.system_metrics._read_cpu_times',side_effect=[(10,100),(15,200)]):
            monitor._append_sample()
            monitor._append_sample()
        restored = _CpuMonitor()
        restored._path = path
        with patch('app.bootstrap.system_metrics.threading.Thread.start'):
            restored.start()
        initial = restored.snapshot()
        self.assertEqual(initial['current'],95.0)
        incremental = restored.snapshot(after=initial['cursor'])
        self.assertEqual(incremental['samples'],[])
        self.assertEqual(incremental['current'],95.0)

    def test_shared_login_limit_and_readiness_failure(self):
        client = self.app.test_client()
        for _ in range(5):
            response = client.post('/api/user/login',json={'username':'invalid-limit','password':'wrong'},environ_overrides={'REMOTE_ADDR':'127.0.0.99'})
            self.assertEqual(response.status_code,401)
        response = self.app.test_client().post('/api/user/login',json={'username':'invalid-limit','password':'wrong'},environ_overrides={'REMOTE_ADDR':'127.0.0.99'})
        self.assertEqual(response.status_code,429)
        with patch('app.bootstrap.database.GaussDB',side_effect=RuntimeError('database offline')):
            self.assertEqual(client.get('/api/user/ready').status_code,503)
            self.assertEqual(client.get('/api/user/health').status_code,200)

    def test_migration_checksum_and_sql_literals(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '010_acceptance.sql'
            path.write_text("CREATE TABLE acceptance_literals(value text);\nINSERT INTO acceptance_literals VALUES('one;two'); -- comment\n")
            self.assertEqual(len(migrate.statements(path)),2)
            try:
                with patch.object(migrate,'MIGRATIONS',Path(temporary)):
                    migrate.main()
                    path.write_text(path.read_text() + '\n-- tampered\n')
                    with self.assertRaisesRegex(RuntimeError,'Applied migration changed'):
                        migrate.main()
                with GaussDB() as db:
                    self.assertEqual(db.execute_query_sql('SELECT value FROM acceptance_literals')[0][0],'one;two')
            finally:
                with GaussDB() as db:
                    db.execute_sql('DROP TABLE IF EXISTS acceptance_literals')
                    db.execute_sql('DELETE FROM wfs_schema_migrations WHERE name=?',params=(path.name,))

    @unittest.skipIf(os.name == 'nt', 'Linux backup lease')
    def test_backup_integrity_and_refusal_when_scheduler_active(self):
        import fcntl
        import zipfile
        from scripts.backup_local import backup
        data = Path(os.environ['WFS_DATA_DIR'])
        output = Path(shared._tmp.name) / 'backup.zip'
        with (data / '.scheduler.lock').open('a') as lease:
            fcntl.flock(lease,fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                backup(os.environ['WFS_LOCAL_DB_PATH'],data,output)
        backup(os.environ['WFS_LOCAL_DB_PATH'],data,output)
        with zipfile.ZipFile(output) as archive:
            self.assertIn('database.sqlite3',archive.namelist())
            self.assertIsNone(archive.testzip())
