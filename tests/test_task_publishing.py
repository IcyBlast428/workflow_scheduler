import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_local_integration
from app import create_app
from app.bootstrap import task_publishing as settings
from scripts.backup_files import add_connection_settings


class TaskPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'WFS_DATA_DIR':str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_examples_seed_edit_create_conflict_and_persistence(self):
        examples = settings.examples()
        self.assertEqual(len(examples), 6)
        hello = next(item for item in examples if item['id'] == 'hello')
        self.assertIn('sum(range(1, 101))', hello['code'])
        saved = settings.save_example(dict(hello, code='print("new")'))
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(settings.examples()[0]['code'], 'print("new")')
        with self.assertRaises(settings.PublishingError) as error:
            settings.save_example(hello)
        self.assertEqual(error.exception.status, 409)
        new = settings.save_example(dict(title='SQL 示例',filename='query.sql',language='sql',
                                        code='SELECT 1;',revision=0))
        self.assertEqual(len(settings.examples()), 7)
        self.assertEqual(settings.examples()[-1]['id'], new['id'])
        self.assertIn('5050', (Path(__file__).resolve().parents[1]/'examples/tasks/catalog.json').read_text(encoding='utf-8'))
        with self.assertRaises(settings.PublishingError):
            settings.save_example(dict(new, filename='../../x'))
        with self.assertRaises(settings.PublishingError):
            settings.save_example(dict(new, id='', revision=0))

    def test_repository_normalization_secret_retention_encryption_and_backup(self):
        original = dict(mode='nexus',index_url='http://nexus.immp.icbc/repository/pypi-hosted',
                        username='repo-reader',password='private-test-password',revision=0)
        saved = settings.save_repository(original)
        self.assertEqual(saved['index_url'], settings.DEFAULT_INDEX)
        self.assertNotIn('password',saved)
        self.assertTrue(saved['password_set'])
        saved = settings.save_repository(dict(saved, password=''))
        self.assertEqual(settings.repository()['password'], original['password'])
        with self.assertRaises(settings.PublishingError):
            settings.save_repository(original)
        storage = self.root/'task-publishing.sqlite3'
        self.assertNotIn(original['password'].encode(), storage.read_bytes())
        with patch.dict(os.environ, {'WFS_SECRET_KEY':'different-key','WFS_CONNECTIONS_KEY':''}):
            with self.assertRaises(settings.PublishingError):
                settings.repository()
        (self.root/'snapshot').mkdir()
        with zipfile.ZipFile(self.root/'backup.zip','w') as archive:
            self.assertTrue(add_connection_settings(archive,self.root,self.root/'snapshot', 'task-publishing.sqlite3'))
        with zipfile.ZipFile(self.root/'backup.zip') as archive:
            self.assertIn('data/task-publishing.sqlite3', archive.namelist())
        settings.save_repository(dict(saved,username='',password=''))
        self.assertFalse(settings.public_repository()['password_set'])
        for url in ['file:///secret', 'https://user:pass@example.com/simple', 'https://example.com/simple?token=secret']:
            with self.assertRaises(settings.PublishingError):
                settings.index_url(url)

    def test_admin_auth_csrf_and_ordinary_user_denial(self):
        app = create_app()
        app.testing = True
        client = app.test_client()
        base = '/api/admin/task-publishing'
        self.assertEqual(client.get(base+'/examples').status_code,401)
        login = client.post('/api/user/login',json={'username':'admin','password':'test-password'})
        headers = {'X-CSRF-Token':login.json['data']['csrf_token']}
        value = client.get(base+'/examples').json['data']['items'][0]
        self.assertEqual(client.post(base+'/examples',json=value).status_code,403)
        self.assertEqual(client.post(base+'/examples',json=value,headers=headers).status_code,200)
        with patch('app.middleware.identity', return_value={'username':'viewer','role':'viewer'}):
            for path in ('examples','repository'):
                self.assertEqual(client.get(base+'/'+path).status_code,403)
                self.assertEqual(client.post(base+'/'+path,json=value,headers=headers).status_code,403)

    def test_requirements_accept_standard_constraints_but_reject_urls_and_pip_options(self):
        from app.bootstrap.task_packages import _requirements, PackageError
        path = self.root/'requirements.txt'
        path.write_text('requests>=2.0,<3\npsycopg[binary]==3.3.6; python_version >= "3.9"\n',encoding='utf-8')
        self.assertEqual(len(_requirements(self.root)),2)
        for value in ('--extra-index-url https://example.com/simple', 'demo @ https://example.com/demo.whl', '-r other.txt'):
            path.write_text(value,encoding='utf-8')
            with self.subTest(requirement=value), self.assertRaises(PackageError):
                _requirements(self.root)
        with self.assertRaises(settings.PublishingError):
            settings.save_repository(dict(revision=0, mode=[]))
        with self.assertRaises(settings.PublishingError):
            settings.save_example(dict(language=[]))
