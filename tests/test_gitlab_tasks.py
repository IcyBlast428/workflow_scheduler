"""Real HTTP discovery, immutable publication and deletion with output files."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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
            db.replace('snapshot',('id','payload'),(1,json.dumps(data)))
        return data

    @property
    def pid(self):
        return tasks.generated_task_id(updates.configuration(), 'app/jobs/acceptance/git_new')

    def candidate(self, pid=None):
        pid = pid or self.pid
        return next(i for i in tasks.changes()['items'] if i['pid'] == pid)

    def test_new_update_delete_preserve_outputs_history_and_pinned_execution(self):
        self.connect()
        candidate = self.candidate()
        self.assertEqual(candidate['kind'], 'new')
        self.assertFalse(candidate['blocked'])
        data = tasks.stage(candidate['id'], 'admin')
        self.assertEqual(packages.registry()[self.pid]['active_version'], None)
        self.assertNotIn('.wfs-task.json', [f['path'] for f in data['manifest']])
        self.activate(self.ready(data))
        first = task_loader.discover_task_specs()[0]
        self.assertFalse(task_loader.discover_task_specs()[0]['schedule_enabled'])
        self.assertNotIn(self.pid, [i['pid'] for i in tasks.changes()['items']])
        code = packages.release_dir(self.pid, data['version']) / 'code'
        code.chmod(0o755)
        extra = code / 'untracked-output.csv'
        extra.write_text('preserve old output')
        code.chmod(0o555)
        persistent = self.root / ('task-data/' + self.pid + '/checkpoint.json')
        persistent.parent.mkdir(parents=True); persistent.write_text('{"checkpoint":42}')
        self.server.repository['app/jobs/acceptance/git_new/helper.py'] = b'value="GITLAB_V2"\n'
        self.server.head = 'd' * 40
        self.scan()
        update = self.candidate()
        self.assertEqual(update['kind'], 'update')
        second = tasks.stage(update['id'], 'admin')
        self.assertIn('+value="GITLAB_V2"', packages.preview(self.pid, second['version'], 'helper.py')['diff'])
        self.activate(self.ready(second))
        self.assertEqual(extra.read_text(), 'preserve old output')
        self.assertFalse((packages.release_dir(self.pid, second['version']) / 'code/untracked-output.csv').exists())
        self.server.repository = {p:c for p,c in self.server.repository.items() if not p.startswith('app/jobs/acceptance/git_new/')}
        self.server.head = 'e' * 40
        self.scan()
        deleted = self.candidate()
        self.assertEqual(deleted['kind'], 'delete')
        tasks.remove(deleted['id'], 'admin')
        self.assertTrue(packages.task(self.pid)['deleted_at'])
        self.assertEqual(persistent.read_text(), '{"checkpoint":42}')
        self.assertEqual(extra.read_text(), 'preserve old output')
        self.assertFalse(task_loader.discover_task_specs())
        # A queued execution retains its original interpreter and whole module tree.
        self.assertEqual(core.execute_py(first['main_file_path'], self.pid, python_executable=first['python_executable']), 0)
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
                db.replace('snapshot',('id','payload'),(1,json.dumps(value)))
            with self.subTest(failure=failure), self.assertRaises(packages.PackageError):
                tasks.remove(identifier, 'admin')
            self.assertFalse(packages.task(self.pid)['deleted_at'])

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
        self.assertIsNone(packages.task(self.pid)['active_version'])

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
        pid = self.pid
        updates.save_configuration({**updates.public_configuration(), 'tasks':[{'pid':pid,'path':'app/jobs/acceptance/renamed','commit':''}]})
        self.server.head = 'd' * 40; self.scan()
        moved = self.candidate(pid)
        self.assertEqual(moved['kind'], 'update')
        self.assertTrue(moved['path'].endswith('/renamed'))
        self.server.repository = {p:c for p,c in self.server.repository.items() if not p.endswith('.py')}
        self.server.repository['app/jobs/acceptance/renamed/README.md'] = b'keep directory'
        self.server.head = 'e' * 40; self.scan()
        invalid = self.candidate(pid)
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
        for override in ({'task_id':'manual'}, {'pid':'manual'}, {'configuration':{'task_id':'manual'}}, {'configuration':[]}):
            response=self.client.post(base,json={'action':'stage','id':candidate['id'],**override},headers=self.headers)
            self.assertEqual(response.status_code,400,response.json)
        result = self.client.post(base, json={'action':'stage','id':candidate['id']}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['data']['git_source']['sha'], B)
        from app.bootstrap.permissions import allowed
        self.assertFalse(allowed(base, 'GET', 'viewer'))
        self.assertFalse(allowed(base, 'POST', 'operator'))

    def test_bound_rollback_keeps_association_without_claiming_newer_content(self):
        legacy = packages.stage(package_tests.archive({'main.py':'print("legacy")\n'}),
                                {'task_name':'Legacy','group_name':'acceptance','folder_name':'git_new'}, 'admin')
        self.activate(self.ready(legacy))
        self.connect()
        pid = legacy['pid']
        updates.save_configuration({**updates.public_configuration(), 'tasks':[{'pid':pid,'path':'app/jobs/acceptance/git_new','commit':''}]})
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
            db.replace('snapshot',('id','payload'),(1,json.dumps(data)))
        self.assertNotIn(pid, [i['pid'] for i in tasks.changes()['items']])

    def test_generated_id_is_stable_unique_and_manifest_cannot_override_it(self):
        self.connect()
        original=self.candidate()['pid']
        self.assertRegex(original,r'^task_[0-9a-f]{32}$')
        self.server.repository['app/jobs/acceptance/git_new/.wfs-task.json']=b'{invalid ignored metadata'
        self.server.head='d'*40;self.scan()
        self.assertEqual(self.candidate()['pid'],original)
        self.scan();self.assertEqual(self.candidate()['pid'],original)
        config=updates.configuration()
        self.assertNotEqual(original,tasks.generated_task_id(config,'other/jobs/acceptance/git_new'))
        self.assertNotEqual(original,tasks.generated_task_id({**config,'project':'another/project'},'app/jobs/acceptance/git_new'))
        with self.assertRaises(packages.PackageError):
            tasks.stage(self.candidate()['id'],'admin',{'task_id':'manual-id'})

    def test_multiple_entries_are_selected_in_platform_and_retained(self):
        self.connect()
        self.server.repository.pop('app/jobs/acceptance/git_new/main.py')
        self.server.repository['app/jobs/acceptance/git_new/src/run.py']=b'print("selected-entry")'
        self.server.head='d'*40;self.scan()
        item=self.candidate()
        self.assertFalse(item['blocked']);self.assertTrue(item['configuration_required'])
        with self.assertRaisesRegex(packages.PackageError,'选择'):
            tasks.stage(item['id'],'admin')
        for entry in ('../main.py','missing.py'):
            with self.assertRaises(packages.PackageError):
                tasks.stage(item['id'],'admin',{'main_file':entry})
        data=tasks.stage(item['id'],'admin',{'main_file':'src/run.py','task_name':'平台配置的报表'})
        self.assertEqual(data['main_file'],'src/run.py')
        self.assertEqual(packages.task(item['pid'])['task_name'],'平台配置的报表')
        self.scan();current=self.candidate()
        self.assertEqual(current['pid'],item['pid'])
        self.assertEqual(current['main_file'],'src/run.py')
        self.assertEqual(current['task_name'],'平台配置的报表')
        with self.assertRaises(packages.PackageError):tasks.stage(item['id'],'admin')
        self.activate(self.ready(data))
        self.assertEqual(task_loader.discover_task_specs()[0]['main_file'],'src/run.py')
        self.server.repository['app/jobs/acceptance/git_new/helper.py']=b'value=2'
        self.server.head='e'*40;self.scan()
        tasks.stage(self.candidate()['id'],'admin',{'task_name':'新版报表','main_file':'src/run.py'})
        self.assertEqual(self.candidate()['task_name'],'新版报表')
        self.assertEqual(packages.task(item['pid'])['task_name'],'平台配置的报表')


    def test_simultaneous_first_publications_create_only_one_task(self):
        self.connect();identifier=self.candidate()['id']
        barrier=Barrier(2)
        original_archive=tasks._archive
        def archive(*args):
            blob=original_archive(*args)
            barrier.wait(timeout=10)
            return blob
        def stage():
            try:
                return tasks.stage(identifier,'admin')
            except packages.PackageError as exc:
                return exc.status
        with patch.object(tasks,'_archive',archive), ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:stage(),range(2)))
        self.assertEqual(sum(isinstance(result,dict) for result in results),1)
        self.assertIn(409,results)
        self.assertEqual(list(packages.registry()),[self.pid])
        self.assertEqual(len(packages.overview(self.pid)["versions"]),1)

    def test_example_downloads_contain_code_without_identity_files(self):
        import io
        import zipfile
        for kind in ('outputs','nested','report_flow','database_transaction','retry_once','business_backfill','queue_observer','business_connection'):
            with self.subTest(kind=kind):
                response=self.client.get('/api/taskinfo/packages/example?kind='+kind)
                self.assertEqual(response.status_code,200)
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    names=archive.namelist()
                    self.assertTrue(any(name.endswith('.py') for name in names))
                    self.assertFalse(any(name.endswith('.wfs-task.json') for name in names))

    def test_registration_conflict_discards_only_the_new_candidate(self):
        self.connect()
        with patch.object(packages,'_write_task',side_effect=packages.PackageError('conflict',409)):
            with self.assertRaises(packages.PackageError):
                tasks.stage(self.candidate()['id'],'admin')
        self.assertNotIn(self.pid,packages.registry())
        from app.bootstrap.database import GaussDB
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_task_releases WHERE pid=?',params=(self.pid,))[0][0],0)
        releases=packages.storage_root()/self.pid/'releases'
        self.assertEqual(list(releases.iterdir()) if releases.exists() else [],[])

    def test_old_catalog_requires_rescan_instead_of_using_old_identities(self):
        self.connect()
        with updates.store() as db:
            snapshot=updates._snapshot(db)
            snapshot['task_catalog'].pop('identity_version')
            snapshot['task_catalog']['tasks'][0].pop('main_file_options')
            db.replace('snapshot',('id','payload'),(1,json.dumps(snapshot)))
        result=tasks.changes()
        self.assertFalse(result['complete'])
        self.assertEqual(result['items'],[])
        self.assertIn('重新检查',result['error'])
        self.scan()
        self.assertTrue(tasks.changes()['complete'])
        self.assertRegex(self.candidate()['pid'],r'^task_[0-9a-f]{32}$')

    def test_binding_cannot_create_a_manually_named_task(self):
        self.connect()
        updates.save_configuration({**updates.public_configuration(), 'tasks':[
            {'pid':'manual-id','path':'app/jobs/acceptance/git_new','commit':''}]})
        self.scan()
        result=tasks.changes()
        self.assertFalse(result['complete'])
        self.assertIn('新任务标识由平台自动生成',result['error'])
        self.assertNotIn('manual-id',packages.registry())

    def test_identity_collision_never_overwrites_another_task(self):
        self.connect();item=self.candidate()
        record=dict(pid=item['pid'],group_name='another',folder_name='unrelated',task_name='Unrelated',
                    active_version=None,deleted_at=None,revision=0)
        packages._write_task(record,expected=0)
        item=self.candidate();self.assertTrue(item['blocked'])
        with self.assertRaises(packages.PackageError):tasks.stage(item['id'],'admin')
        self.assertEqual(packages.task(item['pid'])['task_name'],'Unrelated')

    def test_directory_collision_identifies_active_and_recycled_owner(self):
        self.connect()
        item = self.candidate()
        record = packages._write_task(dict(pid='legacy-task', group_name=item['group_name'],
            folder_name=item['folder_name'], task_name='Legacy', active_version=None,
            deleted_at=None, revision=0), expected=0)
        for deleted in (None, '2026-11-16 12:00:00'):
            record['deleted_at'] = deleted
            record = packages._write_task(record, expected=record['revision'])
            candidate = self.candidate()
            self.assertFalse(candidate['blocked'])
            self.assertEqual(candidate['kind'], 'recover')
            self.assertEqual(candidate['recovery']['pid'], 'legacy-task')
            self.assertEqual(candidate['recovery']['deleted'], bool(deleted))
            with self.assertRaises(packages.PackageError):
                tasks.stage(candidate['id'], 'admin')
        self.assertEqual(packages.task('legacy-task')['task_name'], 'Legacy')

    def test_redeploy_recovers_recycled_legacy_task_at_original_path_and_id(self):
        from app.bootstrap.database import GaussDB
        from app.bootstrap.schedule_config import save_schedule
        old = packages.stage(package_tests.archive({'main.py': 'print("old")\n'}),
            {'task_name': 'Original task', 'group_name': 'acceptance', 'folder_name': 'git_new'}, 'admin')
        self.activate(self.ready(old))
        pid = old['pid']
        save_schedule(pid, {'schedule_type': 'every_hour', 'main_file': 'main.py', 'enabled': True})
        packages.recycle(pid, packages.task(pid)['revision'], 'admin')
        (packages.release_dir(pid, old['version'])/'code/main.py').unlink()
        self.connect()
        item = self.candidate()
        self.assertEqual(item['kind'], 'recover')
        response = self.client.post('/api/taskinfo/packages/gitlab',
            json={'action': 'recover', 'id': item['id']}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['data']['pid'], pid)
        self.assertIsNone(packages.task(pid)['deleted_at'])
        with self.assertRaises(packages.PackageError):
            tasks.recover(item['id'], 'admin')  # stale recovery cannot be replayed
        self.scan()
        item = self.candidate(pid)
        self.assertEqual(item['kind'], 'update')
        version = tasks.stage(item['id'], 'admin')
        self.activate(self.ready(version))
        self.assertEqual(set(packages.registry()), {pid})
        self.assertEqual(packages.task(pid)['group_name'], 'acceptance')
        self.assertEqual(packages.task(pid)['folder_name'], 'git_new')
        self.assertEqual(packages.task(pid)['task_name'], 'Original task')
        self.assertEqual(packages.release(pid, old['version'])['version'], old['version'])
        with GaussDB() as db:
            row = db.execute_query_sql('SELECT enabled,schedule_type FROM wfs_task_config WHERE pid=?', params=(pid,))[0]
        self.assertEqual(tuple(row), ('false', 'every_hour'))
        self.assertFalse(task_loader.discover_task_specs()[0]['error'])

    def test_same_remote_commit_with_missing_local_code_can_be_republished(self):
        self.connect()
        data = tasks.stage(self.candidate()['id'], 'admin')
        self.activate(self.ready(data))
        self.assertFalse(any(i['pid'] == self.pid for i in tasks.changes()['items']))
        (packages.release_dir(self.pid, data['version'])/'code/main.py').unlink()
        task_loader.invalidate_task_cache()
        item = self.candidate()
        self.assertEqual(item['kind'], 'update')
        self.assertTrue(item['recovery_required'])
        self.activate(self.ready(tasks.stage(item['id'], 'admin')))
        self.assertFalse(task_loader.discover_task_specs()[0]['error'])

    def test_recovery_cannot_reassign_a_foreign_repository_directory(self):
        self.connect()
        item = self.candidate()
        packages._write_task(dict(pid='foreign', group_name=item['group_name'], folder_name=item['folder_name'],
            task_name='Foreign', active_version=None, deleted_at='2026-11-16', revision=0,
            git_source={'project_key': 'other-project', 'path': item['path']}), expected=0)
        item = self.candidate()
        self.assertTrue(item['blocked'])
        self.assertNotIn('recovery', item)
        with self.assertRaises(packages.PackageError):
            tasks.recover(item['id'], 'admin')


if __name__ == '__main__':
    unittest.main()
