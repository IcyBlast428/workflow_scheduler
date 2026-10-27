"""Real HTTP discovery, immutable publication and deletion with output files."""
import copy
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_task_packages as package_tests
from gitlab_fixture import serve, TOKEN, B
from app.bootstrap import gitlab_tasks as tasks, gitlab_updates as updates, task_packages as packages, task_loader, core


class GitLabTaskTests(unittest.TestCase):
    setUp = package_tests.PackageTests.setUp
    ready = package_tests.PackageTests.ready
    activate = package_tests.PackageTests.activate

    def tearDown(self):
        if hasattr(self, 'catalog_environment'):
            self.catalog_environment.stop()
        package_tests.PackageTests.tearDown(self)

    def connect(self):
        self.catalog_environment = patch.dict(os.environ, {'WFS_DATA_DIR': str(self.root)})
        self.catalog_environment.start()
        self.server, url, self.calls = serve()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        updates.save_configuration({**copy.deepcopy(updates.DEFAULTS), 'enabled': True, 'allow_http': True,
                                    'url': url, 'project': 'team/project', 'token': TOKEN})
        self.scan()

    def scan(self):
        with updates.store() as db:
            previous = updates._snapshot(db)
        data = updates.scan(updates.configuration(), previous)
        with updates.store() as db:
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(data),))
        return data

    def candidate(self, pid='git_new'):
        return next(i for i in tasks.changes()['items'] if i['pid'] == pid)

    def test_new_update_delete_preserve_outputs_history_and_pinned_execution(self):
        self.connect()
        candidate = self.candidate()
        self.assertEqual(candidate['kind'], 'new')
        self.assertFalse(candidate['blocked'])
        data = tasks.stage(candidate['id'], 'admin')
        self.assertEqual(packages.registry()['git_new']['active_version'], None)
        self.assertNotIn('.wfs-task.json', [f['path'] for f in data['manifest']])
        self.activate(self.ready(data))
        first = task_loader.discover_task_specs()[0]
        self.assertFalse(task_loader.discover_task_specs()[0]['schedule_enabled'])
        self.assertNotIn('git_new', [i['pid'] for i in tasks.changes()['items']])
        code = packages.release_dir('git_new', data['version']) / 'code'
        code.chmod(0o755)
        extra = code / 'untracked-output.csv'
        extra.write_text('preserve old output')
        code.chmod(0o555)
        persistent = self.root / 'task-data/git_new/checkpoint.json'
        persistent.parent.mkdir(parents=True); persistent.write_text('{"checkpoint":42}')
        self.server.repository['app/jobs/acceptance/git_new/helper.py'] = b'value="GITLAB_V2"\n'
        self.server.head = 'd' * 40
        self.scan()
        update = self.candidate()
        self.assertEqual(update['kind'], 'update')
        second = tasks.stage(update['id'], 'admin')
        self.assertIn('+value="GITLAB_V2"', packages.preview('git_new', second['version'], 'helper.py')['diff'])
        self.activate(self.ready(second))
        self.assertEqual(extra.read_text(), 'preserve old output')
        self.assertFalse((packages.release_dir('git_new', second['version']) / 'code/untracked-output.csv').exists())
        self.server.repository = {p:c for p,c in self.server.repository.items() if not p.startswith('app/jobs/acceptance/git_new/')}
        self.server.head = 'e' * 40
        self.scan()
        deleted = self.candidate()
        self.assertEqual(deleted['kind'], 'delete')
        tasks.remove(deleted['id'], 'admin')
        self.assertTrue(packages.task('git_new')['deleted_at'])
        self.assertEqual(persistent.read_text(), '{"checkpoint":42}')
        self.assertEqual(extra.read_text(), 'preserve old output')
        self.assertFalse(task_loader.discover_task_specs())
        # A queued execution retains its original interpreter and whole module tree.
        self.assertEqual(core.execute_py(first['main_file_path'], 'git_new', python_executable=first['python_executable']), 0)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))

    def test_incomplete_stale_or_failed_inventory_cannot_delete(self):
        self.connect()
        data = self.ready(tasks.stage(self.candidate()['id'], 'admin')); self.activate(data)
        self.server.repository = {}; self.server.head = 'e' * 40; self.scan()
        identifier = self.candidate()['id']
        for failure in ('error', 'incomplete', 'expired'):
            self.scan()
            with updates.store() as db:
                value = updates._snapshot(db)
                if failure == 'error': value['error'] = 'GitLab unavailable'
                if failure == 'incomplete': value['task_catalog']['complete'] = False
                if failure == 'expired': value['checked_at'] = time.time() - 5000
                db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(value),))
            with self.subTest(failure=failure), self.assertRaises(packages.PackageError):
                tasks.remove(identifier, 'admin')
            self.assertFalse(packages.task('git_new')['deleted_at'])

    def test_changed_target_rejected_at_stage_and_activation(self):
        self.connect()
        candidate = self.candidate()
        self.server.head = 'd' * 40
        with self.assertRaises(packages.PackageError): tasks.stage(candidate['id'], 'admin')
        self.assertEqual(packages.registry(), {})
        self.server.head = B
        data = self.ready(tasks.stage(candidate['id'], 'admin'))
        self.server.head = 'd' * 40
        with self.assertRaises(packages.PackageError): self.activate(data)
        self.assertIsNone(packages.task('git_new')['active_version'])

    def test_archive_content_must_match_confirmed_tree(self):
        self.connect()
        candidate = self.candidate()
        self.server.repository['app/jobs/acceptance/git_new/helper.py'] = b'print("tampered")\n'
        with self.assertRaises(packages.PackageError) as error:
            tasks.stage(candidate['id'], 'admin')
        self.assertIn('校验失败', str(error.exception))
        self.assertEqual(packages.registry(), {})

    def test_stable_id_directory_move_and_missing_entry_are_not_deletions(self):
        self.connect()
        self.activate(self.ready(tasks.stage(self.candidate()['id'], 'admin')))
        self.server.repository = {p.replace('/git_new/', '/renamed/'):c for p,c in self.server.repository.items()}
        self.server.head = 'd' * 40; self.scan()
        moved = self.candidate()
        self.assertEqual(moved['kind'], 'update')
        self.assertTrue(moved['path'].endswith('/renamed'))
        self.server.repository = {p:c for p,c in self.server.repository.items() if not p.endswith('.py')}
        self.server.head = 'e' * 40; self.scan()
        invalid = self.candidate()
        self.assertEqual(invalid['kind'], 'update')
        self.assertTrue(invalid['blocked'])

    def test_gitlab_task_routes_permissions_csrf_and_publisher_allowlist(self):
        self.connect()
        base = '/api/taskinfo/packages/gitlab'
        self.assertEqual(self.app.test_client().get(base).status_code, 401)
        candidate = self.candidate()
        self.assertEqual(self.client.post(base, json={'action':'stage','id':candidate['id']}).status_code, 403)
        with patch.dict(os.environ, {'WFS_TASK_PUBLISHERS':'another-admin'}):
            self.assertEqual(self.client.post(base, json={'action':'stage','id':candidate['id']}, headers=self.headers).status_code, 403)
        result = self.client.post(base, json={'action':'stage','id':candidate['id']}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['data']['git_source']['sha'], B)
        from app.bootstrap.permissions import allowed
        self.assertFalse(allowed(base, 'GET', 'viewer'))
        self.assertFalse(allowed(base, 'POST', 'operator'))

    def test_legacy_rollback_keeps_association_without_claiming_newer_content(self):
        legacy = packages.stage(package_tests.archive({'main.py':'print("legacy")\n'}),
                                {'task_name':'Legacy','group_name':'acceptance','folder_name':'git_new'}, 'admin')
        self.activate(self.ready(legacy))
        self.connect()
        pid = legacy['pid']
        self.server.repository['app/jobs/acceptance/git_new/.wfs-task.json'] = json.dumps({'task_id':pid,'main_file':'main.py'}).encode()
        self.server.head = 'd' * 40; self.scan()
        current = tasks.stage(self.candidate(pid)['id'], 'admin')
        self.activate(self.ready(current))
        self.activate(legacy, rollback=True)
        source = packages.task(pid)['git_source']
        self.assertEqual(source['fingerprint'], '')
        self.assertEqual(source['sha'], '')
        self.assertEqual(self.candidate(pid)['kind'], 'update')
        self.server.repository = {}; self.server.head = 'e' * 40; self.scan()
        self.assertEqual(self.candidate(pid)['kind'], 'delete')

    def test_confirmed_legacy_binding_requires_actual_complete_deletion_evidence(self):
        legacy = packages.stage(package_tests.archive({'main.py':'print("legacy")\n'}),
                                {'task_name':'Legacy','group_name':'acceptance','folder_name':'old'}, 'admin')
        self.activate(self.ready(legacy)); self.connect()
        pid = legacy['pid']
        updates.save_configuration({**updates.public_configuration(), 'tasks':[{'pid':pid,'path':'app/jobs/acceptance/old','commit':'a'*40}]})
        self.scan()
        self.assertNotIn(pid, [i['pid'] for i in tasks.changes()['items']], 'A missing bound path alone cannot authorize deletion')
        self.server.compare_diffs = [{'old_path':'app/jobs/acceptance/old/main.py','new_path':'app/jobs/acceptance/old/main.py','deleted_file':True,'diff':'-print("legacy")\n'}]
        self.server.head = 'd' * 40; self.scan()
        self.assertEqual(self.candidate(pid)['kind'], 'delete')
        with updates.store() as db:
            data = updates._snapshot(db)
            next(i for i in data['items'] if i['kind'] == 'task')['incomplete'] = True
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(data),))
        self.assertNotIn(pid, [i['pid'] for i in tasks.changes()['items']])


if __name__ == '__main__':
    unittest.main()
