"""Read-only discovery, credential boundaries, stable review refs and scan races."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import requests
import test_local_integration
from app import create_app
from app.bootstrap import gitlab_updates as updates
from app.bootstrap.database import GaussDB

A, B, C, D = (letter * 40 for letter in 'abcd')
SECRET = 'glpat-test-secret-never-returned'


def changed(path, old=None, **extra):
    return dict(old_path=old or path, new_path=path, diff='@@ -1 +1 @@\n-old\n+new\n', **extra)


class Fixture:
    def __init__(self):
        self.head = C
        self.calls = []
        self.fail = None
        self.ancestor = A

    def get(self, client, suffix='', params=None):
        self.calls.append((suffix, params))
        if self.fail:
            raise self.fail
        if not suffix:
            return {'path_with_namespace': 'team/project', 'default_branch': 'main'}, {}
        if suffix == '/repository/branches/main':
            return {'name': 'main', 'commit': {'id': B}}, {}
        if suffix == '/repository/branches':
            return [{'name': 'main', 'commit': {'id': B}}, {'name': 'feature/report', 'commit': {'id': self.head}}], {}
        if suffix == '/repository/merge_base':
            return {'id': self.ancestor}, {}
        if suffix == '/repository/compare':
            return {'diffs': [changed('frontend/src/report.vue'), changed('app/jobs/team/report/main.py'),
                              changed('app/common/report.py'), changed('app/bootstrap/moved.py', 'app/jobs/team/report/helper.py', renamed_file=True)],
                    'commits': [{'id': params['to'], 'title': 'Report update', 'author_name': 'Developer', 'committed_date': '2026-10-27T10:00:00Z'}]}, {}
        raise AssertionError(suffix)


class GitLabTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {'WFS_DATA_DIR': str(self.root),
                                              'WFS_LOCAL_DB_PATH': str(self.root / 'platform.sqlite3'),
                                              'WFS_SCHEDULER_CONTROL_URL': ''})
        environment.start(); self.addCleanup(environment.stop)
        self.app = create_app(); self.app.testing = True
        self.client = self.app.test_client()
        result = self.client.post('/api/user/login', json={'username': 'admin', 'password': 'test-password'})
        self.headers = {'X-CSRF-Token': result.json['data']['csrf_token']}
        self.fixture = Fixture()

    def config(self, **extra):
        return updates.save_configuration({**copy.deepcopy(updates.DEFAULTS), 'url': 'https://gitlab.example',
            'project': 'team/project', 'token': SECRET, 'enabled': True, 'platform_commit': A,
            'tasks': [{'pid': 'report', 'path': 'app/jobs/team/report', 'commit': A}], **extra})

    def network(self):
        fixture = self.fixture
        return patch.object(updates.Client, 'get', lambda client, suffix='', params=None: fixture.get(client, suffix, params))

    def run_scan(self):
        with self.network():
            result = updates.scan(updates.configuration())
        with updates.store() as db:
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(result),))
        return result

    def test_classification_rename_baselines_and_pinned_links(self):
        self.config()
        data = self.run_scan()
        self.assertEqual([item['kind'] for item in data['items']], ['branch', 'platform', 'task'])
        branch, platform, task = data['items']
        self.assertEqual(branch['categories'], ['platform', 'shared', 'task'])
        self.assertEqual(branch['files'][-1]['categories'], ['platform', 'task'])
        self.assertEqual(len(task['files']), 2)
        self.assertEqual(len(platform['files']), 3)
        self.assertIn('source_branch=feature%2Freport', branch['merge_url'])
        self.assertIn(B + '...' + C, branch['compare_url'])
        self.assertTrue(all(i['compare_url'].startswith('https://gitlab.example/team/project/') for i in data['items']))
        self.assertFalse(task['merge_url'])
        public = updates.state('admin')
        self.assertEqual((public['pending_merge'], public['pending_release']), (1, 2))
        self.assertNotIn('diff', public['items'][0]['files'][0])
        self.assertIn('+new', updates.diff(branch['id'], 0)['diff'])

    def test_unchanged_refs_reuse_comparisons_and_baseline_ancestry(self):
        self.config()
        first = self.run_scan()
        self.fixture.calls.clear()
        with self.network():
            second = updates.scan(updates.configuration(), first)
        self.assertEqual(second['items'], first['items'])
        self.assertFalse([call for call in self.fixture.calls if call[0] in ('/repository/compare', '/repository/merge_base')])

    def test_encryption_masking_preservation_and_configuration_cas(self):
        public = self.config()
        self.assertTrue(public['token_set'])
        self.assertNotIn('token', public)
        self.assertNotIn(SECRET.encode(), (self.root / 'gitlab-updates.sqlite3').read_bytes())
        value = updates.save_configuration({**public, 'token': ''})
        self.assertEqual(updates.configuration()['token'], SECRET)
        with self.assertRaises(updates.GitLabError):
            updates.save_configuration(public)
        updates.save_configuration({**value, 'clear_token': True})
        self.assertFalse(updates.public_configuration()['token_set'])

    def test_read_acknowledgement_is_per_user_and_does_not_advance_baselines(self):
        self.config(); self.run_scan()
        fingerprint = updates.state('admin')['fingerprint']
        updates.acknowledge('admin', fingerprint)
        self.assertFalse(updates.state('admin')['unread'])
        self.assertTrue(updates.state('other-admin')['unread'])
        self.assertEqual(updates.configuration()['platform_commit'], A)
        self.fixture.head = D
        self.run_scan()
        self.assertTrue(updates.state('admin')['unread'])
        with self.assertRaises(updates.GitLabError):
            updates.acknowledge('admin', fingerprint)

    def test_http_insecure_urls_paths_and_overlapping_bindings(self):
        cases = [{'url': 'http://gitlab.example'}, {'url': 'https://user:password@gitlab.example'},
                 {'url': 'https://gitlab.example/path?token=secret'}, {'url': 'https://[invalid'},
                 {'task_roots': ['/etc']}, {'task_roots': ['../jobs']}, {'task_roots': ['app/.git']},
                 {'tasks': [{'pid': 'one', 'path': 'jobs/a', 'commit': A}, {'pid': 'two', 'path': 'jobs/a/sub', 'commit': A}]},
                 {'platform_commit': 'main'}, {'interval': 5}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(updates.GitLabError):
                self.config(**case)
        self.config(url='http://gitlab.example', allow_http=True)

    def test_rewritten_or_newer_deployment_baseline_is_not_offered_as_upgrade(self):
        self.config()
        self.fixture.ancestor = D
        result = self.run_scan()
        self.assertEqual([i['kind'] for i in result['items']], ['branch'])
        self.assertTrue(any('未包含' in message for message in result['warnings']))

    def test_unknown_task_baselines_are_visible_and_never_guessed(self):
        self.config(platform_commit='', tasks=[])
        result = self.run_scan()
        self.assertEqual(len(result['items']), 1)
        self.assertTrue(any('尚未绑定任务' in message for message in result['warnings']))
        self.assertTrue(any('尚未确认平台' in message for message in result['warnings']))

    def test_timeout_and_truncated_text_are_explicit(self):
        config = self.config()
        raw = {'diffs': [dict(changed('main.py'), diff='+' * 100000)], 'compare_timeout': True}
        with patch.object(updates.Client, 'get', return_value=(raw, {})):
            warnings = []
            result = updates.comparison(updates.Client(config), A, B, False, warnings)
        self.assertTrue(result['incomplete']); self.assertTrue(warnings)
        self.assertTrue(result['files'][0]['truncated'])
        self.assertEqual(len(result['files'][0]['diff']), 80000)

    def test_network_failure_preserves_previous_results_and_has_no_token(self):
        self.config(); self.run_scan()
        config = updates.configuration()
        with updates.store() as db:
            db.execute('INSERT INTO scan_lease VALUES(1,?,?)', ('worker', 9999999999))
        with patch.object(updates, 'scan', side_effect=updates.GitLabError('无法连接 GitLab。')):
            updates._worker('worker', config)
        value = updates.state('admin')
        self.assertEqual(value['count'], 3)
        self.assertTrue(value['error'])
        self.assertFalse(value['scanning'])
        self.assertNotIn(SECRET, json.dumps(value))

    def test_scan_lease_deduplicates_requests_and_config_changes_discard_old_scan(self):
        self.config()
        with patch.object(updates.threading, 'Thread') as thread:
            self.assertTrue(updates.request_scan(True))
            self.assertFalse(updates.request_scan(True))
            thread.assert_called_once()
        config = updates.configuration()
        with updates.store() as db:
            token = db.execute('SELECT token FROM scan_lease').fetchone()[0]
        result = dict(items=[], warnings=['old'], error='', checked_at=1, comparisons={})
        def change(*args):
            updates.save_configuration({**updates.public_configuration(), 'target': 'release'})
            return result
        with patch.object(updates, 'scan', side_effect=change):
            updates._worker(token, config)
        self.assertEqual(updates.state('admin')['warnings'], [])

    def test_permissions_csrf_and_secrets_are_enforced_for_all_routes(self):
        self.config()
        base = '/api/admin/gitlab-updates'
        self.assertEqual(self.app.test_client().get(base + '/state').status_code, 401)
        self.assertEqual(self.client.post(base + '/scan', json={}).status_code, 403)
        self.assertNotIn('token', self.client.get(base + '/configuration').json['data'])
        with GaussDB() as db:
            from app.settings import AUTH_ADMIN_PASSWORD_HASH
            db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)',
                           params=('git-viewer', AUTH_ADMIN_PASSWORD_HASH, 'viewer'))
        viewer = self.app.test_client()
        login = viewer.post('/api/user/login', json={'username': 'git-viewer', 'password': 'test-password'})
        headers = {'X-CSRF-Token': login.json['data']['csrf_token']}
        for path in ('/state', '/configuration', '/diff?id=fake&index=0'):
            self.assertEqual(viewer.get(base + path).status_code, 403)
        for path in ('/configuration', '/scan', '/acknowledge'):
            self.assertEqual(viewer.post(base + path, json={}, headers=headers).status_code, 403)

    def test_client_rejects_redirects_and_uses_only_authenticated_get(self):
        self.config()
        response = requests.Response()
        response.status_code = 302
        response._content = b'{}'; response._content_consumed = True
        with patch.object(requests.Session, 'get', return_value=response) as get:
            client = updates.Client(updates.configuration())
            with self.assertRaises(updates.GitLabError):
                client.get()
            args, kwargs = get.call_args
            self.assertEqual(args[0], 'https://gitlab.example/api/v4/projects/team%2Fproject')
            self.assertFalse(kwargs['allow_redirects'])
            self.assertTrue(kwargs['verify'])
            self.assertEqual(kwargs['headers']['PRIVATE-TOKEN'], SECRET)
            self.assertFalse(client.session.trust_env)
            client.close()

    def test_real_http_gitlab_scan_is_read_only_and_returns_cached_diffs(self):
        from gitlab_fixture import serve, TOKEN
        server, url, calls = serve()
        try:
            self.config(url=url, allow_http=True, token=TOKEN,
                        tasks=[{'pid': 'slow', 'path': 'app/jobs/acceptance/slow', 'commit': A}])
            result = updates.scan(updates.configuration())
            self.assertEqual([item['kind'] for item in result['items']], ['branch', 'platform', 'task'])
            self.assertTrue(all(method == 'GET' for method, _, _ in calls))
            with updates.store() as db:
                db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(result),))
            response = self.client.get('/api/admin/gitlab-updates/state')
            item = response.json['data']['items'][0]
            response = self.client.get('/api/admin/gitlab-updates/diff', query_string={'id': item['id'], 'index': 1})
            self.assertIn('+new-task', response.json['data']['diff'])
            self.assertNotIn(TOKEN, json.dumps(updates.public_configuration()))
        finally:
            server.shutdown(); server.server_close()

    def test_backup_restores_gitlab_configuration_and_acknowledgements(self):
        from scripts.backup_files import add_connection_settings
        from scripts.restore_local import restore
        self.config(); self.run_scan()
        updates.acknowledge('admin', updates.state('admin')['fingerprint'])
        archive_path = self.root / 'backup.zip'
        temporary = self.root / 'snapshot'
        temporary.mkdir()
        with zipfile.ZipFile(archive_path, 'w') as archive:
            self.assertTrue(add_connection_settings(archive, self.root, temporary, 'gitlab-updates.sqlite3'))
            archive.writestr('manifest.json', json.dumps({'format': 2}))
        restored = restore(archive_path, self.root / 'restored')
        with patch.dict(os.environ, {'WFS_DATA_DIR': str(restored / 'data')}):
            self.assertEqual(updates.configuration()['token'], SECRET)
            self.assertFalse(updates.state('admin')['unread'])
            self.assertEqual(updates.state('admin')['count'], 3)
