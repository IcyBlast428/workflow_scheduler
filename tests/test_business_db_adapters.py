"""Driver contracts only: URL/TLS, SQL binding and transaction ownership.

The DWS dialect uses an in-memory DBAPI double below, not a DWS server. Actual
vendor integrations must be tested with their server/driver versions.
"""
import sqlite3
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from sqlalchemy.dialects.mssql.pyodbc import MSDialect_pyodbc
from sqlalchemy.dialects.oracle.oracledb import OracleDialect_oracledb
from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlalchemy import create_engine
from sqlalchemy.dialects import registry
from app.common.db.adapters import GaussDBAdapter, SQLServerAdapter, OracleAdapter
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

    def test_sqlserver_and_oracle_keep_password_outside_url_rendering(self):
        ms = SQLServerAdapter(dict(self.config, port=1433, tls='verify_identity')).build_url()
        self.assertEqual(ms.query['Encrypt'], 'yes')
        self.assertEqual(ms.query['TrustServerCertificate'], 'no')
        self.assertNotIn(self.config['password'], str(ms))
        ora = OracleAdapter(dict(self.config, port=1521))
        self.assertEqual(ora.build_url().query['service_name'], 'reports')
        self.assertIsNone(ora.build_url().database)
        self.assertEqual(ora.connection_options()['service_name'], 'reports')
        self.assertIsNone(ora.connection_options()['dsn'])
        with patch('ssl.create_default_context', return_value='test-context') as tls:
            options = OracleAdapter(dict(self.config, tls='verify_identity', ssl_ca='/ca.pem')).connection_options()
        tls.assert_called_once_with(cafile='/ca.pem')
        self.assertEqual(options['protocol'], 'tcps')
        self.assertTrue(options['ssl_server_dn_match'])

    def test_sqlserver_qmark_pipeline_preserves_brackets_temp_tables_and_values(self):
        dialect = MSDialect_pyodbc(paramstyle='qmark')
        connection = Mock()
        adapter = SQLServerAdapter(dict(self.config, dialect='sqlserver'))
        payload = "quote'; DROP TABLE harmless -- 中文"
        adapter._execute(connection,
                         "SELECT '?' AS literal, [question?] FROM #jobs WHERE id=? AND note=?",
                         (17, payload))
        statement, parameters = connection.execute.call_args.args
        compiled = statement.compile(dialect=dialect)
        self.assertEqual(str(compiled), "SELECT '?' AS literal, [question?] FROM #jobs WHERE id=? AND note=?")
        self.assertEqual([parameters[key] for key in compiled.positiontup], [17, payload])
        self.assertNotIn(payload, str(compiled))
        connection.exec_driver_sql.assert_not_called()
        adapter._execute(connection, 'INSERT INTO #jobs(id,note) VALUES (?,?)', [(1, 'one'), (2, 'two')])
        statement, parameters = connection.execute.call_args.args
        self.assertEqual(len(parameters), 2)
        self.assertEqual(parameters[1], {'wfs_bind_0': 2, 'wfs_bind_1': 'two'})

    def test_oracle_pipeline_keeps_alternative_quotes_and_named_bindings(self):
        connection = Mock()
        adapter = OracleAdapter(dict(self.config, dialect='oracle', port=1521))
        adapter._execute(connection, "SELECT q'[it's ?]' AS label, ? FROM DUAL", ('中文 50%',))
        statement, parameters = connection.execute.call_args.args
        compiled = statement.compile(dialect=OracleDialect_oracledb(paramstyle='named'))
        self.assertEqual(str(compiled), "SELECT q'[it's ?]' AS label, :wfs_bind_0 FROM DUAL")
        self.assertEqual(parameters, {'wfs_bind_0': '中文 50%'})
        # SQLAlchemy's dialect supplies credentials; structured connect args
        # override its default TCP DSN for TLS without dropping service_name.
        fake_dbapi = SimpleNamespace(makedsn=lambda host, port, **kwargs: 'generated-tcp-descriptor')
        dialect = OracleDialect_oracledb()
        dialect.dbapi = fake_dbapi
        _, generated = dialect.create_connect_args(adapter.build_url())
        with patch('ssl.create_default_context', return_value='verified-test-context'):
            secure = OracleAdapter(dict(self.config, dialect='oracle', port=1521, tls='verify_identity', ssl_ca='/ca.pem'))
            generated.update(secure.connection_options())
        self.assertIsNone(generated['dsn'])
        self.assertEqual(generated['user'], self.config['user'])
        self.assertEqual(generated['password'], self.config['password'])
        self.assertEqual((generated['protocol'], generated['service_name']), ('tcps', 'reports'))

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
            ('sqlserver', MSDialect_pyodbc(paramstyle='qmark'), "SELECT ' :literal' AS x, ? AS y -- :comment"),
            ('oracle', OracleDialect_oracledb(paramstyle='named'), "SELECT q'[ :literal]' AS x, ? AS y FROM DUAL /* :comment */"),
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
            for family in ('gaussdb', 'sqlserver'):
                fake_driver.pooling = True
                adapter = adapter_for(dict(self.config, dialect=family))
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
        self.assertFalse(catalog['sqlserver']['ca_file'])
        self.assertFalse(catalog['clickhouse']['transactions'])
        self.assertEqual(catalog['oracle']['database_label'], '服务名（Service Name）')
        self.assertFalse(catalog['sqlserver']['driver_ready'])
