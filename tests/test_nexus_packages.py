"""Real local Simple API: dependency resolution, isolated venv and failed publish."""
import base64
import http.server
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import test_task_packages as package_tests
from test_task_packages import archive
from app.bootstrap import task_packages as packages, task_publishing as settings
from app.bootstrap import task_loader, core


class NexusPackageTests(unittest.TestCase):
    new = package_tests.PackageTests.new
    ready = package_tests.PackageTests.ready
    activate = package_tests.PackageTests.activate

    def setUp(self):
        package_tests.PackageTests.setUp(self)
        self.settings_env = patch.dict(os.environ, {'WFS_DATA_DIR':str(self.root/'settings')})
        self.settings_env.start()
        self.web = self.root/'repository'
        self.auth = None
        self.requests = []
        owner = self
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(owner.web), **kwargs)
            def do_GET(self):
                owner.requests.append(self.path)
                if owner.auth and self.headers.get('Authorization') != owner.auth:
                    self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="test"'); self.end_headers(); return
                super().do_GET()
            def log_message(self, *args):
                pass
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.index = f'http://127.0.0.1:{self.server.server_port}/repository/pypi-hosted'
        self.wheel('guide_leaf', "value='NEXUS_TRANSITIVE_OK'\n")
        self.wheel('guide_parent', 'from guide_leaf import value\n', requires='guide-leaf>=1,<2')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.settings_env.stop()
        package_tests.PackageTests.tearDown(self)

    def wheel(self, name, source, requires=''):
        info = name+'-1.0.0.dist-info'
        files = {name+'/__init__.py':source,
                 info+'/METADATA':f'Metadata-Version: 2.1\nName: {name.replace("_","-")}\nVersion: 1.0.0\n'+(f'Requires-Dist: {requires}\n' if requires else ''),
                 info+'/WHEEL':'Wheel-Version: 1.0\nGenerator: acceptance\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}
        files[info+'/RECORD'] = ''.join(path+',,\n' for path in [*files,info+'/RECORD'])
        folder = self.web/'repository/pypi-hosted'
        (folder/'packages').mkdir(parents=True,exist_ok=True)
        filename = name+'-1.0.0-py3-none-any.whl'
        (folder/'packages'/filename).write_bytes(archive(files))
        simple = folder/'simple'/name.replace('_','-')
        simple.mkdir(parents=True,exist_ok=True)
        (simple/'index.html').write_text(f'<a href="../../packages/{filename}">{filename}</a>',encoding='utf-8')

    def configure(self, **options):
        return settings.save_repository(dict(mode='nexus',index_url=self.index,username='',password='',
                                             revision=settings.repository()['revision'], **options))

    def test_nexus_resolves_indirect_dependencies_and_reuses_published_environment(self):
        self.configure()
        with patch.dict(os.environ, {'PIP_EXTRA_INDEX_URL':'http://127.0.0.1:1/never-use-this'}):
            data = self.ready(self.new({'main.py':'from guide_parent import value\nprint(value)\n',
                                       'requirements.txt':'guide-parent>=1,<2\n'}))
        self.assertEqual(data['dependency_source']['mode'],'nexus')
        root = packages.release_dir(data['pid'],data['version'])
        locked = (root/'dependencies.lock.txt').read_text(encoding='utf-8')
        self.assertIn('guide-leaf==1.0.0',locked)
        self.assertIn('guide-parent==1.0.0',locked)
        self.activate(data)
        spec = task_loader.discover_task_specs()[0]
        interpreter = spec['python_executable']
        count = len(self.requests)
        for _ in range(2):
            self.assertEqual(core.execute_py(spec['main_file_path'],spec['pid'],python_executable=interpreter),0)
        self.assertEqual(len(self.requests),count,'Execution must not reinstall or contact Nexus')
        # Other versions do not inherit this version's third-party packages.
        other = self.ready(self.new({'main.py':'print("stdlib only")'},folder='other'))
        self.assertNotEqual(other['python'], data['python'])

    def test_nexus_conflicting_dependencies_cannot_publish(self):
        self.configure()
        data = self.new({'main.py':'print(1)', 'requirements.txt':'guide-parent==1.0.0\nguide-leaf==2.0.0\n'})
        packages.prepare(data['pid'],data['version'])
        import time
        deadline = time.monotonic()+90
        while packages.release(data['pid'],data['version'])['status']=='preparing' and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertEqual(packages.release(data['pid'],data['version'])['status'],'failed')
        with self.assertRaises(packages.PackageError):
            self.activate(data)

    def test_authenticated_index_uses_temporary_netrc_and_keeps_credentials_out_of_release(self):
        username, password = 'reader', 'private-test-password'
        self.auth = 'Basic '+base64.b64encode(f'{username}:{password}'.encode()).decode()
        value = settings.repository()
        settings.save_repository(dict(value,mode='nexus',index_url=self.index,username=username,password=password))
        data = self.ready(self.new({'main.py':'print(1)', 'requirements.txt':'guide-parent==1.0.0\n'}))
        root = packages.release_dir(data['pid'],data['version'])
        self.assertNotIn(password,(root/'prepare.log').read_text(encoding='utf-8'))
        self.assertNotIn(password,str(data))
        self.assertFalse(list(root.rglob('credentials')))
