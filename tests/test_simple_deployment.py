"""Deployment safety and ordering without touching services or production databases."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import deploy
from scripts.service_config import read_environment


class SimpleDeploymentTests(unittest.TestCase):
    def values(self):
        return dict(WFS_SECRET_KEY='key-one', WFS_CONNECTIONS_KEY='key-two', WFS_ADMIN_PASSWORD_HASH='hash',
                    WFS_NACOS_URL='https://nacos.example/nacos', WFS_NACOS_USERNAME='operator',
                    WFS_NACOS_PASSWORD='secret', WFS_DB_ID='wfsscheduler_wfs', WFS_STATE_BACKEND='gauss', WFS_DB_DRIVER='DWS')

    def test_configuration_quotes_secrets_and_retry_preserves_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = 'Nacos # $ " \\ password'
            with patch('builtins.input', side_effect=['https://nacos.example/nacos', 'operator', '']), \
                 patch('getpass.getpass', side_effect=['a-long-admin-password', 'a-long-admin-password', secret]):
                path = deploy.configure(root)
            values, _ = read_environment(path)
            self.assertEqual(values['WFS_NACOS_PASSWORD'], secret)
            self.assertNotIn('a-long-admin-password', path.read_text(encoding='utf-8'))
            before = path.read_bytes()
            with patch('builtins.input', side_effect=AssertionError('must not prompt')), \
                 patch('getpass.getpass', side_effect=AssertionError('must not reset password')):
                deploy.configure(root)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotEqual(values['WFS_SECRET_KEY'], values['WFS_CONNECTIONS_KEY'])
            self.assertEqual(values['LD_LIBRARY_PATH'], (root/'app/config/driver/dws_odbc/lib').as_posix())

    def test_invalid_production_overrides_and_urls_rejected(self):
        for changes in ({'WFS_POSTGRES_TEST':'true'}, {'WFS_DB_DRIVER':'psycopg'},
                        {'WFS_NACOS_URL':'https://user:password@host/nacos'},
                        {'WFS_DB_ID':'bad'}, {'WFS_STATE_BACKEND':'sqlite'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                deploy.validate_values({**self.values(), **changes})

    def test_service_preflight_wont_overwrite_or_install_while_running(self):
        for state in ('active', 'activating', 'deactivating', 'reloading'):
            with patch.object(deploy, 'run', return_value=SimpleNamespace(stdout=state)), self.assertRaises(ValueError):
                deploy.assert_stopped()
        with patch.object(deploy, 'run', return_value=SimpleNamespace(stdout='inactive')):
            deploy.assert_stopped()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for unit in deploy.UNITS:
                (root/'deploy/root-test').mkdir(parents=True, exist_ok=True)
                (root/'units').mkdir(exist_ok=True)
                (root/'deploy/root-test'/unit).write_text('expected')
                (root/'units'/unit).write_text('other installation')
            with self.assertRaises(ValueError):
                deploy.assert_units_compatible(root, root/'units')

    def test_package_corruption_and_path_escape_fail_before_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'source').write_bytes(b'original')
            entry = {'path':'source', 'sha256':hashlib.sha256(b'original').hexdigest()}
            manifest = root/'PACKAGE-MANIFEST.json'
            manifest.write_text(json.dumps({'files':[entry]}))
            deploy.verify_package(root)
            (root/'source').write_bytes(b'changed')
            with self.assertRaises(ValueError): deploy.verify_package(root)
            for path in ('../outside', '/absolute', 'C:/private', 'a\\..\\private'):
                manifest.write_text(json.dumps({'files':[{**entry, 'path':path}]}))
                with self.assertRaises(ValueError): deploy.verify_package(root)

    def test_pip_has_no_implicit_public_fallback_and_offline_has_no_index(self):
        with patch.dict(os.environ, {'PIP_EXTRA_INDEX_URL':'https://pypi.org/simple', 'PIP_INDEX_URL':'https://elsewhere'}):
            environment = deploy.pip_environment()
        self.assertNotIn('PIP_EXTRA_INDEX_URL', environment)
        self.assertNotIn('PIP_INDEX_URL', environment)
        self.assertEqual(environment['PIP_CONFIG_FILE'], os.devnull)
        self.assertEqual(deploy.pip_options(deploy.DEFAULT_INDEX)[-2:], ['--trusted-host','nexus.immp.icbc'])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(deploy.pip_options('ignored', directory), ['--no-index','--find-links',str(Path(directory).resolve())])
        with self.assertRaises(ValueError): deploy.pip_options('https://user:secret@host/simple')

    def test_database_failure_cannot_install_or_start_services(self):
        args = SimpleNamespace(skip_dependencies=True)
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'app/dist').mkdir(parents=True)
                (root/'app/dist/index.html').write_text('built')
                events = []
                def database(*args, **kwargs):
                    events.append('database')
                    if fails: raise ValueError('database unavailable')
                with patch.object(deploy, 'ROOT', root), patch.object(deploy.sys, 'prefix', str(root/'.venv')), \
                     patch.object(deploy, 'verify_package'), patch.object(deploy, 'ensure_venv', return_value=root/'.venv/bin/python'), \
                     patch.object(deploy, 'configure'), patch.object(deploy, 'production_environment', return_value={}), \
                     patch.object(deploy, 'check_database', side_effect=database), \
                     patch.object(deploy, 'run', side_effect=lambda command, **kw: events.append('services' if '--install' in command else 'pip')), \
                     patch.object(deploy, 'ready', side_effect=lambda *args: events.append('ready')):
                    if fails:
                        with self.assertRaises(ValueError): deploy.install(args)
                        self.assertEqual(events, ['pip','database'])
                    else:
                        deploy.install(args)
                        self.assertEqual(events, ['pip','database','services','ready'])

    def test_read_only_check_never_initializes_schema(self):
        with patch.object(deploy, 'driver_check'), patch.object(deploy, 'run') as run:
            deploy.check_database(Path('/python'), {})
        commands = [' '.join(map(str, call.args[0])) for call in run.call_args_list]
        self.assertEqual(len(commands), 1)
        self.assertIn('check_gauss_platform.py', commands[0])

    @unittest.skipIf(os.name == 'nt', 'requires POSIX flock')
    def test_concurrent_installer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, deploy.deployment_lock(Path(directory)):
            with self.assertRaises(ValueError), deploy.deployment_lock(Path(directory)):
                pass


if __name__ == '__main__':
    unittest.main()
