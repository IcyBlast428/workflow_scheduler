"""Test DB host routing stays isolated, including profiles and schema cleanup."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import test_database


class TestDatabaseConfigTests(unittest.TestCase):
    def test_ci_service_host_and_port_with_fixed_disposable_identity(self):
        environment = dict(WFS_CI_POSTGRES='true', PGDATABASE='wfstest', PGHOST='postgres',
                           PGPORT='5434', PGPASSWORD='test-only', PGUSER='must-not-be-used')
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(test_database.connection_options(),
                             dict(host='postgres', port=5434, dbname='wfstest', user='wfstest', password='test-only'))
            del os.environ['PGHOST']
            self.assertEqual(test_database.connection_options()['host'], '127.0.0.1')

    def test_ci_rejects_other_databases_and_invalid_hosts_before_connecting(self):
        environment = dict(WFS_CI_POSTGRES='true', PGDATABASE='wfstest', PGPASSWORD='test-only')
        for change in ({'PGDATABASE':'production'}, {'PGDATABASE':''}, {'PGHOST':'postgres\nhost=outside'},
                       {'PGHOST':'postgres,another'}, {'PGHOST':''}, {'PGPORT':'0'}, {'PGPORT':'65536'}):
            with self.subTest(change=change), patch.dict(os.environ, {**environment, **change}, clear=True):
                with self.assertRaises(ValueError):
                    test_database.connection_options()

    def test_local_runs_ignore_inherited_ci_connection_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data/gauss-dev').mkdir(parents=True)
            (root/'data/gauss-dev/environment.json').write_text(json.dumps({'WFS_DB_PASSWORD':'local-only'}))
            with patch.object(test_database, 'ROOT', root), patch.dict(os.environ, {
                'PGHOST':'unrelated-server', 'PGPORT':'5432', 'PGDATABASE':'production', 'PGPASSWORD':'wrong'
            }, clear=True):
                self.assertEqual(test_database.connection_options(),
                                 dict(host='127.0.0.1', port=15433, dbname='wfstest', user='wfstest', password='local-only'))

    def test_schema_setup_business_profiles_and_cleanup_share_the_ci_host(self):
        import psycopg
        from scripts import init_database
        environment = dict(WFS_CI_POSTGRES='true', PGDATABASE='wfstest', PGHOST='postgres', PGPASSWORD='test-only')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment, clear=True), \
             patch.object(init_database, 'initialize') as initialize, \
             patch.object(test_database.atexit, 'register') as register, \
             patch.object(psycopg, 'connect', return_value=MagicMock()) as connect:
            test_database.configure(Path(directory))
            initialize.assert_called_once_with()
            profile = test_database.business_profile()
            self.assertEqual((profile['host'],profile['database'],profile['port']), ('postgres','wfstest',5432))
            self.assertIn('host=postgres', (Path(directory)/'database.ini').read_text())
            cleanup = register.call_args.args[0]
            cleanup()
            self.assertEqual(connect.call_args.kwargs,
                             dict(host='postgres',port=5432,dbname='wfstest',user='wfstest',password='test-only',autocommit=True))
            statement = connect.return_value.__enter__.return_value.execute.call_args.args[0]
            self.assertRegex(statement, r'^DROP SCHEMA IF EXISTS test_[a-f0-9]{16} CASCADE$')


if __name__ == '__main__':
    unittest.main()
