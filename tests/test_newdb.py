"""Real pooled SQLite checks plus multi-driver URL and parameter compatibility."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, TimeoutError

import test_local_integration  # Isolated platform environment for discovery.
from app.bootstrap import connection_settings as settings
from app.common.database import NewDB
from app.common.db.factory import adapter_for
from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class NewDBTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict(os.environ, {'WFS_DATA_DIR':str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(NewDB.dispose_pool)
        self.profile = settings.validate({'id':'sqlite_reports','dialect':'sqlite','database':'reports.sqlite3'})
        self.saved = settings.save(self.profile)
        with NewDB('sqlite_reports') as db:
            db.execute('CREATE TABLE report(id INTEGER PRIMARY KEY, value TEXT)')

    def test_new_instances_reuse_one_physical_connection_and_close_returns_it(self):
        NewDB.dispose_pool()
        engine = NewDB('sqlite_reports').get_engine()
        connections = []
        event.listen(engine, 'connect', lambda connection, record: connections.append(connection))
        for index in range(40):
            with NewDB('sqlite_reports') as db:
                self.assertEqual(db.query('SELECT ? AS value', (index,)), [(index,)])
        self.assertEqual(len(connections), 1)
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_transaction_commit_rollback_batch_and_automatic_close(self):
        with NewDB('sqlite_reports') as db:
            with db.transaction():
                db.execute('INSERT INTO report VALUES(?,?)', (1,'committed'))
                db.executemany('INSERT INTO report VALUES(:id,:value)', [{'id':2,'value':'二'},{'id':3,'value':'三'}])
            with self.assertRaises(IntegrityError):
                with db.transaction():
                    db.execute('INSERT INTO report VALUES(?,?)', (4,'rolled back'))
                    db.execute('INSERT INTO report VALUES(?,?)', (1,'duplicate'))
            self.assertEqual(db.query('SELECT COUNT(*) FROM report'), [(3,)])
            # Raw connections are also rolled back at context exit.
            db.get_connection().exec_driver_sql('INSERT INTO report VALUES(5,\'unfinished\')')
        self.assertEqual(NewDB('sqlite_reports').query('SELECT COUNT(*) FROM report'), [(3,)])
        self.assertEqual(NewDB('sqlite_reports').get_engine().pool.checkedout(), 0)

    def test_failed_batch_is_atomic_and_empty_batch_does_nothing(self):
        db = NewDB('sqlite_reports')
        with self.assertRaises(IntegrityError):
            db.insert_with_rollback('INSERT INTO report VALUES(?,?)', [(1,'one'),(1,'duplicate')])
        self.assertEqual(db.query('SELECT COUNT(*) FROM report'), [(0,)])
        self.assertEqual(db.executemany('INSERT INTO report VALUES(?,?)', []), 0)

    def test_pool_is_bounded_and_recovers_after_timeout(self):
        with self.assertRaises(ValueError):
            NewDB('sqlite_reports').get_engine(poolSize=0)
        profile = settings.validate(dict(self.saved, pool_size=1, max_overflow=0, pool_timeout=1))
        settings.save(profile)
        held = NewDB('sqlite_reports')
        held.get_connection()
        try:
            with self.assertRaises(TimeoutError):
                NewDB('sqlite_reports').query('SELECT 1')
        finally:
            held.close()
        self.assertEqual(NewDB('sqlite_reports').query('SELECT 1'), [(1,)])

    def test_multiple_threads_use_distinct_handles_without_leaking_connections(self):
        def read(index):
            with NewDB('sqlite_reports') as db:
                return db.query('SELECT ?', (index,))[0][0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(list(pool.map(read,range(30))), list(range(30)))
        self.assertEqual(NewDB('sqlite_reports').get_engine().pool.checkedout(), 0)

    def test_a_handle_cannot_cross_threads_or_processes(self):
        db = NewDB('sqlite_reports')
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(RuntimeError):
                pool.submit(db.query,'SELECT 1').result()
        with patch('app.common.db.sqlalchemy_adapter.os.getpid', return_value=os.getpid()+1):
            with self.assertRaises(RuntimeError):
                db.query('SELECT 1')

    def test_profile_change_invalidates_old_pool_and_disabled_pool_closes_sockets(self):
        old = NewDB('sqlite_reports').get_engine()
        changed = settings.validate(dict(self.saved, database='other.sqlite3', pool_enabled=False))
        settings.save(changed)
        db = NewDB('sqlite_reports')
        engine = db.get_engine()
        self.assertIsNot(engine, old)
        from sqlalchemy.pool import NullPool
        self.assertIsInstance(engine.pool, NullPool)
        closed = []
        event.listen(engine,'close',lambda connection, record:closed.append(1))
        db.query('SELECT 1'); db.query('SELECT 1')
        self.assertEqual(len(closed),2)

    def test_resolved_sqlite_location_is_part_of_pool_identity(self):
        old = NewDB('sqlite_reports').get_engine()
        with patch.dict(os.environ, {'WFS_DATA_DIR':str(self.root/'other-data')}):
            settings.save(settings.validate({'id':'sqlite_reports','dialect':'sqlite','database':'reports.sqlite3'}))
            current = NewDB('sqlite_reports').get_engine()
            self.assertIsNot(current,old)
            self.assertNotEqual(current.url.database, old.url.database)

    def test_portable_parameters_ignore_literals_comments_and_support_legacy_named_style(self):
        db = NewDB('sqlite_reports')
        self.assertEqual(db.query("SELECT '?' AS literal, ? AS value -- ?\n", ('中文 50%',), as_dict=True), [{'literal':'?','value':'中文 50%'}])
        self.assertEqual(db.query('SELECT %(value)s', {'value':'value'}), [('value',)])
        with self.assertRaises(ValueError):
            db.query('SELECT ?,?', (1,))
        with self.assertRaises(RuntimeError):
            with db.transaction():
                with db.transaction():
                    pass

    def test_default_tls_supported_catalog_and_dialect_validation(self):
        mysql = dict(id='orders',host='localhost',database='orders',user='reader',password='test-only-password')
        self.assertEqual(settings.validate(mysql)['tls'], 'disabled')
        self.assertEqual(settings.validate(dict(mysql,dialect='postgresql'))['port'],5432)
        from app.common.db.catalog import capabilities
        catalog = {item['dialect']: item['label'] for item in capabilities()}
        self.assertEqual(set(catalog), {'mysql', 'postgresql', 'clickhouse', 'sqlite'})
        self.assertEqual(catalog['postgresql'], 'PostgreSQL / GaussDB')
        for removed in ('oracle', 'mssql', 'sqlserver'):
            with self.subTest(dialect=removed), self.assertRaises(ValueError):
                settings.validate(dict(mysql, dialect=removed))
            with self.subTest(adapter=removed), self.assertRaises(ValueError):
                adapter_for(dict(mysql, dialect=removed))
        with self.assertRaises(ValueError):
            settings.validate(dict(mysql,id='platform',dialect='postgresql'))
        with self.assertRaises(ValueError):
            settings.validate(dict(mysql,pool_size=0))
        with self.assertRaises(ValueError):
            settings.validate(dict(id='bad',dialect='sqlite',database='../secret'))
        self.assertTrue(settings.probe(self.profile)['ready'])

    def test_driver_urls_preserve_special_credentials_without_connecting(self):
        from app.common.db.catalog import capabilities
        config = dict(id='url-check',host='localhost',port=3306,user='name@host',password='secret/@:%?',database='example',tls='disabled')
        for spec in capabilities():
            if spec['dialect'] == 'sqlite':
                continue
            if not spec['available']:
                continue
            adapter = adapter_for(dict(config,dialect=spec['dialect']))
            url = adapter.build_url()
            self.assertEqual(url.username,config['user'])
            self.assertEqual(url.password,config['password'])
            self.assertNotIn(config['password'],str(url))
            self.assertIsNotNone(adapter.get_engine())


if __name__ == '__main__':
    unittest.main()
