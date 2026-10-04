"""Run real ODBC acceptance in a fresh schema, preserving the running test app."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (os.environ.get('WFS_POSTGRES_TEST') != 'true' or
        os.environ.get('WFS_DB_ID') != 'wfstest_wfs' or os.environ.get('WFS_LOCAL_DB_PATH')):
    raise SystemExit('Only the dedicated local PostgreSQL test configuration is allowed.')

schema = 'wfs_acceptance_' + uuid.uuid4().hex
os.environ['WFS_DB_ID'] = 'wfstest_' + schema
os.environ['WFS_ENABLE_SCHEDULER'] = 'false'
os.environ['WFS_SCHEDULER_CONTROL_URL'] = ''
with tempfile.TemporaryDirectory(prefix='wfs-pg-acceptance-') as temporary:
    os.environ.update(WFS_DATA_DIR=temporary, WFS_LOG_DIR=str(Path(temporary)/'logs'),
                      WFS_TASK_RELEASE_DIR=str(Path(temporary)/'packages'))
    from app.bootstrap.database import GaussDB
    from scripts.migrate import main as migrate, statements
    created = False
    try:
        with GaussDB() as db:
            database, version = db.execute_query_sql('SELECT current_database(),version()')[0]
            if database != 'wfstest' or not version.startswith('PostgreSQL 18.1'):
                raise SystemExit('Expected the dedicated PostgreSQL 18.1 test database.')
            db.execute_sql(f'CREATE SCHEMA {schema}')
            created = True
            db.begin_transaction()
            for sql in statements(ROOT/'ddl.sql'):
                if sql == 'CREATE SCHEMA wfs' or sql == 'SET search_path TO wfs':
                    continue
                db.execute_sql(sql)
            db.set_commit()
        migrate()
        from scripts.accept_postgres_test import PostgreSQLAcceptance
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PostgreSQLAcceptance))
        passed = result.wasSuccessful()
        if passed and os.environ.get('WFS_PG_BENCHMARK') == 'true':
            from scripts.benchmark_postgres_completion import benchmark
            benchmark()
    finally:
        if created:
            # Only the exact fresh UUID schema created by this process is removed.
            with GaussDB() as db:
                db.execute_sql(f'DROP SCHEMA {schema} CASCADE')
            print('Temporary PostgreSQL acceptance schema removed.')
    raise SystemExit(0 if passed else 1)
