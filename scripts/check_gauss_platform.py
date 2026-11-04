"""Read-only GaussDB platform readiness check; never creates business tables."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import os
    if os.environ.get('WFS_STATE_BACKEND') != 'gauss':
        raise RuntimeError('Set WFS_STATE_BACKEND=gauss; SQLite state is not allowed in this deployment')
    from app.bootstrap.database import GaussDB
    definitions = [ROOT/'ddl.sql', *sorted((ROOT/'migrations').glob('[0-9][0-9][0-9]_*.sql'))]
    tables = list(dict.fromkeys([name for source in definitions
                                for name in re.findall(r'CREATE TABLE (?:IF NOT EXISTS )?(wfs_\w+)', source.read_text(encoding='utf-8'))]
                               + ['wfs_schema_migrations']))
    with GaussDB() as db:
        if db._mysql or db._local_sqlite or db.dialect != 'GaussDB/DWS':
            raise RuntimeError('This deployment requires the GaussDB/DWS platform database')
        for table in tables:
            db.execute_query_sql(f'SELECT 1 FROM {table} LIMIT 0')
    print('GaussDB platform schema ready:', len(tables), 'tables')


if __name__ == '__main__':
    main()
