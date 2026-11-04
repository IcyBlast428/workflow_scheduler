"""Real isolated PostgreSQL coverage for bounded log reads and cleanup gates."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_local_integration as fixture
from app.bootstrap import operations, log_storage, journal
from app.bootstrap.timebase import business_now
from app.bootstrap.database import GaussDB
from werkzeug.security import generate_password_hash


class LogStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.LocalIntegrationTests.setUpClass()
        cls.app = fixture.LocalIntegrationTests.app

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = patch.object(operations, '_directory', Path(self.tmp.name))
        self.directory.start()
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        self.context.pop()
        self.directory.stop()
        self.tmp.cleanup()

    def run_log(self, status='success', days=100, synced=True, history=True):
        identifier = operations.create_run('storage-test')
        old = (business_now()-dt.timedelta(days=days)).isoformat(' ')
        record = operations.read_run(identifier)
        record.update(status=status, created_at=old, end_time=old, db_synced=synced, history_saved=history)
        operations._persist_record(record)
        operations._write_file(record)
        path=operations.run_path(identifier,'log')
        path.write_bytes(('HEAD\n'+'汉字'*100000+'\nTAIL').encode())
        return identifier,path

    def test_tail_is_bounded_unicode_and_cursors_cover_log(self):
        identifier,path=self.run_log()
        tail=operations.read_log(identifier,'tail')
        self.assertTrue(tail['content'].endswith('TAIL'))
        self.assertNotIn('\ufffd',tail['content'])
        self.assertGreater(tail['start_offset'],0)
        self.assertEqual(tail['next_offset'],path.stat().st_size)
        self.assertLessEqual(len(tail['content'].encode()),65536)
        first=operations.read_log(identifier,0)
        self.assertTrue(first['content'].startswith('HEAD'))
        self.assertNotIn('\ufffd',operations.read_log(identifier,first['next_offset'])['content'])

    def test_cleanup_protects_running_recent_unsynced_and_history_pending(self):
        identifier,path=self.run_log()
        protected=[self.run_log(status='running'), self.run_log(days=2), self.run_log(synced=False),self.run_log(history=False)]
        plan=log_storage.preview(90)
        self.assertEqual(plan['count'],1)
        with self.assertRaises(ValueError):log_storage.execute({'token':plan['token'],'confirm':'yes'})
        with self.assertRaises(ValueError):log_storage.execute({'token':plan['token']+'x','confirm':plan['confirm']})
        result=log_storage.execute({'token':plan['token'],'confirm':plan['confirm']})
        self.assertEqual(result['count'],1)
        self.assertFalse(path.exists())
        self.assertTrue(operations.read_run(identifier)['log_cleaned_at'])
        self.assertTrue(operations.read_log(identifier,'tail')['log_unavailable'])
        self.assertTrue(all(p.exists() for _,p in protected))
        self.assertEqual(log_storage.preview(90)['count'],0)
        self.assertEqual(log_storage.execute({'token':plan['token'],'confirm':plan['confirm']})['count'],0)
        # Empty index log_path must not turn automatic expiry into unlink(directory).
        self.assertEqual(journal.expire(operations._directory,(business_now()-dt.timedelta(days=90)).isoformat(' '),500),1)

    def test_changed_files_and_external_links_are_skipped(self):
        identifier,path=self.run_log()
        plan=log_storage.preview(90)
        path.write_text('changed')
        result=log_storage.execute({'token':plan['token'],'confirm':plan['confirm']})
        self.assertEqual(result['skipped'],1)
        outside=Path(self.tmp.name)/'outside.txt'
        outside.write_text('KEEP')
        path.unlink();path.symlink_to(outside)
        self.assertEqual(log_storage.preview(90)['count'],0)
        self.assertEqual(outside.read_text(),'KEEP')

    def test_old_database_log_preview_is_bounded(self):
        identifier='f'*32
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_run_history(id,pid,taskname,state,tasklog,start_time,end_time) VALUES(?,?,?,?,?,?,?)',params=(identifier,'storage-test','huge',0,'START'+'x'*200000+'END',business_now(),business_now()))
        client=self.app.test_client()
        login=client.post('/api/user/login',json={'username':'admin','password':'test-password'})
        response=client.post('/api/taskinfo/taskLogDetail?pid=storage-test',headers={'X-CSRF-Token':login.json['data']['csrf_token']})
        self.assertEqual(response.status_code,200)
        self.assertLess(len(response.json['data']),66000)
        self.assertTrue(response.json['data'].endswith('END'))

    def test_cleanup_api_is_admin_only_and_requires_csrf(self):
        path='/api/admin/operational/log-storage'
        client=self.app.test_client()
        self.assertEqual(client.get(path).status_code,401)
        login=client.post('/api/user/login',json={'username':'admin','password':'test-password'})
        self.assertEqual(client.get(path+'?days=1').status_code,400)
        self.assertEqual(client.post(path,json={}).status_code,403)
        self.assertEqual(client.post(path,json={},headers={'X-CSRF-Token':login.json['data']['csrf_token']}).status_code,400)
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,?)',params=('log-viewer',generate_password_hash('viewer-password'),'viewer',1))
        viewer=self.app.test_client()
        viewer.post('/api/user/login',json={'username':'log-viewer','password':'viewer-password'})
        self.assertEqual(viewer.get(path).status_code,403)

    def test_plan_rechecks_terminal_state_before_unlinking(self):
        identifier,path=self.run_log()
        plan=log_storage.preview(90)
        operations.update_run(identifier,status='running')
        result=log_storage.execute({'token':plan['token'],'confirm':plan['confirm']})
        self.assertEqual(result['skipped'],1)
        self.assertTrue(path.exists())
