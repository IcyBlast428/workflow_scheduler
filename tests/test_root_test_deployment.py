import importlib.util
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
            self.assertEqual(values['WFS_DB_ID'], 'wfsscheduler_wfs')
            self.assertEqual(values['WFS_DB_DRIVER'], 'DWS')
            self.assertFalse(setup.initialize(Path(temporary), 'replacement-password')[1])
            self.assertEqual(content, config.read_text())

    def test_empty_password_creates_no_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                setup.initialize(Path(temporary), '')
            self.assertFalse((Path(temporary)/'deploy/root-test/runtime.env').exists())

    def test_services_pin_roles_and_share_environment_and_data(self):
        for role, name in [('web','wfs.service'), ('scheduler','wfs-scheduler.service')]:
            text = (ROOT/'deploy/root-test'/name).read_text()
            self.assertIn('User=root\nGroup=root',text)
            self.assertIn('WorkingDirectory=/data/workflow_scheduler\n',text)
            self.assertIn('EnvironmentFile=/data/workflow_scheduler/deploy/root-test/runtime.env',text)
            command = shlex.split(next(line.split('=',1)[1] for line in text.splitlines() if line.startswith('ExecStart=')))
            self.assertEqual(command[0], '/data/workflow_scheduler/.venv/bin/python')
            self.assertEqual(command[command.index('--workers')+1], '1' if role=='scheduler' else '2')
            self.assertEqual(command[command.index('--bind')+1], '127.0.0.1:8009' if role=='scheduler' else '0.0.0.0:8008')
            self.assertIn('WFS_ENABLE_SCHEDULER='+('true' if role=='scheduler' else 'false'), command)
            self.assertIn('WFS_DATA_DIR=/data/workflow_scheduler/data',command)
            self.assertIn('ExecStartPost=', text)
            self.assertIn('scripts/check_gauss_platform.py', text)

    def test_gauss_check_is_read_only_and_rejects_other_platforms(self):
        class Database:
            _mysql = False
            _local_sqlite = False
            dialect = 'GaussDB/DWS'
            queries = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute_query_sql(self, sql): self.queries.append(sql)
        database = Database()
        with patch.dict('sys.modules', {'app.bootstrap.database': SimpleNamespace(GaussDB=lambda: database)}):
            gauss_check.main()
            self.assertEqual(len(database.queries), 20)
            self.assertTrue(all(query.startswith('SELECT 1 FROM wfs_') and query.endswith('LIMIT 0') for query in database.queries))
            database._local_sqlite = True
            with self.assertRaises(RuntimeError): gauss_check.main()
