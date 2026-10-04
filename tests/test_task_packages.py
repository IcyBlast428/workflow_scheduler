"""Package lifecycle with isolated storage, real venvs and bounded ZIP attacks."""
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import test_local_integration  # establishes isolated authentication defaults
from app import create_app
from app.bootstrap import task_packages as packages, task_loader, core
from app.bootstrap.database import GaussDB
from app.bootstrap.schedule_config import save_schedule, load_schedule
from app.bootstrap.task_source import read_source
from app.bootstrap.operations import read_run, read_log
from app.extensions import scheduler


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buffer.getvalue()


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.jobs = self.root / 'jobs'
        self.jobs.mkdir()
        self.patches = [patch.dict(os.environ, {'WFS_LOCAL_DB_PATH': str(self.root / 'db.sqlite3'),
                                               'WFS_TASK_RELEASE_DIR': str(self.root / 'packages'),
                                               'WFS_SCHEDULER_CONTROL_URL': ''}),
                        patch.object(task_loader, 'TASK_DIR', self.jobs), patch.object(core, 'TASK_DIR', self.jobs)]
        for item in self.patches:
            item.start()
        task_loader.invalidate_task_cache()
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        result = self.client.post('/api/user/login', json={'username': 'admin', 'password': 'test-password'})
        self.headers = {'X-CSRF-Token': result.json['data']['csrf_token']}

    def tearDown(self):
        for job in scheduler.get_jobs():
            if job.id != 'MAIN_TASK_JOB':
                scheduler.remove_job(job.id)
        for item in reversed(self.patches):
            item.stop()
        task_loader.invalidate_task_cache()
        self.temp.cleanup()

    def new(self, files=None, folder='demo'):
        return packages.stage(archive(files or {'main.py': 'print("v1")\n', 'sql/query.sql': 'select 1;'}),
                              {'task_name': 'Demo', 'group_name': '包管理', 'folder_name': folder}, 'admin')

    def ready(self, data):
        packages.prepare(data['pid'], data['version'], data['main_file'])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = packages.release(data['pid'], data['version'])
            if result['status'] != 'preparing':
                self.assertEqual(result['status'], 'ready', result['message'])
                return result
            time.sleep(.05)
        self.fail('dependency preparation timed out')

    def activate(self, data, rollback=False):
        return packages.publish(data['pid'], data['version'], packages.task(data['pid'])['revision'], 'admin', rollback)

    def test_multifile_publish_diff_rollback_delete_restore_and_execution_pin(self):
        v1 = self.ready(self.new({'main.py': 'from helper import value\nprint(value)\n', 'helper.py': 'value="v1"\n', 'sql/query.sql': 'select 1;'}))
        current = self.activate(v1)
        pid = current['pid']
        spec1 = task_loader.discover_task_specs()[0]
        self.assertEqual(spec1['pid'], pid)
        save_schedule(pid, {'schedule_type': 'every_hour', 'main_file': 'main.py', 'enabled': True})
        core.aps_start(task_pid=pid)
        before_config = load_schedule(pid)
        self.assertEqual(packages.overview(pid)['task']['task_name'],before_config['task_name'])
        v2 = self.ready(packages.stage(archive({'main.py': 'from helper import value\nprint(value)\n', 'helper.py': 'value="v2"\n', 'README.md': 'version two'}), {'pid': pid}, 'admin'))
        preview = packages.preview(pid, v2['version'], 'helper.py')
        self.assertEqual({c['kind'] for c in preview['changes']}, {'added','modified','deleted'})
        self.assertIn('+value="v2"', preview['diff'])
        self.activate(v2)
        spec2 = task_loader.discover_task_specs()[0]
        self.assertNotEqual(spec1['main_file_path'], spec2['main_file_path'])
        self.assertEqual(before_config['version'], load_schedule(pid)['version'])
        self.assertIn(v2['version'], scheduler.get_job(pid).args[0])
        # Execution queued before activation retains the complete old module tree.
        self.assertEqual(core.execute_py(spec1['main_file_path'], pid, python_executable=spec1['python_executable']), 0)
        from app.bootstrap.operations import list_runs
        run = list_runs(pid)[0]
        self.assertEqual(run['code_version']['task_release'], v1['version'])
        self.assertIn('v1', read_log(run['run_id'])['content'])
        self.activate(v1, rollback=True)
        self.assertIn(v1['version'], scheduler.get_job(pid).args[0])
        self.assertEqual(before_config['version'], load_schedule(pid)['version'])
        with patch('app.bootstrap.task_source.TASK_DIR', self.jobs):
            self.assertIn('value="v1"', read_source(task_loader.discover_task_specs()[0], 'helper.py')['content'])
        recycled = packages.recycle(pid, packages.task(pid)['revision'], 'admin')
        self.assertIsNone(scheduler.get_job(pid))
        self.assertFalse(task_loader.discover_task_specs())
        with self.assertRaises(ValueError):
            core.call_task_once(pid)
        core.aps_start()
        with GaussDB() as db:
            self.assertTrue(db.execute_query_sql('SELECT pid FROM wfs_job_stats WHERE pid=?', params=(pid,)))
        packages.recycle(pid, recycled['revision'], 'admin', restore=True)
        self.assertFalse(load_schedule(pid)['form']['enabled'])
        self.assertTrue(task_loader.discover_task_specs())
        self.assertIsNone(scheduler.get_job(pid))
        self.assertTrue(read_run(run['run_id']))

    def test_reject_unsafe_packages_without_registry_side_effects(self):
        bad = [archive({'../escaped.py': 'print(1)'}), archive({'/tmp/escaped.py': 'print(1)'}),
               archive({'Main.py':'print(1)','main.py':'print(2)'}), archive({'main.py':'invalid syntax ?'}),
               archive({'main.py':'print(1)','requirements.txt':'-e https://example.com'}),
               archive({'main.py':'print(1)','.env':'SECRET=hidden'}), archive({'con.py':'print(1)'})]
        buff = io.BytesIO()
        with zipfile.ZipFile(buff, 'w') as z:
            info = zipfile.ZipInfo('main.py'); info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, '/etc/passwd')
        bad.append(buff.getvalue())
        for blob in bad:
            with self.subTest(blob=blob[:8]), self.assertRaises(packages.PackageError):
                packages.stage(blob, {'task_name':'Bad','group_name':'examples','folder_name':'bad'}, 'admin')
        with patch.dict(os.environ, {'WFS_PACKAGE_EXPANDED_MB':'0'}), self.assertRaises(packages.PackageError):
            self.new()
        self.assertEqual(packages.registry(), {})
        self.assertFalse((self.root/'escaped.py').exists())

    def test_nested_entry_is_preserved_when_updating_a_package(self):
        files = {'src/main.py': 'print("nested")\n', 'src/helper.py': 'value=1\n'}
        first = packages.stage(archive(files), {'task_name': 'Nested', 'group_name': 'examples',
                                'folder_name': 'nested', 'main_file': 'src/main.py'}, 'admin')
        self.assertEqual(first['main_file'], 'src/main.py')
        self.assertEqual({item['path'] for item in first['manifest']}, set(files))
        self.activate(self.ready(first))
        second = packages.stage(archive(files), {'pid': first['pid']}, 'admin')
        self.assertEqual(second['main_file'], 'src/main.py')
        wrapped = self.new({'export/main.py': 'print("wrapped")\n', 'export/helper.py': 'value=1\n'})
        self.assertEqual(wrapped['main_file'], 'main.py')

    def test_conflicts_scheduler_failure_and_restart_recovery(self):
        v1 = self.ready(self.new())
        self.activate(v1)
        pid = v1['pid']
        save_schedule(pid, {'schedule_type':'every_hour','main_file':'main.py','enabled':True})
        core.aps_start(task_pid=pid)
        v2 = self.ready(packages.stage(archive({'main.py':'print("v2")'}), {'pid':pid}, 'admin'))
        v3 = self.ready(packages.stage(archive({'main.py':'print("v3")'}), {'pid':pid}, 'admin'))
        original = core.aps_start
        calls = []
        def fail_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('injected scheduler rejection')
            return original(*args, **kwargs)
        with patch.object(core, 'aps_start', fail_once), self.assertRaises(packages.PackageError):
            self.activate(v2)
        self.assertEqual(packages.task(pid)['active_version'], v1['version'])
        self.assertIn(v1['version'], scheduler.get_job(pid).args[0])
        # The failed candidate can be retried while the current code is unchanged.
        self.activate(v2)
        # Another candidate based on v1 cannot silently replace the new v2.
        with self.assertRaises(packages.PackageError) as conflict:
            self.activate(v3)
        self.assertEqual(conflict.exception.status,409)
        previous = packages.task(pid)
        pending = {**previous, 'active_version':v2['version'], 'pending':{'previous':previous,'version':v2['version']}}
        packages._write_task(pending, previous['revision'])
        packages.recover()
        self.assertEqual(packages.task(pid)['active_version'],v2['version'])
        self.assertNotIn('pending',packages.task(pid))

    def test_import_preserves_identity_and_shadows_deleted_git_task(self):
        source = self.jobs/'legacy'/'existing'; source.mkdir(parents=True)
        (source/'main.py').write_text('print("legacy")')
        (source/'.wfs-task.json').write_text(json.dumps({'task_id':'stable_existing'}))
        task_loader.invalidate_task_cache()
        data = packages.import_task('stable_existing','admin')
        self.assertEqual(task_loader.discover_task_specs()[0]['task_dir'],source)
        data = self.ready(data)
        self.activate(data)
        self.assertEqual(len(task_loader.discover_task_specs()),1)
        deleted = packages.recycle(data['pid'],packages.task(data['pid'])['revision'],'admin')
        self.assertTrue((source/'main.py').exists())
        self.assertFalse(task_loader.discover_task_specs())
        packages.recycle(data['pid'],deleted['revision'],'admin',True)
        self.assertEqual(task_loader.discover_task_specs()[0]['pid'],'stable_existing')

    def test_offline_dependency_failure_cannot_publish(self):
        data = self.new({'main.py':'print(1)','requirements.txt':'nonexistent_wfs_package==1.0.0'})
        packages.prepare(data['pid'],data['version'])
        deadline = time.monotonic()+30
        while packages.release(data['pid'],data['version'])['status'] == 'preparing' and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertEqual(packages.release(data['pid'],data['version'])['status'],'failed')
        with self.assertRaises(packages.PackageError):
            self.activate(data)
        self.assertFalse(task_loader.discover_task_specs())

    def test_bundled_offline_wheel_is_installed_in_version_environment(self):
        wheel_files = {
            'package_demo/__init__.py': 'value="OFFLINE_WHEEL_OK"\n',
            'package_demo-1.0.0.dist-info/METADATA': 'Metadata-Version: 2.1\nName: package-demo\nVersion: 1.0.0\n',
            'package_demo-1.0.0.dist-info/WHEEL': 'Wheel-Version: 1.0\nGenerator: acceptance\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
        }
        record = 'package_demo-1.0.0.dist-info/RECORD'
        wheel_files[record] = ''.join(name + ',,\n' for name in [*wheel_files,record])
        data = self.ready(self.new({'main.py':'from package_demo import value\nprint(value)\n',
                                    'requirements.txt':'package-demo==1.0.0\n',
                                    'wheels/package_demo-1.0.0-py3-none-any.whl':archive(wheel_files)}))
        self.activate(data)
        spec = task_loader.discover_task_specs()[0]
        self.assertEqual(core.execute_py(spec['main_file_path'],spec['pid'],python_executable=spec['python_executable']),0)
        from app.bootstrap.operations import list_runs
        self.assertIn('OFFLINE_WHEEL_OK', read_log(list_runs(spec['pid'])[0]['run_id'])['content'])

    def test_multipart_csrf_permissions_download_and_proxy(self):
        base = '/api/taskinfo/packages'
        response = self.client.post(base+'/upload', data={'package':(io.BytesIO(archive({'main.py':'print(1)'})),'demo.zip')})
        self.assertEqual(response.status_code,403)
        response = self.client.post(base+'/upload', headers=self.headers, data={'package':(io.BytesIO(archive({'main.py':'print(1)'})),'demo.zip'),
                                    'task_name':'Demo','group_name':'examples','folder_name':'api'})
        self.assertEqual(response.status_code,200,response.json)
        data = response.json['data']
        download = self.client.get(base+'/download',query_string={'pid':data['pid'],'version':data['version']})
        self.assertEqual(download.status_code,200)
        self.assertIn('main.py',zipfile.ZipFile(io.BytesIO(download.data)).namelist())
        from app.bootstrap.permissions import allowed
        self.assertFalse(allowed(base+'/upload','POST','operator'))
        self.assertFalse(allowed(base+'/action','POST','viewer'))
        self.assertTrue(allowed(base,'GET','viewer'))
        with patch('app.api.task.views._scheduler_control_enabled',return_value=True), patch('app.api.task_packages.requests.request') as proxy:
            proxy.return_value.headers = {'Content-Type':'application/json'}
            proxy.return_value.json.return_value = {'code':20000,'data':{}}
            proxy.return_value.status_code = 200
            response = self.client.post(base+'/upload',headers=self.headers,data={'package':(io.BytesIO(archive({'main.py':'print(2)'})),'demo.zip')})
            self.assertEqual(response.status_code,200)
            self.assertIn(b'PK',proxy.call_args.kwargs['data'])
            self.assertIn('multipart/form-data',proxy.call_args.kwargs['headers']['Content-Type'])
            self.assertEqual(proxy.call_args.kwargs['headers']['X-CSRF-Token'],self.headers['X-CSRF-Token'])


if __name__ == '__main__':
    unittest.main()
