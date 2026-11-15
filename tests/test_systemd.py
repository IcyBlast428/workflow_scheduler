"""Service startup/configuration checks without changing the host service manager."""
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shlex
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.install_systemd import render, assert_legacy_scheduler_retired
from scripts import install_systemd
from scripts.service_config import read_environment, serialize_environment
from scripts.wait_ready import wait


class SystemdTests(unittest.TestCase):
    def test_role_fencing_loopback_and_process_cleanup(self):
        for scope in ('user',):
            units = render(scope=scope, unset=('WFS_LOCAL_DB_PATH',))
            scheduler = next(value for name, value in units.items() if 'scheduler' in name)
            web = next(value for name, value in units.items() if 'scheduler' not in name)
            for role, content, workers in (('scheduler', scheduler, '1'), ('web', web, '2')):
                command = shlex.split(next(line.split('=', 1)[1] for line in content.splitlines() if line.startswith('ExecStart=')))
                self.assertEqual(command[command.index('--workers') + 1], workers)
                self.assertEqual(command[command.index('--bind') + 1].split(':')[0], '127.0.0.1')
                self.assertIn('WFS_ENABLE_SCHEDULER=' + ('true' if role == 'scheduler' else 'false'), command)
                self.assertIn('WFS_SCHEDULER_CONTROL_URL=' + ('' if role == 'scheduler' else 'http://127.0.0.1:8009'), command)
                self.assertIn('KillMode=mixed', content)
                self.assertIn('Restart=on-failure', content)
                self.assertIn('ExecStartPost=', content)
                self.assertIn('GUNICORN_CMD_ARGS', content)
                self.assertNotIn('User=',content)
                self.assertNotIn('Group=',content)
                self.assertNotIn('ExecStartPre=',content)
                self.assertIn('WorkingDirectory=/data/workflow_scheduler\n', content)
                self.assertIn('EnvironmentFile=/data/workflow_scheduler/deploy/root-test/runtime.env\n', content)
            self.assertIn('Requires=', web)

    def test_production_paths_http_cookies_and_committed_units_match(self):
        root = Path(__file__).resolve().parents[1]
        for name, content in render().items():
            self.assertEqual((root/name).read_text(), content)
            command = shlex.split(next(line.split('=', 1)[1] for line in content.splitlines() if line.startswith('ExecStart=')))
            self.assertEqual(command[command.index('--data') + 1], '/data/workflow_scheduler/data')
            self.assertEqual(command[command.index('--logs') + 1], '/data/workflow_scheduler/logs')
            self.assertIn('User=root\nGroup=root\n',content)
            self.assertEqual(command[command.index('--web-host')+1],'0.0.0.0')
            self.assertIn('Environment=WFS_STATE_BACKEND=gauss',content)
            preflight=shlex.split(next(line.split('=',1)[1] for line in content.splitlines() if line.startswith('ExecStartPre=')))
            self.assertEqual(preflight,[command[0],'/data/workflow_scheduler/scripts/check_gauss_platform.py'])
            self.assertNotIn('Environment="ODBC',content)
            self.assertIn('Environment=WFS_COOKIE_SECURE=false', content)
            self.assertIn('scripts/serve.py', command[1])
            self.assertIn('Conflicts=wfs-scheduler.service', content)
            self.assertNotIn('Requires=wfs-scheduler.service', content)
            self.assertIn('/data/workflow_scheduler/scripts/wait_ready.py', content)
            self.assertNotIn('/data/wfs', content)
        for content in render(https_proxy=True).values():
            self.assertIn('WFS_COOKIE_SECURE=true', content)
        custom = render(project='/srv/custom-project')
        for content in custom.values():
            self.assertNotIn('/data/workflow_scheduler', content)
            self.assertIn('/srv/custom-project/data', content)
            self.assertIn('EnvironmentFile=/srv/custom-project/deploy/root-test/runtime.env', content)

    def test_system_profile_is_one_service_and_old_scheduler_must_be_retired(self):
        self.assertEqual(list(render()), ['wfs.service'])
        for active, enabled, rejected in [('active','disabled',True), ('inactive','enabled',True),
                                           ('activating','disabled',True), ('inactive','disabled',False),
                                           ('inactive','',False)]:
            replies = [SimpleNamespace(returncode=0, stdout=active), SimpleNamespace(returncode=0, stdout=enabled)]
            with self.subTest(active=active, enabled=enabled), patch('scripts.install_systemd.subprocess.run', side_effect=replies):
                if rejected:
                    with self.assertRaises(ValueError): assert_legacy_scheduler_retired()
                else:
                    assert_legacy_scheduler_retired()

    def test_service_account_cannot_select_the_retired_profile(self):
        for option in ('--user','--group'):
            with self.subTest(option=option), patch('sys.argv',['install_systemd.py',option,'wfs','--output','unused']), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    install_systemd.main()
                self.assertEqual(result.exception.code,2)

    def test_literal_environment_roundtrip_and_no_shell_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'secret.env'
            expected = {'WFS_SECRET_KEY': 'a$hash"with\\slashes and \'quotes', 'WFS_ADMIN_PASSWORD_HASH': 'scrypt:32768:8:1$salt$digest'}
            path.write_text('unset WFS_LOCAL_DB_PATH\n' + ''.join(f'{key}={shlex.quote(value)}\n' for key, value in expected.items()))
            values, removed = read_environment(path)
            self.assertEqual(values, expected)
            self.assertEqual(removed, {'WFS_LOCAL_DB_PATH'})
            path.write_text(serialize_environment(values))
            self.assertEqual(read_environment(path)[0], expected)
            marker = Path(directory)/'must-not-exist'
            path.write_text(f'WFS_SECRET_KEY=$(touch {marker})\n')
            with self.assertRaises(ValueError): read_environment(path)
            self.assertFalse(marker.exists())

    def test_readiness_requires_real_ready_and_does_not_log_remote_body(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                calls.append(1)
                payload = json.dumps({'data': {'ready': len(calls) >= 3}}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(payload)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_address[1]) + '/api/user/ready'
            self.assertTrue(wait(url, timeout=2, interval=.01))
            self.assertGreaterEqual(len(calls), 3)
        finally:
            server.shutdown(); server.server_close()
        capture = io.StringIO()
        with redirect_stderr(capture):
            self.assertFalse(wait(url, timeout=.03, interval=.01))
        self.assertIn('Readiness timed out', capture.getvalue())
        with self.assertRaises(ValueError): wait('http://outside.example/ready', timeout=.03)


if __name__ == '__main__':
    unittest.main()
