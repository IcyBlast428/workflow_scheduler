"""Read-only GaussDB platform readiness check; never creates business tables."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.bootstrap.database import GaussDB
    tables = re.findall(r'CREATE TABLE IF NOT EXISTS (wfs_\w+)',
                        (ROOT/'app/bootstrap/sqlite_schema.sql').read_text())
    with GaussDB() as db:
        if db._mysql or db._local_sqlite or db.dialect != 'GaussDB/DWS':
            raise RuntimeError('This deployment requires the GaussDB/DWS platform database')
        for table in [*tables, 'wfs_schema_migrations']:
            db.execute_query_sql(f'SELECT 1 FROM {table} LIMIT 0')
    print('GaussDB platform schema ready:', len(tables)+1, 'tables')


if __name__ == '__main__':
    main()
