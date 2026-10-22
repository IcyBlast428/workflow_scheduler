"""Credential storage, role boundaries and MySQL parameter compatibility."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import test_local_integration as shared
from app import create_app
from app.bootstrap import connection_settings as settings
from app.bootstrap.database import GaussDB
from app.bootstrap.permissions import allowed
from app.settings import AUTH_ADMIN_PASSWORD_HASH


class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'connections.sqlite3'
        self.path_patch = patch.object(settings, '_path', return_value=self.path)
        self.path_mock = self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.form = {'id': 'mysql_orders', 'host': 'cluster.example.com', 'port': 3306,
                     'database': 'orders', 'user': 'wfs', 'password': 'test-secret-password',
                     'tls': 'disabled', 'revision': 0}

    def test_encrypted_storage_masking_reuse_and_concurrent_revision(self):
        validated = settings.validate(self.form)
        saved = settings.save(validated)
        self.assertNotIn('password', saved)
        self.assertTrue(saved['password_set'])
        self.assertNotIn(b'test-secret-password', self.path.read_bytes())
        self.assertNotIn(b'cluster.example.com', self.path.read_bytes())
        next_form = dict(saved, password='')
        self.assertEqual(settings.validate(next_form)['password'], self.form['password'])
        with self.assertRaises(RuntimeError):
            settings.save(validated)
        settings.save(settings.validate(next_form))
        from app.common.db.config import load_database_config
        self.assertEqual(load_database_config('mysql_orders')['password'], self.form['password'])
        with patch.dict(os.environ, {'WFS_CONNECTIONS_KEY': 'wrong-key'}):
            with self.assertRaisesRegex(ValueError, '无法解密'):
                settings.profiles()
        self.assertEqual(settings.profiles()['mysql_orders']['revision'], 2)

    def test_platform_selection_is_frozen_until_new_process(self):
        self.assertIsNone(settings.active_platform())
        settings.save(settings.validate(dict(self.form, id='platform')))
        self.assertIsNone(settings.active_platform())
        settings._active.pop(str(self.path.resolve()))
        # A newly spawned task must still use the old profile. App startup is
        # the only place that activates a pending edit.
        self.assertIsNone(settings.active_platform())
        settings.activate_at_app_start()
        settings._active.pop(str(self.path.resolve()))
        self.assertEqual(settings.active_platform()['database'], 'orders')
        with patch.dict(os.environ, {'WFS_IGNORE_MANAGED_DATABASE': 'true'}):
            self.assertIsNone(settings.active_platform())

    def test_task_key_opens_business_profiles_without_exposing_platform_or_session_key(self):
        settings.save(settings.validate(self.form))
        settings.save(settings.validate(dict(self.form, id='platform')))
        task_key = settings.task_database_key()
        with patch.dict(os.environ, {'WFS_TASK_DATABASE_KEY':task_key}, clear=True):
            self.assertEqual(settings.business_profile('mysql_orders')['password'], self.form['password'])
            self.assertIsNone(settings.business_profile('platform'))
            with self.assertRaises(ValueError):
                settings.profiles()

    def test_backup_restores_encrypted_profiles_with_original_key(self):
        import json
        import zipfile
        from scripts.backup_files import add_connection_settings
        from scripts.restore_local import restore
        # Match the real configuration filename used by the backup helpers.
        self.path = Path(self.directory.name) / 'database-connections.sqlite3'
        self.path_mock.return_value = self.path
        settings.save(settings.validate(self.form))
        archive_path = Path(self.directory.name) / 'backup.zip'
        temporary = Path(self.directory.name) / 'snapshot'
        temporary.mkdir()
        with zipfile.ZipFile(archive_path, 'w') as archive:
            self.assertTrue(add_connection_settings(archive, self.path.parent, temporary))
            archive.writestr('manifest.json', json.dumps({'format':2}))
        target = restore(archive_path, Path(self.directory.name) / 'restored')
        with patch.object(settings, '_path', return_value=target/'data/database-connections.sqlite3'):
            self.assertEqual(settings.business_profile('mysql_orders')['password'], self.form['password'])

    def test_validation_tls_and_invalid_profiles(self):
        for changes in ({'id':'../../secret'}, {'port': 0}, {'host': 'mysql://user:pass@host'},
                        {'password': 123}, {'tls': 'verify_identity', 'ssl_ca': ''}):
            with self.assertRaises(ValueError):
                settings.validate(dict(self.form, **changes))
        certificate = Path(self.directory.name) / 'ca.pem'
        certificate.write_text('certificate placeholder')
        profile = settings.validate(dict(self.form, tls='verify_identity', ssl_ca=str(certificate)))
        with patch('pymysql.connect', return_value=MagicMock()) as connect:
            settings.connect_mysql(profile)
        self.assertTrue(connect.call_args.kwargs['ssl_verify_identity'])
        self.assertTrue(connect.call_args.kwargs['ssl_verify_cert'])
        self.assertFalse(connect.call_args.kwargs['local_infile'])

    def test_mysql_parameters_literals_comments_and_percent(self):
        db = GaussDB.__new__(GaussDB)
        db._mysql, db._local_sqlite, db._in_transaction = True, False, True
        query = "SELECT '?', `odd?`, ? FROM t WHERE name LIKE '%x%' /* ? % */ -- ? %\nAND id=?"
        self.assertEqual(db._parameters(query), "SELECT '?', `odd?`, %s FROM t WHERE name LIKE '%%x%%' /* ? %% */ -- ? %%\nAND id=%s")
        self.assertIn('TIMESTAMPDIFF(SECOND,start_time,end_time)', db._sql('SELECT extract(epoch from (end_time - start_time))::bigint'))
        self.assertEqual(db._sql('LOCK TABLE wfs_users IN EXCLUSIVE MODE'), 'DO 0')
        db._in_transaction = False
        with self.assertRaises(RuntimeError):
            db._sql('LOCK TABLE wfs_users IN EXCLUSIVE MODE')

    def test_mysql_transaction_uses_row_lock_and_rolls_back_on_close(self):
        db = GaussDB.__new__(GaussDB)
        db._mysql, db._local_sqlite, db._in_transaction = True, False, False
        db.conn, db.cursor = MagicMock(), MagicMock()
        db.cursor.fetchone.return_value = (1,)
        db.begin_transaction()
        self.assertIn('FOR UPDATE', db.cursor.execute.call_args.args[0])
        db.close()
        db.conn.rollback.assert_called_once()
        db.conn.close.assert_called_once()

    def test_driver_errors_do_not_expose_secrets(self):
        import pymysql
        with patch.object(settings, 'connect_mysql', side_effect=pymysql.OperationalError(1045, 'password=test-secret-password')):
            with self.assertRaises(ValueError) as error:
                settings.probe(settings.validate(dict(self.form, id='platform')))
        self.assertNotIn('test-secret-password', str(error.exception))
        self.assertIn('1045', str(error.exception))

    def test_admin_only_connection_api_csrf_and_failed_save(self):
        app = create_app()
        client = app.test_client()
        endpoint = '/api/admin/database-connections'
        self.assertEqual(client.get(endpoint).status_code, 401)
        response = client.post('/api/user/login', json={'username':'admin','password':'test-password','portal':'admin'})
        headers = {'X-CSRF-Token': response.json['data']['csrf_token']}
        self.assertEqual(client.post(endpoint+'/save', json=self.form).status_code, 403)
        with patch.object(settings, 'probe', return_value={'connected':True,'ready':False,'missing':['wfs_users']}):
            self.assertEqual(client.post(endpoint+'/save', json=dict(self.form,id='platform'), headers=headers).status_code, 400)
        self.assertEqual(settings.profiles(), {})
        with patch.object(settings, 'probe', return_value={'connected':True,'ready':True,'missing':[]}):
            saved = client.post(endpoint+'/save', json=self.form, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.json)
        listing = client.get(endpoint)
        self.assertNotIn(self.form['password'], listing.get_data(as_text=True))
        self.assertNotIn('password', listing.json['data']['profiles'][0])

    def test_unified_login_keeps_viewers_and_legacy_operators_read_only(self):
        app = create_app()
        with GaussDB() as db:
            for name, role in [('portal-viewer', 'viewer'), ('portal-operator','operator')]:
                db.execute_sql('DELETE FROM wfs_users WHERE username=?', params=(name,))
                db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)', params=(name,AUTH_ADMIN_PASSWORD_HASH,role))
        for username in ['portal-viewer', 'portal-operator']:
            client = app.test_client()
            denied = client.post('/api/user/login', json={'username':username,'password':'test-password','portal':'admin'})
            self.assertEqual(denied.status_code, 200)
            login = client.post('/api/user/login', json={'username':username,'password':'test-password','portal':'viewer'})
            headers = {'X-CSRF-Token': login.json['data']['csrf_token']}
            self.assertEqual(client.get('/api/taskinfo/state').status_code, 200)
            for path in ['/api/admin/database-connections', '/api/admin/users', '/api/taskinfo/source', '/api/taskinfo/flow', '/api/taskinfo/packages', '/api/taskinfo/dashboard']:
                self.assertEqual(client.get(path).status_code, 403, path)
            for path in ['/api/taskinfo/call_task', '/api/taskinfo/batch', '/api/taskinfo/editTask', '/api/admin/database-connections/save']:
                self.assertEqual(client.post(path, json={}, headers=headers).status_code, 403, path)
        self.assertFalse(allowed('/api/new-future-api', 'GET', 'viewer'))
        self.assertFalse(allowed('/api/taskinfo/state', 'GET', 'unknown'))


if __name__ == '__main__':
    unittest.main()
