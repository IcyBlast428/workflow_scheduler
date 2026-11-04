"""Opt-in acceptance against a prepared dedicated GaussDB test schema."""
import os
import unittest
import uuid


@unittest.skipUnless(os.environ.get('WFS_TEST_GAUSS') == 'true', 'Dedicated GaussDB test connection not provided')
class GaussIntegrationTests(unittest.TestCase):
    def test_odbc_schema_transaction_and_migrations(self):
        from app.bootstrap.database import GaussDB
        from scripts.init_database import table_names
        table = 'wfs_acceptance_' + uuid.uuid4().hex[:12]
        with GaussDB() as db:
            self.assertEqual(db.dialect,'GaussDB/DWS')
            for required in table_names():
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
