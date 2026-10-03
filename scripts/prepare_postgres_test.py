"""Create project schema and all migrations through the actual pyodbc adapter."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if os.environ.get('WFS_POSTGRES_TEST') != 'true' or os.environ.get('WFS_LOCAL_DB_PATH') or os.environ.get('WFS_DB_ID') != 'wfstest_wfs':
    raise SystemExit('Only the dedicated PostgreSQL test database is allowed.')
from app.bootstrap.database import GaussDB
from scripts.migrate import main as migrate, statements

with GaussDB() as db:
    version = db.execute_query_sql('SELECT version()')[0][0]
    if not version.startswith('PostgreSQL 18.1'):
        raise SystemExit('Expected PostgreSQL 18.1')
    exists = db.execute_query_sql("SELECT 1 FROM information_schema.tables WHERE table_schema='wfs' AND table_name='wfs_run_history'")
    if not exists:
        db.begin_transaction()
        try:
            for sql in statements(ROOT/'ddl.sql'):
                db.execute_sql(sql)
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
    print(version.split(',')[0])
migrate()
with GaussDB() as db:
    tables = db.execute_query_sql("SELECT table_name FROM information_schema.tables WHERE table_schema='wfs' ORDER BY table_name")
    print('Project tables: '+', '.join(row[0] for row in tables))
