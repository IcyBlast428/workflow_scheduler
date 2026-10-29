"""Admission, duplicate requests and task connection authorization regressions."""
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_local_integration as shared
from app.bootstrap import admission, connection_settings

class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'WFS_DATA_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)

    def test_concurrent_request_replay_and_cross_task_conflict(self):
        calls=[]
        def submit(): calls.append(1);return 'abc123'
        def request():return admission.manual_request('admin','task','key_123456789012345',submit)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(lambda _:request(),range(12)))
        self.assertEqual(len(calls),1)
        self.assertEqual({r['run_id'] for r in results},{'abc123'})
        self.assertEqual(sum(not r['replayed'] for r in results),1)
        with self.assertRaises(RuntimeError): admission.manual_request('admin','other','key_123456789012345',submit)
        # Original successful receipt remains retrievable even during maintenance.
        admission.set_maintenance(True,0,'upgrade','admin')
        self.assertEqual(request()['run_id'],'abc123')

    def test_unknown_request_is_not_automatically_retried(self):
        def uncertain(): raise RuntimeError('injected failure after enqueue')
        with self.assertRaises(RuntimeError): admission.manual_request('admin','task','key_123456789012345',uncertain)
        with self.assertRaises(RuntimeError): admission.manual_request('admin','task','key_123456789012345',lambda:self.fail('duplicate'))
        with admission.store() as db: self.assertEqual(db.execute('SELECT status FROM receipts').fetchone()[0],'unknown')

    def test_maintenance_persists_and_revision_conflicts(self):
        state=admission.set_maintenance(True,0,'upgrade','admin')
        self.assertTrue(admission.maintenance()['enabled'])
        with self.assertRaises(RuntimeError): admission.ensure_open()
        with self.assertRaises(RuntimeError): admission.set_maintenance(False,0,'','other')
        with self.assertRaises(RuntimeError): admission.manual_request('admin','task','key_123456789012345',lambda:self.fail('started'))
        admission.set_maintenance(False,state['revision'],'','admin');admission.ensure_open()

    def test_scheduled_task_skipped_without_process_or_reservation_leak(self):
        from app.bootstrap.execution import execute_py
        from app.bootstrap.global_vars import runnings
        from app.bootstrap.operations import list_runs
        admission.set_maintenance(True,0,'upgrade','admin')
        with patch('app.bootstrap.execution.subprocess.Popen') as start:
            execute_py('/missing/entry.py','maintenance_test')
            start.assert_not_called()
        self.assertFalse(runnings.is_running('maintenance_test'))
        record=list_runs('maintenance_test')[0]
        self.assertEqual(record['status'],'skipped');self.assertIn('维护模式',record['reason'])

    def test_grants_limit_snapshot_and_deny_legacy_fallback(self):
        profiles={'orders':dict(id='orders',password='one'), 'billing':dict(id='billing',password='two')}
        with patch.object(connection_settings,'profiles',return_value=profiles),patch.object(connection_settings,'business_profile',side_effect=lambda i:profiles.get(i)):
            self.assertIsNone(admission.connection_environment('old_task'))
            admission.save_grant('task',dict(mode='restricted',connections=['orders'],revision=0),'admin')
            snapshot=admission.connection_environment('task')
            self.assertEqual(list(json.loads(snapshot)),['orders'])
            with self.assertRaises(ValueError): admission.save_grant('task',dict(mode='restricted',connections=['platform'],revision=1),'admin')
            with self.assertRaises(RuntimeError): admission.save_grant('task',dict(mode='restricted',connections=[],revision=0),'admin')
        with patch.dict(os.environ,{'WFS_TASK_CONNECTIONS_JSON':snapshot}):
            self.assertEqual(connection_settings.business_profile('orders')['password'],'one')
            from app.common.db.config import load_database_config
            with self.assertRaises(PermissionError):load_database_config('billing')
            with self.assertRaises(PermissionError):load_database_config('legacy_ini')
            with self.assertRaises(PermissionError):connection_settings.business_profile('platform')

    def test_backup_contains_admission_and_grants(self):
        import zipfile
        from scripts.backup_files import add_connection_settings
        admission.set_maintenance(True,0,'upgrade','admin')
        with tempfile.TemporaryDirectory() as temp,zipfile.ZipFile(Path(self.temp.name)/'backup.zip','w') as archive:
            self.assertTrue(add_connection_settings(archive,self.temp.name,temp,'admission.sqlite3'))
            self.assertIn('data/admission.sqlite3',archive.namelist())

    def test_routes_require_admin_and_csrf(self):
        from app import create_app
        from app.bootstrap.permissions import allowed
        app=create_app();client=app.test_client()
        for route in ('/api/admin/admission','/api/admin/task-connections?pid=testJob__test_job1'):
            self.assertEqual(client.get(route).status_code,401)
            self.assertFalse(allowed(route.split('?')[0],'GET','viewer'))
            self.assertFalse(allowed(route.split('?')[0],'POST','operator'))
        client.post('/api/user/login',json={'username':'admin','password':'test-password'})
        self.assertEqual(client.post('/api/admin/admission',json={'enabled':True,'revision':0}).status_code,403)
        self.assertEqual(client.get('/api/admin/admission').status_code,200)

    def test_final_process_gate_catches_maintenance_started_during_preparation(self):
        from app.bootstrap.execution import execute_py
        from app.bootstrap.operations import list_runs
        script=Path(self.temp.name)/'entry.py';script.write_text('print("must not run")')
        def preparing(*args):
            admission.set_maintenance(True,0,'upgrade','admin')
            return '{}'
        with patch.object(admission,'connection_environment',side_effect=preparing),patch('app.bootstrap.execution.execution_version',return_value={}),patch('app.bootstrap.execution.subprocess.Popen') as start:
            execute_py(script,'maintenance_race_test')
            start.assert_not_called()
        self.assertEqual(list_runs('maintenance_race_test')[0]['status'],'skipped')

    def test_restricted_worker_receives_only_scoped_connections_and_runtime_environment(self):
        from app.bootstrap.execution import execute_py
        from app.bootstrap.operations import list_runs,read_log
        script=Path(self.temp.name)/'scoped.py'
        script.write_text("import os\nfrom app.common.db.config import load_database_config\nassert load_database_config('orders')['password']=='one'\nfor key in ('WFS_SECRET_KEY','WFS_TASK_DATABASE_KEY','WFS_NACOS_PASSWORD','UNRELATED_TEST_SECRET'):\n    assert key not in os.environ,key\nfor identifier in ('billing','legacy_ini','platform'):\n    try: load_database_config(identifier)\n    except PermissionError: pass\n    else: raise AssertionError(identifier)\nprint('SCOPED_CONNECTION_OK')\n")
        with patch.dict(os.environ,{'WFS_NACOS_PASSWORD':'hidden','UNRELATED_TEST_SECRET':'hidden'}),patch.object(admission,'connection_environment',return_value=json.dumps({'orders':{'id':'orders','password':'one'}})):
            execute_py(script,'scoped_worker_test',timeout_seconds=15)
        record=list_runs('scoped_worker_test')[0]
        self.assertEqual(record['status'],'success',record['reason'])
        self.assertIn('SCOPED_CONNECTION_OK',read_log(record['run_id'])['content'])
