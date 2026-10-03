"""Create local development credentials without committing them to Git."""

from pathlib import Path
import secrets
import shlex
import sys

from werkzeug.security import generate_password_hash


root = Path(__file__).resolve().parents[1]
target = root / '.env.local'
if target.exists():
    raise SystemExit(f'{target} already exists; leave it in place or remove it to reset local credentials')

password = secrets.token_urlsafe(18)
values = {
    'WFS_ENV': 'development',
    'WFS_ENABLE_SCHEDULER': 'true',
    'WFS_DEV_RUN_ALL': 'true',
    'WFS_LOCAL_DB_PATH': str(root / 'data' / 'wfs-local.sqlite3'),
    'WFS_SECRET_KEY': secrets.token_urlsafe(48),
    'WFS_ADMIN_USERNAME': 'admin',
    'WFS_ADMIN_PASSWORD_HASH': generate_password_hash(password, method='scrypt'),
    'WFS_COOKIE_SECURE': 'false',
    'WFS_PYTHON': sys.executable,
    'WFS_PORT': '18008',
    'WFS_CONTROL_PORT': '18009',
}
target.write_text(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()), encoding='utf-8')
target.chmod(0o600)
print(f'Local environment: {target}')
print('Username: admin')
print(f'Password (shown once): {password}')
