"""One systemd service supervising separate Web and single-Scheduler processes."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def commands(project, python, web_host, web_port, control_port, data, logs):
    project = str(project)
    result = []
    for role in ('scheduler', 'web'):
        scheduler = role == 'scheduler'
        port = control_port if scheduler else web_port
        args = [str(python), '-m', 'gunicorn', '-c', project + '/gunicorn.conf.py',
                '--workers', '1' if scheduler else '2', '--worker-class', 'gthread',
                '--threads', '8', '--timeout', '120', '--graceful-timeout', '60',
                '--keep-alive', '75', '--bind', ('127.0.0.1' if scheduler else web_host) + ':' + str(port),
                '--access-logfile', '-', '--error-logfile', '-']
        pinned = dict(WFS_ENV='production', WFS_ENABLE_SCHEDULER='true' if scheduler else 'false',
                      WFS_SCHEDULER_CONTROL_URL='' if scheduler else 'http://127.0.0.1:' + str(control_port),
                      WFS_DATA_DIR=str(data), WFS_LOG_DIR=str(logs), PYTHONPATH=project)
        for key, value in pinned.items():
            args += ['--env', key + '=' + value]
        args += ['run:app']
        result.append((role, args, port))
    return result


def child_environment():
    environment = dict(os.environ)
    # Role flags are pinned in commands(); inherited Gunicorn options must not
    # preload the scheduler or create additional workers/listeners.
    for key in ('GUNICORN_CMD_ARGS', 'GUNICORN_FD', 'WFS_DEV_RUN_ALL', 'WFS_PLATFORM_ACTIVE_CONFIG_FILE'):
        environment.pop(key, None)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    return environment


@contextmanager
def instance_lock(data):
    import fcntl
    Path(data).mkdir(parents=True, exist_ok=True)
    with (Path(data)/'.service.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another service instance already uses this data directory.') from None
        yield


def check_ports(web_host, web_port, control_port):
    for host, port in ((web_host, web_port), ('127.0.0.1', control_port)):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                raise RuntimeError(f'Port {port} is already in use; stop the previous services first.') from None


def ready(port):
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/user/ready', timeout=1) as response:
            payload = json.loads(response.read(65537))
            data = payload.get('data', {})
            return response.status == 200 and data.get('ready') is True and data.get('scheduler') is True
    except (OSError, ValueError, AttributeError):
        return False


class Supervisor:
    def __init__(self, project, environment, startup_timeout=90, stop_timeout=70):
        self.project = project
        self.environment = environment
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout
        self.stopping = threading.Event()
        self.children = []

    def request_stop(self, *_):
        self.stopping.set()

    def check_children(self):
        for role, process in self.children:
            code = process.poll()
            if code is not None:
                raise RuntimeError(f'{role} process exited unexpectedly (status {code}).')

    def start(self, role, command, port):
        if self.stopping.is_set():
            return False
        process = subprocess.Popen(command, cwd=self.project, env=self.environment, start_new_session=True)
        self.children.append((role, process))
        deadline = time.monotonic() + self.startup_timeout
        while not self.stopping.is_set():
            self.check_children()
            if ready(port):
                print(role + ' is ready.', flush=True)
                return True
            if time.monotonic() >= deadline:
                raise RuntimeError(role + ' did not become ready before the startup deadline.')
            self.stopping.wait(.2)
        return False

    @staticmethod
    def signal_group(process, signum):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    def stop_children(self):
        # Stop accepting requests first, then stop the scheduler. The Gunicorn
        # masters drain workers and invoke the existing task cleanup hook.
        for _, process in reversed(self.children):
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + self.stop_timeout
        for _, process in reversed(self.children):
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        # Include orphaned workers whose master exited before their cleanup.
        for _, process in self.children:
            self.signal_group(process, signal.SIGKILL)
            process.wait()

    def run(self, services):
        try:
            for role, command, port in services:
                if not self.start(role, command, port):
                    return 0
            while not self.stopping.wait(.2):
                self.check_children()
            return 0
        except (OSError, RuntimeError) as error:
            print('Service failed: ' + str(error), file=sys.stderr, flush=True)
            return 1
        finally:
            self.stop_children()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--web-host', choices=('127.0.0.1', '0.0.0.0'), default='127.0.0.1')
    parser.add_argument('--web-port', type=int, default=8008)
    parser.add_argument('--control-port', type=int, default=8009)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--logs', type=Path)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('This production launcher requires Linux.')
    if args.web_port == args.control_port or not all(1 <= p <= 65535 for p in (args.web_port, args.control_port)):
        parser.error('Choose two different valid ports.')
    project = args.project.resolve()
    data = (args.data or Path(os.environ.get('WFS_DATA_DIR', project/'data'))).resolve()
    logs = (args.logs or Path(os.environ.get('WFS_LOG_DIR', project/'logs'))).resolve()
    supervisor = Supervisor(project, child_environment())
    signal.signal(signal.SIGTERM, supervisor.request_stop)
    signal.signal(signal.SIGINT, supervisor.request_stop)
    try:
        with instance_lock(data):
            check_ports(args.web_host, args.web_port, args.control_port)
            from app.bootstrap.platform_config import frozen_service_config
            with frozen_service_config(data, supervisor.environment) as frozen:
                supervisor.environment['WFS_PLATFORM_ACTIVE_CONFIG_FILE'] = frozen
                return supervisor.run(commands(project, args.python, args.web_host, args.web_port, args.control_port, data, logs))
    except (RuntimeError, ValueError, OSError) as error:
        print('Cannot start service: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
