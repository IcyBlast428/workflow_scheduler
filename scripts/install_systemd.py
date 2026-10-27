"""Render or install Web/Scheduler units; no database migration or data deletion."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile

if __package__:
    from .service_config import read_environment, serialize_environment
else:
    from service_config import read_environment, serialize_environment

MARKER = '# Managed by workflow_scheduler/scripts/install_systemd.py'
ROOT = Path(__file__).resolve().parents[1]


def quote(value):
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise ValueError('Unit paths and values cannot contain control characters')
    return json.dumps(value.replace('%', '%%'), ensure_ascii=False)


def unit_path(value):
    # Path directives consume the whole value rather than an ExecStart argv.
    # Literal surrounding quotes would become part of the filesystem path.
    value = str(value)
    if any(ord(c) < 32 for c in value) or '\\' in value or value != value.strip():
        raise ValueError('Invalid unit path')
    return value.replace('%', '%%')


def render(*, scope='system', project='/data/wfs/current', python=None, environment_file='/etc/wfs/wfs.env',
           helper='/etc/wfs/wait_ready.py', data='/data/wfs/shared/data', logs='/data/wfs/shared/logs',
           user='wfs', group='wfs', web_port=8008, control_port=8009, unset=()):
    if scope not in ('system', 'user') or web_port == control_port or not all(1 <= p <= 65535 for p in (web_port, control_port)):
        raise ValueError('Invalid scope or service ports')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*\$?', user) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', group):
        raise ValueError('Invalid service account')
    for path in (project, python or str(Path(project)/'.venv/bin/python'), environment_file, helper, data, logs):
        if not Path(path).is_absolute():
            raise ValueError('Service paths must be absolute')
    python = python or str(Path(project)/'.venv/bin/python')
    base = 'wfs' if scope == 'system' else 'wfs-local'
    units = {}
    for role in ('scheduler', 'web'):
        name = base + ('-scheduler' if role == 'scheduler' else '') + '.service'
        scheduler = base + '-scheduler.service'
        port = control_port if role == 'scheduler' else web_port
        lines = [MARKER, '[Unit]', 'Description=Workflow Scheduler ' + role.title()]
        if role == 'web':
            lines += ['Requires=' + scheduler, 'After=' + scheduler]
        if scope == 'system':
            lines += ['After=network-online.target', 'Wants=network-online.target']
        lines += ['StartLimitIntervalSec=120', 'StartLimitBurst=10', '', '[Service]', 'Type=exec']
        if scope == 'system':
            lines += ['User=' + user, 'Group=' + group]
        lines += ['EnvironmentFile=' + unit_path(environment_file), 'Environment=PYTHONDONTWRITEBYTECODE=1',
                  'WorkingDirectory=' + unit_path(project)]
        removed = {'GUNICORN_CMD_ARGS', 'GUNICORN_FD', *unset}
        if scope == 'system':
            removed.update(('WFS_LOCAL_DB_PATH', 'WFS_POSTGRES_TEST', 'WFS_DEV_RUN_ALL'))
            lines += ['Environment=' + quote('ODBCSYSINI=' + project + '/app/config/driver/dws_odbc/etc'),
                      'Environment=' + quote('ODBCINI=' + project + '/app/config/driver/dws_odbc/etc/odbc.ini')]
        # Gunicorn raw_env is applied before importing the app. EnvironmentFile
        # cannot accidentally turn a Web worker into a second Scheduler.
        pinned = dict(WFS_ENV='production' if scope == 'system' else 'development',
                      WFS_ENABLE_SCHEDULER='true' if role == 'scheduler' else 'false',
                      WFS_SCHEDULER_CONTROL_URL='' if role == 'scheduler' else 'http://127.0.0.1:' + str(control_port),
                      WFS_DATA_DIR=data, WFS_LOG_DIR=logs, PYTHONPATH=project)
        if scope == 'system':
            pinned['WFS_COOKIE_SECURE'] = 'true'
        command = [python, '-m', 'gunicorn', '-c', project + '/gunicorn.conf.py', '--workers',
                   '1' if role == 'scheduler' else '2', '--worker-class', 'gthread', '--threads', '8',
                   '--timeout', '120', '--graceful-timeout', '60', '--keep-alive', '75', '--bind',
                   '127.0.0.1:' + str(port), '--access-logfile', '-', '--error-logfile', '-']
        for key, value in pinned.items():
            command += ['--env', key + '=' + value]
        command += ['run:app']
        lines += ['UnsetEnvironment=' + ' '.join(sorted(removed)), 'ExecStart=' + ' '.join(map(quote, command)),
                  'ExecStartPost=' + ' '.join(map(quote, [python, helper, '--url', f'http://127.0.0.1:{port}/api/user/ready', '--timeout', '90'])),
                  'UMask=0077', 'NoNewPrivileges=true', 'KillMode=mixed', 'KillSignal=SIGTERM',
                  'TimeoutStartSec=100', 'TimeoutStopSec=90', 'Restart=on-failure', 'RestartSec=5',
                  'StandardOutput=journal', 'StandardError=journal', 'SyslogIdentifier=' + base + '-' + role,
                  '', '[Install]', 'WantedBy=' + ('multi-user.target' if scope == 'system' else 'default.target'), '']
        units[name] = '\n'.join(lines)
    return units


def atomic_write(path, content, mode):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.wfs-install-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            output.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('system', 'user'), default='system')
    parser.add_argument('--project', default='/data/wfs/current')
    parser.add_argument('--environment-file', default='/etc/wfs/wfs.env')
    parser.add_argument('--python')
    parser.add_argument('--data')
    parser.add_argument('--logs')
    parser.add_argument('--user', default='wfs')
    parser.add_argument('--group', default='wfs')
    parser.add_argument('--web-port', type=int)
    parser.add_argument('--control-port', type=int)
    parser.add_argument('--output', type=Path, help='Render reviewable units without changing systemd')
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--start', action='store_true', help='Explicitly enable and restart after installing')
    args = parser.parse_args()
    if args.start and not args.install:
        parser.error('--start requires --install')
    if not args.install and not args.output:
        parser.error('choose --output for review, or --install')
    local = args.scope == 'user'
    if args.install and not local and os.geteuid() != 0:
        parser.error('system-wide installation requires root')
    if args.install and local and os.geteuid() == 0:
        parser.error('run the user-service installer as the ordinary project owner')
    project = Path(args.project).absolute()
    source_env = Path(args.environment_file).absolute()
    values, unset = read_environment(source_env) if local or args.install else ({}, set())
    if args.install and (not values.get('WFS_SECRET_KEY') or not values.get('WFS_ADMIN_PASSWORD_HASH')):
        parser.error('configure WFS_SECRET_KEY and WFS_ADMIN_PASSWORD_HASH first')
    data = str(Path(args.data or values.get('WFS_DATA_DIR') or ('/data/wfs/shared/data' if not local else str(project/'data'))).absolute())
    logs = str(Path(args.logs or values.get('WFS_LOG_DIR') or ('/data/wfs/shared/logs' if not local else str(project/'logs'))).absolute())
    python = args.python or (values.get('WFS_PYTHON') if local else None) or str(project/'.venv/bin/python')
    if local:
        config_home = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))).absolute()
        configuration = config_home/'workflow-scheduler'
        environment_file, helper = configuration/'systemd.env', configuration/'wait_ready.py'
        unit_dir = config_home/'systemd/user'
    else:
        environment_file, helper = source_env, source_env.parent/'wait_ready.py'
        unit_dir = Path('/etc/systemd/system')
    units = render(scope=args.scope, project=str(project), python=python, environment_file=str(environment_file),
                   helper=str(helper), data=data, logs=logs, user=args.user, group=args.group,
                   web_port=args.web_port or int(values.get('WFS_PORT', 18008 if local else 8008)),
                   control_port=args.control_port or int(values.get('WFS_CONTROL_PORT', 18009 if local else 8009)), unset=unset)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, content in units.items():
            atomic_write(args.output/name, content, 0o644)
        print('Rendered:', ', '.join(units))
    if not args.install:
        return
    for name in units:
        existing = unit_dir/name
        if existing.is_symlink() or existing.exists() and MARKER not in existing.read_text():
            # Existing repository templates before this installer are allowed
            # only with a deliberate manual backup, described in the handbook.
            raise ValueError('Refusing to overwrite an unmanaged service file: ' + str(existing))
    if not local:
        account = pwd.getpwnam(args.user)
        for directory in (data, logs):
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True, mode=0o750)
            os.chown(path, account.pw_uid, account.pw_gid)
    else:
        configuration.mkdir(parents=True, exist_ok=True, mode=0o700)
        for directory in (data, logs):
            Path(directory).mkdir(parents=True, exist_ok=True)
        atomic_write(environment_file, serialize_environment(values), 0o600)
        atomic_write(configuration/'systemd-source.txt', str(source_env) + '\n', 0o600)
    atomic_write(helper, (ROOT/'scripts/wait_ready.py').read_text(), 0o644)
    for name, content in units.items():
        atomic_write(unit_dir/name, content, 0o644)
    if local:
        subprocess.run(['systemd-analyze', '--user', 'verify', *[str(unit_dir/name) for name in units]], check=True)
    control = ['systemctl'] + (['--user'] if local else [])
    subprocess.run(control + ['daemon-reload'], check=True)
    print('Installed:', ', '.join(units))
    if args.start:
        subprocess.run(control + ['enable', *units], check=True)
        subprocess.run(control + ['restart', *units], check=True)
        print('Both services passed their startup readiness checks.')


if __name__ == '__main__':
    main()
