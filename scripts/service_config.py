"""Strict shared environment reader. No shell expansion or code execution."""
import os
from pathlib import Path
import re
import shlex


def read_environment(path):
    values, unset = {}, set()
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError:
            raise ValueError(f'Invalid quoting on environment line {number}') from None
        if not tokens:
            continue
        if tokens[0] == 'unset' and len(tokens) == 2 and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', tokens[1]):
            unset.add(tokens[1]); values.pop(tokens[1], None)
            continue
        if tokens[0] == 'export':
            tokens = tokens[1:]
        if len(tokens) != 1 or '=' not in tokens[0]:
            raise ValueError(f'Expected a literal KEY=value on environment line {number}')
        key, value = tokens[0].split('=', 1)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or any(ord(c) < 32 for c in value):
            raise ValueError(f'Invalid environment assignment on line {number}')
        values[key] = value; unset.discard(key)
    return values, unset


def serialize_environment(values):
    return '# Managed by workflow_scheduler/scripts/install_systemd.py\n' + ''.join(
        key + '="' + value.replace('\\', '\\\\').replace('"', '\\"') + '"\n'
        for key, value in sorted(values.items()))


def production_command(config, data, logs, command):
    values, unset = read_environment(config)
    environment = dict(os.environ)
    for key in unset:
        environment.pop(key, None)
    environment.update(values)
    for key, expected in (('WFS_DATA_DIR', data), ('WFS_LOG_DIR', logs)):
        if environment.get(key) and Path(environment[key]).resolve() != Path(expected).resolve():
            raise ValueError(key + ' differs from the deployment shared directory; migrate data/configuration first')
        environment[key] = expected
    for key in ('WFS_LOCAL_DB_PATH', 'WFS_POSTGRES_TEST', 'WFS_DEV_RUN_ALL', 'GUNICORN_CMD_ARGS', 'WFS_SCHEDULER_CONTROL_URL'):
        environment.pop(key, None)
    environment.update(WFS_ENV='production', WFS_ENABLE_SCHEDULER='false', PYTHONDONTWRITEBYTECODE='1')
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Run an offline maintenance command with the production service environment.')
    parser.add_argument('--environment-file', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--logs', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('provide a command after --')
    production_command(args.environment_file, args.data, args.logs, command)
