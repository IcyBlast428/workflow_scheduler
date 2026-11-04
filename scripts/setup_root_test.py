"""Initialize the explicit root / fixed-directory intranet test profile."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import subprocess

from werkzeug.security import generate_password_hash

PROJECT = Path('/data/workflow_scheduler')


def initialize(project, password):
    project = Path(project)
    config = project / 'deploy/root-test/runtime.env'
    if config.exists():
        return config, False
    if not password:
        raise ValueError('Administrator password cannot be empty')
    config.parent.mkdir(parents=True, exist_ok=True)
    values = {
        'WFS_ENV': 'production',
        'WFS_SECRET_KEY': secrets.token_urlsafe(48),
        'WFS_CONNECTIONS_KEY': secrets.token_urlsafe(48),
        'WFS_ADMIN_USERNAME': 'admin',
        'WFS_ADMIN_PASSWORD_HASH': generate_password_hash(password),
        'WFS_DB_ID': 'wfsscheduler_wfs',
        'WFS_DB_DRIVER': 'DWS',
        'WFS_STATE_BACKEND': 'gauss',
        'WFS_NACOS_URL': 'CHANGE_ME',
        'WFS_NACOS_USERNAME': 'CHANGE_ME',
        'WFS_NACOS_PASSWORD': 'CHANGE_ME',
        'ODBCSYSINI': str(project / 'deploy/root-test/odbc'),
        'ODBCINI': str(project / 'deploy/root-test/odbc/odbc.ini'),
        'WFS_DATA_DIR': str(project / 'data'),
        'WFS_LOG_DIR': str(project / 'logs'),
        'WFS_COOKIE_SECURE': 'false',
        'WFS_DEV_RUN_ALL': 'false',
        'PYTHONDONTWRITEBYTECODE': '1',
    }
    # Exclusive creation preserves existing credentials on retries/races.
    try:
        with config.open('x', encoding='utf-8', newline='\n') as output:
            os.chmod(config, 0o600)
            output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    except FileExistsError:
        return config, False
    return config, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Install and start the two test services')
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        parser.error('Run as root on the Linux test server')
    if Path(__file__).resolve().parents[1] != PROJECT:
        parser.error('Extract this project directly into /data/workflow_scheduler')
    python = PROJECT / '.venv/bin/python'
    if not python.is_file():
        parser.error('Create /data/workflow_scheduler/.venv and install dependencies first')
    destinations = [(PROJECT/'deploy/root-test'/name, Path('/etc/systemd/system')/name)
                    for name in ('wfs-scheduler.service', 'wfs.service')]
    if args.install:
        # Do not replace a production service or an unrelated installation.
        for source, target in destinations:
            if target.is_symlink() or target.exists() and target.read_bytes() != source.read_bytes():
                parser.error(f'Existing service differs; back up and resolve it first: {target}')
    config = PROJECT/'deploy/root-test/runtime.env'
    if not config.exists():
        password = getpass.getpass('Set administrator password (at least 12 characters): ')
        if len(password) < 12 or password != getpass.getpass('Confirm password: '):
            parser.error('Passwords must match and contain at least 12 characters')
        initialize(PROJECT, password)
    for directory in ('data', 'logs'):
        (PROJECT/directory).mkdir(mode=0o700, exist_ok=True)
    print('Configuration ready (existing keys and accounts are preserved):', config)
    if not args.install:
        print('Configure GaussDB/Nacos, create the database tables, then run again with --install.')
        return
    from service_config import read_environment
    values, _ = read_environment(config)
    if values.get('WFS_STATE_BACKEND') != 'gauss':
        parser.error('Set WFS_STATE_BACKEND=gauss for this fresh-install profile')
    if values.get('WFS_LOCAL_DB_PATH') or values.get('WFS_POSTGRES_TEST') or values.get('WFS_DB_DIALECT'):
        parser.error('This profile requires GaussDB/DWS, without a local database test override')
    for key in ('WFS_DB_ID','WFS_NACOS_URL','WFS_NACOS_USERNAME','WFS_NACOS_PASSWORD'):
        if not values.get(key) or 'CHANGE_ME' in values[key]:
            parser.error('Complete GaussDB/Nacos configuration in runtime.env first: ' + key)
    subprocess.run([str(python), str(PROJECT/'scripts/service_config.py'),
                    '--environment-file', str(config), '--data', str(PROJECT/'data'),
                    '--logs', str(PROJECT/'logs'), '--', str(python),
                    str(PROJECT/'scripts/check_gauss_platform.py')], check=True)
    for source, target in destinations:
        target.write_bytes(source.read_bytes())
        target.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'wfs-scheduler.service', 'wfs.service'], check=True)
    subprocess.run(['systemctl', 'restart', 'wfs-scheduler.service'], check=True)
    subprocess.run(['systemctl', 'restart', 'wfs.service'], check=True)
    print('Ready: http://<server-ip>:8008/  Username: admin')


if __name__ == '__main__':
    main()
