"""Disposable PostgreSQL CI profile; only the named CI database is accepted."""
import os
from pathlib import Path
import runpy
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if os.environ.get('WFS_CI_POSTGRES') != 'true' or os.environ.get('PGDATABASE') != 'wfstest':
    raise SystemExit('Only the disposable CI PostgreSQL profile is allowed.')
with tempfile.TemporaryDirectory(prefix='wfs-ci-pg-') as temporary:
    config=Path(temporary)/'database.ini'
    config.write_text('[gauss_immpdb]\nuser=wfstest\nhost=postgres\nport=5432\npassword=\n')
    os.environ.update(WFS_DB_CONFIG_FILE=str(config),WFS_POSTGRES_TEST='true',WFS_DB_DIALECT='postgresql',WFS_DB_ID='wfstest_wfs',
                      WFS_DB_DRIVER='PostgreSQL Unicode',WFS_DB_PASSWORD=os.environ['PGPASSWORD'],WFS_ENV='development',
                      WFS_SECRET_KEY='disposable-ci-session-key',WFS_PG_BENCHMARK='true')
    os.environ.pop('WFS_LOCAL_DB_PATH',None)
    runpy.run_path(str(ROOT/'scripts/accept_postgres_isolated.py'),run_name='__main__')
