import importlib.util
import os
import sys
from pathlib import Path
import shlex
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('root_test_setup', ROOT/'scripts/setup_root_test.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
check_spec = importlib.util.spec_from_file_location('gauss_check', ROOT/'scripts/check_gauss_platform.py')
gauss_check = importlib.util.module_from_spec(check_spec)
check_spec.loader.exec_module(gauss_check)


class RootTestDeploymentTests(unittest.TestCase):
    def test_initialization_hashes_password_and_preserves_credentials_on_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, created = setup.initialize(Path(temporary), 'a-strong-test-password')
            self.assertTrue(created)
            content = config.read_text()
            values = dict(line.split('=', 1) for line in content.splitlines())
            self.assertTrue(check_password_hash(values['WFS_ADMIN_PASSWORD_HASH'], 'a-strong-test-password'))
            self.assertNotIn('a-strong-test-password', content)
            self.assertNotEqual(values['WFS_SECRET_KEY'], values['WFS_CONNECTIONS_KEY'])
            self.assertNotIn('WFS_LOCAL_DB_PATH', values)
            self.assertEqual(values['WFS_DB_ID'], 'immpdb_wfs')
            self.assertEqual(values['WFS_DB_DRIVER'], 'DWS')
            self.assertFalse(setup.initialize(Path(temporary), 'replacement-password')[1])
            self.assertEqual(content, config.read_text())

    def test_empty_password_creates_no_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                setup.initialize(Path(temporary), '')
            self.assertFalse((Path(temporary)/'deploy/root-test/runtime.env').exists())

    def test_service_supervises_both_roles_with_existing_paths_and_listener(self):
        text = (ROOT/'wfs.service').read_text()
        self.assertFalse((ROOT/'deploy/root-test/wfs.service').exists())
        self.assertIn('User=root\nGroup=root', text)
        self.assertIn('WorkingDirectory=/data/workflow_scheduler\n', text)
        self.assertIn('EnvironmentFile=/data/workflow_scheduler/deploy/root-test/runtime.env', text)
        command = shlex.split(next(line.split('=',1)[1] for line in text.splitlines() if line.startswith('ExecStart=')))
        self.assertEqual(command[0], '/data/workflow_scheduler/.venv/bin/python')
        self.assertEqual(command[1], '/data/workflow_scheduler/scripts/serve.py')
        self.assertEqual(command[command.index('--web-host')+1], '0.0.0.0')
        self.assertEqual(command[command.index('--data')+1], '/data/workflow_scheduler/data')
        self.assertIn('Conflicts=wfs-scheduler.service', text)
        self.assertNotIn('Requires=wfs-scheduler.service', text)
        self.assertFalse((ROOT/'deploy/root-test/wfs-scheduler.service').exists())
        self.assertIn('ExecStartPost=', text)
        self.assertIn('scripts/check_gauss_platform.py', text)

    @unittest.skipIf(os.name=='nt','Linux installation path')
    def test_installer_copies_only_root_template_and_preserves_runtime_configuration(self):
        from scripts import install_systemd, service_config
        with tempfile.TemporaryDirectory() as temporary:
            project=Path(temporary);units=project/'system-units';units.mkdir()
            python=project/'.venv/bin/python';python.parent.mkdir(parents=True);python.touch()
            expected=(ROOT/'wfs.service').read_bytes();(project/'wfs.service').write_bytes(expected)
            config,_=setup.initialize(project,'a-strong-test-password')
            config.write_text(config.read_text().replace('CHANGE_ME','configured-test-value'))
            before=config.read_bytes()
            # An older unpacked archive must not become another installation source.
            (project/'deploy/root-test/wfs.service').write_text('User=wfs\nGroup=wfs\n')
            with patch.object(setup,'PROJECT',project), patch.object(setup,'UNIT_DIR',units), \
                 patch.object(setup,'__file__',str(project/'scripts/setup_root_test.py')), \
                 patch.object(os,'geteuid',return_value=0), \
                 patch.dict(sys.modules,{'install_systemd':install_systemd,'service_config':service_config}), \
                 patch.object(install_systemd,'assert_legacy_scheduler_retired'), \
                 patch.object(setup.subprocess,'run') as run, \
                 patch.object(sys,'argv',['setup_root_test.py','--install']):
                setup.main()
            self.assertEqual((units/'wfs.service').read_bytes(),expected)
            self.assertEqual([p.name for p in units.iterdir()],['wfs.service'])
            self.assertEqual(config.read_bytes(),before)
            commands=[call.args[0] for call in run.call_args_list]
            self.assertIn('check_gauss_platform.py',commands[0][-1])
            self.assertEqual(commands[1:],[['systemctl','daemon-reload'],['systemctl','enable','wfs.service'],['systemctl','restart','wfs.service']])

    def test_gauss_check_is_read_only_and_rejects_other_platforms(self):
        class Database:
            dialect = 'GaussDB/DWS'
            queries = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute_query_sql(self, sql):
                self.queries.append(sql)
                return [(1,)] if sql=='SELECT version FROM wfs_schema_version' else []
        database = Database()
        with patch.dict('os.environ', {'WFS_STATE_BACKEND':'gauss'}), patch.dict('sys.modules', {'app.bootstrap.database': SimpleNamespace(GaussDB=lambda: database)}):
            gauss_check.main()
            self.assertEqual(len(database.queries), 33)
            self.assertTrue(all(query.startswith('SELECT 1 FROM wfs_') and query.endswith('LIMIT 0') for query in database.queries[:-1]))
            database.dialect='PostgreSQL'
            with self.assertRaises(RuntimeError): gauss_check.main()
