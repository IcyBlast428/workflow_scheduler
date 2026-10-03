"""Opt-in acceptance against a prepared dedicated GaussDB test schema."""
import os
import unittest
import uuid


@unittest.skipUnless(os.environ.get('WFS_TEST_GAUSS') == 'true', 'Dedicated GaussDB test connection not provided')
class GaussIntegrationTests(unittest.TestCase):
    def test_odbc_schema_transaction_and_migrations(self):
        from app.bootstrap.database import GaussDB
        from scripts.migrate import REQUIRED_TABLES
        table = 'wfs_acceptance_' + uuid.uuid4().hex[:12]
        with GaussDB() as db:
            self.assertFalse(db._local_sqlite, 'Unset WFS_LOCAL_DB_PATH for GaussDB acceptance')
            for required in REQUIRED_TABLES + ('wfs_executions','wfs_config_versions','wfs_users','wfs_schema_migrations','wfs_run_history_archive','wfs_history_rollup'):
                db.execute_query_sql(f'SELECT 1 FROM {required} LIMIT 0')
            db.execute_sql(f'CREATE TABLE {table} (id integer PRIMARY KEY, value text)')
            try:
                db.begin_transaction()
                db.execute_sql(f'INSERT INTO {table} VALUES (?,?)', params=(1,'rollback;验证'))
                db.execute_query_sql(f'SELECT id FROM {table} WHERE id=? FOR UPDATE',params=(1,))
                db.set_rollback()
                self.assertEqual(db.execute_query_sql(f'SELECT COUNT(*) FROM {table}')[0][0],0)
            finally:
                db.execute_sql(f'DROP TABLE {table}')
                db.set_commit()
