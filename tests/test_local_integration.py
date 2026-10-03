"""Local integration checks that do not require the production GaussDB."""

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from apscheduler.events import EVENT_JOB_MISSED

from werkzeug.security import generate_password_hash


_tmp = tempfile.TemporaryDirectory()
os.environ['WFS_ENV'] = 'development'
os.environ['WFS_ENABLE_SCHEDULER'] = 'false'
os.environ['WFS_LOCAL_DB_PATH'] = str(Path(_tmp.name) / 'wfs.sqlite3')
os.environ['WFS_DATA_DIR'] = str(Path(_tmp.name) / 'data')
os.environ['WFS_SECRET_KEY'] = 'local-integration-secret-key'
os.environ['WFS_ADMIN_PASSWORD_HASH'] = generate_password_hash('test-password', method='scrypt')

from app import create_app  # noqa: E402
from app.bootstrap.core import execute_py  # noqa: E402
from app.bootstrap.database import GaussDB  # noqa: E402
from app.bootstrap.schedule_config import save_schedule  # noqa: E402
from app.bootstrap.global_vars import runnings  # noqa: E402
from app.bootstrap import core  # noqa: E402
from app.api.task import views as task_views  # noqa: E402
from scripts.migrate import main as migrate  # noqa: E402


class LocalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.testing = True

    def test_login_cookie_and_csrf(self):
        client = self.app.test_client()
        self.assertEqual(client.get('/api/taskinfo/state').status_code, 401)
        login = client.post('/api/user/login', json={'username': 'admin', 'password': 'test-password'})
        self.assertEqual(login.status_code, 200)
        csrf = login.json['data']['csrf_token']
        self.assertIn('HttpOnly', login.headers['Set-Cookie'])
        saved_cookie = login.headers['Set-Cookie'].split(';', 1)[0].split('=', 1)[1]
        self.assertEqual(client.post('/api/taskinfo/groups').status_code, 403)
        self.assertEqual(client.post('/api/taskinfo/groups', headers={'X-CSRF-Token': csrf}).status_code, 200)
        self.assertEqual(client.post('/api/user/logout', headers={'X-CSRF-Token': csrf}).status_code, 200)
        self.assertEqual(client.get('/api/taskinfo/state').status_code, 401)
        replay = self.app.test_client()
        replay.set_cookie('session', saved_cookie)
        self.assertEqual(replay.get('/api/user/info').status_code, 401)

    def test_expired_session_is_rejected(self):
        client = self.app.test_client()
        client.post('/api/user/login', json={'username': 'admin', 'password': 'test-password'})
        with GaussDB() as db:
            db.execute_sql("UPDATE wfs_auth_sessions SET expires_at='2000-01-01 00:00:00'")
        self.assertEqual(client.get('/api/user/info').status_code, 401)

    def test_failed_schedule_save_preserves_previous_record(self):
        pid = 'testJob__test_job1'
        form = {'schedule_type': 'every_hour', 'enabled': False, 'main_file': 'main.py'}
        save_schedule(pid, form)
        original = GaussDB.execute_sql

        def fail_insert(db, sql, params=None):
            if 'INSERT INTO wfs_task_config' in sql:
                raise RuntimeError('injected insert failure')
            return original(db, sql, params)

        with patch.object(GaussDB, 'execute_sql', fail_insert):
            with self.assertRaises(RuntimeError):
                save_schedule(pid, {'schedule_type': 'every_minute', 'enabled': True, 'main_file': 'main.py'})

        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT schedule_type FROM wfs_task_config WHERE pid=?', params=(pid,))
        self.assertEqual(rows[0][0], 'every_hour')

    def test_large_task_output_is_bounded(self):
        script = Path(_tmp.name) / 'large_output.py'
        script.write_text('print("x" * 1000000)\n', encoding='utf-8')
        execute_py(script, 'large_output', timeout_seconds=10)
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT tasklog, state FROM wfs_run_history WHERE pid=?', params=('large_output',))
        self.assertEqual(rows[0][1], 0)
        self.assertLess(len(rows[0][0]), 66000)
        self.assertIn('truncated', rows[0][0])

    def test_manual_queue_reserves_automatic_concurrency(self):
        pid = 'testJob__test_job1'
        save_schedule(pid, {'schedule_type': 'every_hour', 'enabled': False, 'main_file': 'main.py'})
        with patch.object(core.scheduler, 'add_job') as add_job:
            core.call_task_once(pid)
            reservation = add_job.call_args.kwargs['args'][-1]
            try:
                self.assertIsNone(runnings.claim(pid, 1))
                with self.assertRaises(ValueError):
                    core.call_task_once(pid)
            finally:
                runnings.remove(reservation)
                core._manual_reservations.pop(add_job.call_args.kwargs['id'], None)
        self.assertFalse(runnings.is_running(pid))

    def test_missed_manual_job_releases_reservation(self):
        pid = 'testJob__test_job1'
        with patch.object(core.scheduler, 'add_job') as add_job:
            core.call_task_once(pid)
            job_id = add_job.call_args.kwargs['id']
        with patch.object(core.scheduler, 'get_job', return_value=None):
            core.my_listener(SimpleNamespace(job_id=job_id, code=EVENT_JOB_MISSED))
        self.assertFalse(runnings.is_running(pid))

    def test_database_failure_does_not_keep_running_slot(self):
        script = Path(_tmp.name) / 'success.py'
        script.write_text('print("finished")\n', encoding='utf-8')
        with patch('app.bootstrap.operations.GaussDB', side_effect=RuntimeError('injected database failure')):
            with self.assertLogs('app.bootstrap.operations', level='ERROR'):
                self.assertEqual(execute_py(script, 'database_failure'), 0)
        self.assertFalse(runnings.is_running('database_failure'))

    @unittest.skipIf(os.name == 'nt', 'Linux process group check')
    def test_timeout_kills_descendants_that_ignore_termination(self):
        script = Path(_tmp.name) / 'timeout.py'
        child_pid_file = Path(_tmp.name) / 'child.pid'
        script.write_text(
            'import subprocess, sys, signal, time\n'
            'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            'child = subprocess.Popen([sys.executable, "-c", '
            '"import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])\n'
            f'open({str(child_pid_file)!r}, "w").write(str(child.pid))\n'
            'time.sleep(60)\n', encoding='utf-8')
        self.assertEqual(execute_py(script, 'timeout_tree', timeout_seconds=1), -9)
        self.assertFalse(runnings.is_running('timeout_tree'))
        pid = child_pid_file.read_text()
        stat = Path(f'/proc/{pid}/stat')
        if stat.exists():
            self.assertEqual(stat.read_text().split()[2], 'Z', 'descendant must not remain running')

    def test_cancel_stops_all_instances(self):
        pid = 'cancel_instances'
        script = Path(_tmp.name) / 'cancel.py'
        script.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
        reservations = [runnings.claim(pid, 2), runnings.claim(pid, 2)]
        threads = [threading.Thread(target=execute_py, args=(script, pid), kwargs={'reservation': r}) for r in reservations]
        try:
            for thread in threads:
                thread.start()
            deadline = time.monotonic() + 5
            while not all(r[pid] for r in reservations) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(all(r[pid] for r in reservations))
        finally:
            runnings.cancel(pid)
            for thread in threads:
                thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(runnings.is_running(pid))
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT state FROM wfs_run_history WHERE pid=?', params=(pid,))
        self.assertEqual([row[0] for row in rows], [-15, -15])

    def test_migrations_are_idempotent(self):
        migrate()
        migrate()
        with GaussDB() as db:
            names = db.execute_query_sql('SELECT name FROM wfs_schema_migrations')
        from scripts.migrate import MIGRATIONS
        self.assertEqual({row[0] for row in names}, {path.name for path in MIGRATIONS.glob('[0-9][0-9][0-9]_*.sql')})

    def test_update_check_only_reads_versions(self):
        with patch('pathlib.Path.is_file', return_value=False), patch.object(task_views, '_run_git_command', side_effect=[(0, 'a' * 40, ''), (0, 'b' * 40 + '\trefs/heads/main', '')]) as git:
            ok, message = task_views._update_code_to_configured_branch()
        self.assertTrue(ok)
        self.assertIn('发现新版本', message)
        self.assertEqual([call.args[0][0] for call in git.call_args_list], ['rev-parse', 'ls-remote'])


if __name__ == '__main__':
    unittest.main()
