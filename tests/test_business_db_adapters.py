"""Driver contracts only: URL/TLS, SQL binding and transaction ownership.

The DWS dialect uses an in-memory DBAPI double below, not a DWS server. Actual
vendor integrations must be tested with their server/driver versions.
"""
import sqlite3
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from sqlalchemy.dialects.mysql.pymysql import MySQLDialect_pymysql
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlalchemy import create_engine
from sqlalchemy.dialects import registry
from app.common.db.adapters import GaussDBAdapter
from app.common.db.dws_dialect import DWSDialect
from app.common.db.catalog import capabilities


class BusinessDatabaseAdapterTests(unittest.TestCase):
    config = dict(id='reports', host='database.internal', port=8000, database='reports',
                  user='name@host', password='secret;PWD={value}', tls='disabled')

    def test_dws_escapes_odbc_values_and_keeps_parameters_separate(self):
        adapter = GaussDBAdapter(self.config)
        url = adapter.build_url()
        self.assertNotIn(self.config['password'], str(url))
        args, kwargs = DWSDialect().create_connect_args(url)
        self.assertIn('PWD={secret;PWD={value}}}', args[0])
        self.assertIn('SERVERNAME={database.internal}', args[0])
        self.assertFalse(kwargs['autocommit'])
        self.assertEqual(kwargs['timeout'], 5)
        ssl_url = GaussDBAdapter(dict(self.config, tls='require')).build_url()
        self.assertEqual(ssl_url.query['sslmode'], 'require')

    def test_dws_dialect_executes_portable_sql_and_transaction_rollback(self):
        registry.register('wfs_dws.pyodbc', 'app.common.db.dws_dialect', 'DWSDialect')
        engine = create_engine('wfs_dws+pyodbc://', module=sqlite3,
                               creator=lambda: sqlite3.connect(':memory:'))
        self.addCleanup(engine.dispose)
        adapter = GaussDBAdapter(dict(self.config, dialect='gaussdb'))
        with patch.object(adapter, 'get_engine', return_value=engine):
            adapter.execute_single_sql('CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)')
            with adapter.transaction():
                adapter.execute_single_sql('INSERT INTO sample VALUES (?, ?)', (1, '中文;50%'))
            with self.assertRaises(Exception):
                with adapter.transaction():
                    adapter.execute_single_sql('INSERT INTO sample VALUES (?, ?)', (2, 'rollback'))
                    adapter.execute_single_sql('INSERT INTO sample VALUES (?, ?)', (1, 'duplicate'))
            self.assertEqual(adapter.execute_query_sql('SELECT * FROM sample', return_json=True),
                             [{'id': 1, 'value': '中文;50%'}])

    def test_postgresql_dollar_quotes_and_mysql_comments_do_not_consume_parameters(self):
        sql, params, native = SQLAlchemyAdapter._prepare_statement(
            "SELECT $$literal ? ' quote$$, $tag$?$tag$, ?", (5,), 'postgresql')
        self.assertEqual(sql, "SELECT $$literal ? ' quote$$, $tag$?$tag$, :wfs_bind_0")
        self.assertEqual(params, {'wfs_bind_0': 5})
        self.assertFalse(native)
        sql, params, native = SQLAlchemyAdapter._prepare_statement('SELECT ? # comment ?\n', (2,), 'mysql')
        self.assertEqual(sql, 'SELECT :wfs_bind_0 # comment ?\n')
        self.assertEqual(params, {'wfs_bind_0': 2})

    def test_colon_text_in_literals_and_comments_is_not_a_bound_parameter(self):
        from sqlalchemy import text
        for dialect_name, dialect, sql in (
            ('postgresql', PGDialect_psycopg(), "SELECT ' :literal' AS x, ? AS y -- :comment"),
            ('mysql', MySQLDialect_pymysql(), "SELECT ' :literal' AS x, ? AS y /* :comment */"),
            ('gaussdb', DWSDialect(), "SELECT ' :literal' AS x, ? AS y /* :comment */"),
        ):
            with self.subTest(dialect=dialect_name):
                statement, values, native = SQLAlchemyAdapter._prepare_statement(sql, (7,), dialect_name)
                compiled = text(statement).compile(dialect=dialect)
                self.assertEqual(set(compiled.params), {'wfs_bind_0'})
                self.assertEqual(values, {'wfs_bind_0': 7})
                self.assertIn(':literal', str(compiled))
                self.assertIn(':comment', str(compiled))
                self.assertNotIn('\\:literal', str(compiled))
                self.assertFalse(native)

    def test_dws_health_ping_is_read_only_and_closes_cursor_on_error(self):
        connection = Mock()
        dialect = DWSDialect()
        self.assertTrue(dialect.do_ping(connection))
        connection.cursor.return_value.execute.assert_called_once_with('SELECT 1')
        connection.cursor.return_value.close.assert_called_once()
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()
        connection.reset_mock()
        connection.cursor.return_value.execute.side_effect = RuntimeError('disconnected')
        with self.assertRaises(RuntimeError):
            dialect.do_ping(connection)
        connection.cursor.return_value.close.assert_called_once()
        self.assertTrue(dialect.is_disconnect(Exception('08006', 'connection lost'), connection, None))
        self.assertFalse(dialect.is_disconnect(Exception('HYT00', 'statement timeout'), connection, None))

    def test_odbc_factory_disables_driver_pool_before_any_task_connection(self):
        from app.common.db.factory import adapter_for
        fake_driver = SimpleNamespace(pooling=True)
        with patch.dict('sys.modules', {'pyodbc': fake_driver}), \
                patch('importlib.util.find_spec', return_value=object()):
            adapter = adapter_for(dict(self.config, dialect='gaussdb'))
            self.assertFalse(fake_driver.pooling)
            self.assertIsNone(adapter._engine)
            fake_driver.pooling = True
            self.assertIs(DWSDialect.import_dbapi(), fake_driver)
            self.assertFalse(fake_driver.pooling)
            # Other driver families do not alter an unrelated ODBC module.
            fake_driver.pooling = True
            adapter_for(dict(self.config, dialect='mysql'))
            self.assertTrue(fake_driver.pooling)

    def test_catalog_distinguishes_system_driver_and_tls_capabilities(self):
        with patch('app.common.db.catalog.installed_odbc_drivers', return_value=['DWS']):
            catalog = {item['dialect']: item for item in capabilities()}
        self.assertNotIn('verify_identity', catalog['gaussdb']['tls_modes'])
        self.assertFalse(catalog['gaussdb']['ca_file'])
        self.assertFalse(catalog['clickhouse']['transactions'])
        self.assertEqual(catalog['gaussdb']['database_label'], '数据库名称')
        self.assertNotIn('oracle', catalog)
        self.assertNotIn('sqlserver', catalog)

    def test_removed_database_types_cannot_construct_newdb_or_load_a_driver(self):
        from app.common.db.factory import NewDB, adapter_for
        for family in ('oracle', 'sqlserver', 'mssql'):
            with self.subTest(dialect=family), patch('importlib.util.find_spec') as find_driver:
                profile = dict(self.config, dialect=family)
                with self.assertRaisesRegex(ValueError, '暂不支持数据库类型'):
                    adapter_for(profile)
                with patch('app.common.db.factory.load_database_config', return_value=profile):
                    with self.assertRaisesRegex(ValueError, '暂不支持数据库类型'):
                        NewDB('removed-connection')
                find_driver.assert_not_called()
