"""Disposable PostgreSQL/Gunicorn acceptance; never installs or changes systemd."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import requests
    from werkzeug.security import generate_password_hash
    from scripts.test_database import configure, publish_fixture
    from scripts.serve import Supervisor, child_environment, commands, check_ports, ready

    with tempfile.TemporaryDirectory(prefix='wfs-single-service-') as temporary:
        root = Path(temporary)
        configure(root)
        password = 'disposable-single-service-test'
        os.environ['WFS_ADMIN_PASSWORD_HASH'] = generate_password_hash(password)
        os.environ['WFS_SESSION_COOKIE_NAME'] = 'wfs_single_service_test'
        from app import create_app
        create_app()
        from app.bootstrap.task_loader import load_task_spec
        task = root/'jobs/single/hello'
        task.mkdir(parents=True)
        (task/'main.py').write_text('print("SINGLE_SERVICE_EXECUTION_OK", flush=True)\n')
        publish_fixture(load_task_spec('single', 'hello', task, {}))
        with socket.socket() as first, socket.socket() as second:
            first.bind(('127.0.0.1', 0)); second.bind(('127.0.0.1', 0))
            web_port, control_port = first.getsockname()[1], second.getsockname()[1]
        services = commands(ROOT, sys.executable, '127.0.0.1', web_port, control_port, root/'data', root/'logs')
        # Production deliberately rejects PostgreSQL; only this acceptance fixture
        # changes that flag. Roles, workers, entry point and supervisor are real.
        services = [(role, ['WFS_ENV=development' if arg == 'WFS_ENV=production' else arg for arg in command], port)
                    for role, command, port in services]
        base = f'http://127.0.0.1:{web_port}'
        for fail_web in (True, False):
            supervisor = Supervisor(ROOT, child_environment(), startup_timeout=40, stop_timeout=10)
            result = []
            thread = threading.Thread(target=lambda: result.append(supervisor.run(services)), daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 60
                while not ready(web_port):
                    if result or time.monotonic() > deadline:
                        raise AssertionError('Single-service startup did not become ready')
                    time.sleep(.2)
                session = requests.Session()
                session.trust_env = False
                def call(method, path, **kwargs):
                    response = session.request(method, base+path, timeout=15, **kwargs)
                    response.raise_for_status()
                    payload = response.json()
                    assert payload['code'] == 20000, payload.get('message')
                    return payload['data']
                csrf = call('POST', '/api/user/login', json={'username':'admin', 'password':password})['csrf_token']
                session.headers['X-CSRF-Token'] = csrf
                request_id = uuid.uuid4().hex
                run_id = call('POST', '/api/taskinfo/call_task', params={'pid':'single__hello'}, json={'request_id':request_id})['run_id']
                deadline = time.monotonic() + 30
                while True:
                    record = call('GET', '/api/taskinfo/run', params={'run_id':run_id})['record']
                    if record['status'] == 'success': break
                    if record['status'] not in ('queued','running') or time.monotonic() > deadline:
                        raise AssertionError('Task failed or timed out: '+record['status'])
                    time.sleep(.2)
                repeated = call('POST', '/api/taskinfo/call_task', params={'pid':'single__hello'}, json={'request_id':request_id})
                assert repeated['run_id'] == run_id
                if fail_web:
                    next(process for role, process in supervisor.children if role == 'web').kill()
                else:
                    supervisor.request_stop()
                thread.join(20)
                assert result == [1 if fail_web else 0], result
                assert all(process.poll() is not None for _, process in supervisor.children)
                for attempt in range(30):
                    try:
                        check_ports('127.0.0.1', web_port, control_port)
                        break
                    except RuntimeError:
                        if attempt == 29: raise
                        time.sleep(.1)
                print('SINGLE_SERVICE_HTTP_AND_' + ('FAILURE_CLEANUP' if fail_web else 'RESTART_SHUTDOWN') + '_OK', flush=True)
            finally:
                supervisor.request_stop()
                thread.join(25)
                if thread.is_alive():
                    raise RuntimeError('Supervisor did not finish cleanup')


if __name__ == '__main__':
    main()
