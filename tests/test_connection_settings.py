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
        self.form = {'id': 'mysql_orders', 'host': 'cluster.example.com', 'port': 3306,
                     'database': 'orders', 'user': 'wfs', 'password': 'test-secret-password',
                     'tls': 'disabled', 'revision': 0}

    def ciphertext(self):
        with settings._store() as db:
            return db.execute('SELECT payload FROM profiles WHERE id=?',('mysql_orders',)).fetchone()[0]

    def test_platform_profile_is_not_editable(self):
        with self.assertRaises(ValueError):settings.validate(dict(self.form,id='platform'))

    def test_encrypted_storage_masking_reuse_and_concurrent_revision(self):
        validated = settings.validate(self.form)
        saved = settings.save(validated)
        self.assertNotIn('password', saved)
        self.assertTrue(saved['password_set'])
        self.assertNotIn(b'test-secret-password', self.ciphertext())
        self.assertNotIn(b'cluster.example.com', self.ciphertext())
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




    def test_validation_tls_and_invalid_profiles(self):
        for changes in ({'id':'../../secret'}, {'port': 0}, {'host': 'mysql://user:pass@host'},
                        {'password': 123}, {'tls': 'verify_identity', 'ssl_ca': ''}):
            with self.assertRaises(ValueError):
                settings.validate(dict(self.form, **changes))
        certificate = Path(self.directory.name) / 'ca.pem'
        certificate.write_text('certificate placeholder')
        profile = settings.validate(dict(self.form, tls='verify_identity', ssl_ca=str(certificate)))
        from app.common.db.mysql import MySQLAdapter
        options=MySQLAdapter(profile).connection_options()
        self.assertTrue(options['ssl_verify_identity'])
        self.assertTrue(options['ssl_verify_cert'])
        self.assertFalse(options['local_infile'])

    def test_admin_only_connection_api_csrf_and_failed_save(self):
        app = create_app()
        client = app.test_client()
        endpoint = '/api/admin/database-connections'
        self.assertEqual(client.get(endpoint).status_code, 401)
        response = client.post('/api/user/login', json={'username':'admin','password':'test-password','portal':'admin'})
        headers = {'X-CSRF-Token': response.json['data']['csrf_token']}
        self.assertEqual(client.post(endpoint+'/save', json=self.form).status_code, 403)
        with patch.object(settings, 'probe_business', return_value={'connected':True,'ready':False,'missing':['wfs_users']}):
            self.assertEqual(client.post(endpoint+'/save', json=dict(self.form,id='platform'), headers=headers).status_code, 400)
        self.assertEqual(settings.profiles(), {})
        with patch.object(settings, 'probe_business', return_value={'connected':True,'ready':True,'missing':[]}):
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
