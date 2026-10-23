"""Real task execution, nested project imports, isolated outputs and safe reads."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import closing

import test_local_integration
import test_task_packages as package_fixture
from test_task_packages import archive
from app.bootstrap import core, task_artifacts as artifacts, task_loader, global_vars
from app.bootstrap.operations import create_run, update_run, list_runs
from app.bootstrap.task_source import SourceError


class TaskArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = package_fixture.PackageTests()
        self.fixture.setUp()
        self.root = self.fixture.root / 'outputs-data'
        self.patches = [patch.object(artifacts, 'DATA_DIR', str(self.root)),
                        patch.object(global_vars, 'DATA_DIR', str(self.root))]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.fixture.tearDown()

    def output_run(self, pid='artifact-demo', status='success'):
        run_id = create_run(pid)
        update_run(run_id, status=status, output_layout='per-run-v1')
        _, _, directory = artifacts.output_directory(pid, run_id, create=True)
        return run_id, directory

    def test_nested_package_relative_imports_resources_and_two_run_outputs(self):
        files = {
            'batch/__init__.py': '', 'batch/helper.py': 'value = 42\n',
            'batch/main.py': '''from .helper import value
import json, os
from pathlib import Path
root = Path(os.environ['WFS_TASK_ROOT'])
assert Path.cwd().resolve() == root.resolve()
assert (root/'assets/input.txt').read_text() == 'resource'
out = Path(os.environ['WFS_OUTPUT_DIR'])/'reports'
out.mkdir()
(out/'summary.json').write_text(json.dumps({'value':value,'run':os.environ['WFS_RUN_ID']}))
(out/'report.csv').write_text('name,amount\\n"a,b",42\\n', encoding='utf-8')
(out/'report.log').write_text('<script>window.outputXss=true</script>', encoding='utf-8')
print('NESTED_OUTPUT_OK', value)
''', 'assets/input.txt': 'resource'}
        data = self.fixture.ready(task_loader_stage(files, 'batch/main.py'))
        self.fixture.activate(data)
        spec = task_loader.discover_task_specs()[0]
        roots = []
        for _ in range(2):
            self.assertEqual(core.execute_py(spec['main_file_path'], spec['pid'], python_executable=spec['python_executable']), 0)
            run_id = list_runs(spec['pid'])[0]['run_id']
            roots.append(artifacts.output_directory(spec['pid'], run_id)[2])
            preview = artifacts.preview_output(run_id, 'reports/summary.json')
            self.assertEqual(json.loads(preview['content'])['value'], 42)
            self.assertEqual(json.loads(preview['content'])['run'], run_id)
            self.assertEqual(artifacts.preview_output(run_id, 'reports/report.csv')['rows'][1], ['a,b', '42'])
        self.assertNotEqual(*roots)
        self.assertFalse((spec['task_dir'] / 'reports').exists())

    def test_preview_limits_permissions_download_and_streamed_html_attachment(self):
        run_id, directory = self.output_run()
        (directory/'report.csv').write_text('name,amount\n甲,7\n', encoding='utf-8-sig')
        (directory/'unsafe.html').write_text('<script>alert(1)</script>', encoding='utf-8')
        (directory/'huge.log').write_text('x\n'*200000)
        self.assertTrue(artifacts.preview_output(run_id, 'huge.log')['truncated'])
        self.assertLessEqual(len(artifacts.preview_output(run_id, 'huge.log')['content'].splitlines()), 2000)
        client = self.fixture.client
        self.assertEqual(client.get('/api/taskinfo/artifacts', query_string={'run_id': run_id}).status_code, 200)
        with closing(client.get('/api/taskinfo/artifact-download', query_string={'run_id': run_id, 'file': 'unsafe.html'})) as downloaded:
            self.assertEqual(downloaded.status_code, 200)
            self.assertTrue(downloaded.headers['Content-Disposition'].startswith('attachment;'))
            self.assertIn('application/octet-stream', downloaded.headers['Content-Type'])
            self.assertEqual(downloaded.headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn('no-store', downloaded.headers['Cache-Control'])
            self.assertIn(b'<script>', downloaded.data)
        from app.bootstrap.database import GaussDB
        from app.settings import AUTH_ADMIN_PASSWORD_HASH
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)',
                           params=('output-viewer', AUTH_ADMIN_PASSWORD_HASH, 'viewer'))
        viewer = self.fixture.app.test_client()
        self.assertEqual(viewer.get('/api/taskinfo/artifacts', query_string={'run_id':run_id}).status_code, 401)
        login = viewer.post('/api/user/login', json={'username':'output-viewer','password':'test-password'})
        self.assertEqual(viewer.get('/api/taskinfo/artifacts', query_string={'run_id':run_id, 'file':'report.csv'}).status_code, 200)
        self.assertEqual(viewer.post('/api/taskinfo/artifacts', headers={'X-CSRF-Token':login.json['data']['csrf_token']}).status_code, 403)
        update_run(run_id, status='running')
        self.assertEqual(client.get('/api/taskinfo/artifact-download', query_string={'run_id':run_id,'file':'report.csv'}).status_code, 409)

    def test_output_path_traversals_links_and_run_boundaries(self):
        run_id, directory = self.output_run()
        another, other = self.output_run('other-task')
        (other/'secret.txt').write_text('not this run')
        for name in ['../secret.txt','/etc/passwd','..\\secret.txt','C:secret.txt','a/../../secret.txt']:
            with self.subTest(name=name), self.assertRaises(SourceError):
                artifacts.preview_output(run_id,name)
        with self.assertRaises(SourceError):
            artifacts.preview_output('invalid', 'secret.txt')
        os.link(other/'secret.txt', directory/'hardlink.txt')
        with self.assertRaises(SourceError):
            artifacts.preview_output(run_id,'hardlink.txt')
        self.assertEqual(artifacts.list_outputs(run_id)['entries'], [])
        try:
            (directory/'link.txt').symlink_to(other/'secret.txt')
        except OSError:
            pass  # Windows requires Developer Mode for symlinks; hard-link protection is still exercised.
        else:
            with self.assertRaises(SourceError):
                artifacts.preview_output(run_id,'link.txt')
        for index in range(205):
            (directory/f'{index:03}.txt').write_text(str(index))
        self.assertTrue(artifacts.list_outputs(run_id)['has_more'])
        self.assertEqual(len(artifacts.list_outputs(run_id, offset=200)['entries']), 5)

    def test_archive_directory_choices_and_nested_requirements_are_explicit(self):
        from app.bootstrap import task_packages as packages
        package = task_loader_stage({'pkg/__init__.py':'','pkg/main.py':'print(1)'}, '')
        self.assertIn('pkg/main.py', {item['path'] for item in package['manifest']})
        files = {'export/tools/main.py':'print(2)', 'export/assets/input.txt':'sample'}
        preserved = task_loader_stage(files, 'export/tools/main.py', 'preserve', 'preserve')
        self.assertIn('export/assets/input.txt', {item['path'] for item in preserved['manifest']})
        stripped = task_loader_stage(files, 'tools/main.py', 'strip', 'strip')
        self.assertIn('assets/input.txt', {item['path'] for item in stripped['manifest']})
        with self.assertRaises(packages.PackageError):
            task_loader_stage({'a/main.py':'print(1)', 'b/input.txt':'x'}, '', 'strip', 'bad-strip')
        with self.assertRaisesRegex(packages.PackageError, 'requirements.txt'):
            task_loader_stage({'src/main.py':'print(1)', 'src/requirements.txt':'requests==2.32.0'}, 'src/main.py', 'preserve', 'deps')


def task_loader_stage(files, entry='', layout='auto', folder='nested-output'):
    from app.bootstrap import task_packages as packages
    return packages.stage(archive(files), {'task_name':'Nested outputs', 'group_name':'artifacts',
                          'folder_name':folder,'main_file':entry,'archive_layout':layout}, 'admin')
