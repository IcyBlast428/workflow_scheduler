"""Readonly file access, directory boundaries and preview limits."""
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_local_integration as shared  # sets an isolated SQLite environment
from app import create_app
from app.api import operations as views
from app.bootstrap import task_source as source
from app.bootstrap.database import GaussDB
from werkzeug.security import generate_password_hash


class TaskSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.testing = True

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base/'jobs'
        self.task = self.root/'group'/'task'
        self.task.mkdir(parents=True)
        (self.task/'helpers').mkdir()
        (self.task/'main.py').write_text('print("中文任务")\n', encoding='utf-8')
        (self.task/'helpers'/'worker.py').write_text('# 子目录文件\n', encoding='utf-8')
        (self.task/'config.ini').write_text('[task]\nname=示例\n', encoding='utf-8')
        (self.task/'README.md').write_text('<script>alert("text only")</script>', encoding='utf-8')
        (self.task/'.env').write_text('EXAMPLE=test-only\n', encoding='utf-8')
        self.spec = {'pid': 'source__fixture', 'task_dir': self.task, 'main_file': 'main.py'}
        self.root_patch = patch.object(source, 'TASK_DIR', self.root)
        self.spec_patch = patch.object(views, 'discover_task_specs', return_value=[self.spec])
        self.root_patch.start(); self.spec_patch.start()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.root_patch.stop); self.addCleanup(self.spec_patch.stop)

    def client(self, username='admin'):
        client = self.app.test_client()
        login = client.post('/api/user/login', json={'username': username, 'password': 'test-password'})
        self.assertEqual(login.status_code, 200)
        return client, {'X-CSRF-Token': login.json['data']['csrf_token']}

    def test_auth_readonly_and_nested_config_files(self):
        endpoint = '/api/taskinfo/source'
        self.assertEqual(self.app.test_client().get(endpoint, query_string={'pid': self.spec['pid']}).status_code, 401)
        client, headers = self.client()
        result = client.get(endpoint, query_string={'pid': self.spec['pid']})
        names = {item['path'] for item in result.json['data']['entries']}
        self.assertEqual(names, {'main.py', 'helpers', 'config.ini', 'README.md', '.env'})
        nested = client.get(endpoint, query_string={'pid': self.spec['pid'], 'dir': 'helpers'})
        self.assertEqual(nested.json['data']['entries'][0]['path'], 'helpers/worker.py')
        for filename in ('main.py', 'helpers/worker.py', 'config.ini', 'README.md', '.env'):
            response = client.get(endpoint, query_string={'pid': self.spec['pid'], 'file': filename})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['data']['kind'], 'text')
            self.assertTrue(response.json['data']['readonly'])
        before = (self.task/'main.py').read_bytes()
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(client, method)(endpoint, headers=headers, json={'pid': self.spec['pid'], 'file': 'main.py', 'content': 'overwrite'})
            self.assertEqual(response.status_code, 405)
        self.assertEqual((self.task/'main.py').read_bytes(), before)
        self.assertEqual(client.get(endpoint, query_string={'pid': 'unknown'}).status_code, 404)

    def test_description_is_bounded_and_does_not_follow_symlinks(self):
        client, _ = self.client()
        endpoint = '/api/taskinfo/detail'
        with patch.object(views, 'load_schedule', return_value={}):
            normal = client.get(endpoint, query_string={'pid': self.spec['pid']})
            self.assertIn('<script>', normal.json['data']['description'])
            readme = self.task/'README.md'
            readme.write_text('x' * (source.MAX_BYTES + 1), encoding='utf-8')
            oversized = client.get(endpoint, query_string={'pid': self.spec['pid']})
            self.assertEqual(oversized.status_code, 200)
            self.assertLess(len(oversized.json['data']['description']), 1000)
            if os.name != 'nt':
                readme.unlink()
                outside = self.base/'private.txt'
                outside.write_text('OUTSIDE_PRIVATE_CONTENT', encoding='utf-8')
                readme.symlink_to(outside)
                linked = client.get(endpoint, query_string={'pid': self.spec['pid']})
                self.assertEqual(linked.status_code, 200)
                self.assertNotIn('OUTSIDE_PRIVATE_CONTENT', linked.json['data']['description'])

    def test_existing_viewer_role_can_only_read(self):
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)', params=('source-read-viewer', generate_password_hash('test-password'), 'viewer'))
        try:
            client, headers = self.client('source-read-viewer')
            self.assertEqual(client.get('/api/taskinfo/source', query_string={'pid': self.spec['pid'], 'file': 'main.py'}).status_code, 200)
            self.assertEqual(client.put('/api/taskinfo/source', headers=headers, json={}).status_code, 403)
        finally:
            with GaussDB() as db:
                db.execute_sql('DELETE FROM wfs_users WHERE username=?', params=('source-read-viewer',))

    def test_traversal_symlinks_and_special_files_cannot_escape(self):
        outside = self.base/'outside.py'
        outside.write_text('outside secret', encoding='utf-8')
        for path in ('../outside.py', '../../outside.py', '/etc/passwd', 'C:/secret.py', 'helpers/../../main.py', 'helpers\\worker.py', './main.py'):
            with self.assertRaises(source.SourceError):
                source.read_source(self.spec, path)
        with self.assertRaises(source.SourceError):
            source.list_source(self.spec, '../')
        if os.name != 'nt':
            (self.task/'link.py').symlink_to(outside)
            (self.task/'linked-dir').symlink_to(self.base)
            os.mkfifo(self.task/'pipe')
            for filename in ('link.py', 'linked-dir/outside.py', 'pipe'):
                with self.assertRaises(source.SourceError):
                    source.read_source(self.spec, filename)
            with self.assertRaises(source.SourceError):
                source.list_source(self.spec, 'linked-dir')
            entries = {item['name']: item['type'] for item in source.list_source(self.spec)['entries']}
            self.assertEqual(entries['link.py'], 'unavailable')
            self.assertEqual(entries['pipe'], 'unavailable')

    def test_encodings_binary_image_size_and_directory_paging(self):
        (self.task/'gbk.py').write_bytes('# coding: gbk\nprint("中文")\n'.encode('gbk'))
        (self.task/'gbk.sql').write_bytes('-- 中文\nSELECT 1;'.encode('gbk'))
        self.assertIn('中文', source.read_source(self.spec, 'gbk.py')['content'])
        self.assertIn('中文', source.read_source(self.spec, 'gbk.sql')['content'])
        (self.task/'binary.bin').write_bytes(b'\x00\x01binary')
        self.assertEqual(source.read_source(self.spec, 'binary.bin')['kind'], 'binary')
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jwZkAAAAASUVORK5CYII=')
        (self.task/'sample.png').write_bytes(png)
        self.assertTrue(source.read_source(self.spec, 'sample.png')['data_url'].startswith('data:image/png;base64,'))
        (self.task/'large.txt').write_bytes(b'x'*(source.MAX_BYTES+1))
        self.assertEqual(source.read_source(self.spec, 'large.txt')['kind'], 'unavailable')
        (self.task/'long.txt').write_text('\n'*source.MAX_LINES)
        self.assertEqual(source.read_source(self.spec, 'long.txt')['kind'], 'unavailable')
        with patch.object(source, 'PAGE_SIZE', 3):
            first = source.list_source(self.spec)
            second = source.list_source(self.spec, offset=first['next_offset'])
            self.assertTrue(first['has_more'])
            self.assertFalse({item['path'] for item in first['entries']} & {item['path'] for item in second['entries']})
