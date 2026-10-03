"""Configure a local-only PostgreSQL ODBC acceptance environment."""
import os
from pathlib import Path
import secrets
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / '.env.postgres.local'
if target.exists():
    raise SystemExit('PostgreSQL test configuration already exists; reuse it.')
secret_dir = ROOT / '.wfs-secrets'
secret_dir.mkdir(mode=0o700, exist_ok=True)
password = secrets.token_urlsafe(32)
(secret_dir/'postgres-container.env').write_text(f'POSTGRES_DB=wfstest\nPOSTGRES_USER=wfstest\nPOSTGRES_PASSWORD={password}\n', encoding='utf-8')
(secret_dir/'postgres-test.ini').write_text('[gauss_immpdb]\nuser=wfstest\nhost=127.0.0.1\nport=15432\npassword=\n', encoding='utf-8')
values = {key:os.environ[key] for key in ('WFS_SECRET_KEY','WFS_ADMIN_USERNAME','WFS_ADMIN_PASSWORD_HASH')}
values.update({
    'WFS_ENV':'development', 'WFS_POSTGRES_TEST':'true', 'WFS_DEV_RUN_ALL':'true',
    'WFS_DB_ID':'wfstest_wfs', 'WFS_DB_DRIVER':'PostgreSQL Unicode',
    'WFS_DB_CONFIG_FILE':str(secret_dir/'postgres-test.ini'), 'WFS_DB_PASSWORD':password,
    'WFS_COOKIE_SECURE':'false', 'WFS_PYTHON':sys.executable,
    'WFS_DATA_DIR':str(ROOT/'data'/'postgres-test'),
    'WFS_PORT':'18008', 'WFS_CONTROL_PORT':'18009',
})
target.write_text('unset WFS_LOCAL_DB_PATH\n'+''.join(f'{key}={shlex.quote(value)}\n' for key,value in values.items()),encoding='utf-8')
for path in (target,secret_dir/'postgres-container.env',secret_dir/'postgres-test.ini'):
    path.chmod(0o600)
print('Local PostgreSQL test configuration created. Existing browser login credentials retained.')
