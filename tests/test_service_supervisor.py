"""Exercise real child process lifecycle without changing systemd or running jobs."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scripts import serve


@unittest.skipIf(os.name != 'posix', 'Linux process groups and locks')
class SupervisorTests(unittest.TestCase):
    def services(self, scheduler=None, web=None):
        wait = 'import time; time.sleep(60)'
        return [('scheduler', [sys.executable, '-c', scheduler or wait], 1),
                ('web', [sys.executable, '-c', web or wait], 2)]

    def run_supervisor(self, services, readiness=lambda port: True, timeout=.2, stop_after=None):
        instance = serve.Supervisor(Path.cwd(), serve.child_environment(), startup_timeout=timeout, stop_timeout=.15)
        if stop_after:
            timer = threading.Timer(stop_after, instance.request_stop)
            timer.start()
            self.addCleanup(timer.cancel)
        with patch.object(serve, 'ready', side_effect=readiness):
            code = instance.run(services)
        self.assertTrue(all(process.poll() is not None for _, process in instance.children))
        return instance, code

    def test_roles_workers_and_environment_are_pinned(self):
        specs = serve.commands('/data/workflow_scheduler', '/python', '127.0.0.1', 8008, 8009, '/data', '/logs')
        for role, command, port in specs:
            scheduler = role == 'scheduler'
            self.assertEqual(command[command.index('--workers') + 1], '1' if scheduler else '2')
            self.assertIn('WFS_ENABLE_SCHEDULER=' + ('true' if scheduler else 'false'), command)
            self.assertIn('WFS_SCHEDULER_CONTROL_URL=' + ('' if scheduler else 'http://127.0.0.1:8009'), command)
            self.assertIn('127.0.0.1:' + str(port), command)
        with patch.dict(os.environ, GUNICORN_CMD_ARGS='--preload --workers=8', GUNICORN_FD='5'):
            environment = serve.child_environment()
        self.assertNotIn('GUNICORN_CMD_ARGS', environment)
        self.assertNotIn('GUNICORN_FD', environment)

    def test_main_pins_one_encrypted_configuration_for_all_children(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            environment={**serve.child_environment(),'WFS_SECRET_KEY':'supervisor-test-key'}
            observed=[]
            instance=SimpleNamespace(environment=environment,request_stop=lambda *args:None)
            def run(services):
                target=Path(instance.environment['WFS_PLATFORM_ACTIVE_CONFIG_FILE'])
                self.assertTrue(target.is_file())
                self.assertEqual(target.parent,root/'data/platform-runtime')
                self.assertEqual([role for role,_,_ in services],['scheduler','web'])
                observed.append(target)
                return 0
            instance.run=run
            args=['serve','--project',str(root),'--data',str(root/'data')]
            with patch.object(serve.sys,'argv',args),patch.object(serve,'Supervisor',return_value=instance),patch.object(serve,'check_ports'),patch.object(serve.signal,'signal'):
                self.assertEqual(serve.main(),0)
            self.assertEqual(len(observed),1)
            self.assertFalse(observed[0].exists())

    def test_orderly_stop_reaps_both_roles(self):
        instance, code = self.run_supervisor(self.services(), stop_after=.3)
        self.assertEqual(code, 0)
        self.assertEqual([role for role, _ in instance.children], ['scheduler', 'web'])

    def test_either_child_exit_including_zero_fails_whole_service(self):
        for role in ('scheduler', 'web'):
            for status in (0, 3):
                with self.subTest(role=role, status=status):
                    fail = f'import time; time.sleep(.1); raise SystemExit({status})'
                    instance, code = self.run_supervisor(self.services(**{role: fail}))
                    self.assertEqual(code, 1)

    def test_scheduler_not_ready_never_starts_web(self):
        instance, code = self.run_supervisor(self.services(), readiness=lambda port: False)
        self.assertEqual(code, 1)
        self.assertEqual([role for role, _ in instance.children], ['scheduler'])

    def test_web_start_failure_cleans_scheduler(self):
        services = self.services()
        services[1] = ('web', ['/definitely/missing/wfs-test-executable'], 2)
        instance, code = self.run_supervisor(services)
        self.assertEqual(code, 1)
        self.assertEqual(len(instance.children), 1)

    def test_unresponsive_children_are_killed_within_shutdown_deadline(self):
        stubborn = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
        started = time.monotonic()
        instance, code = self.run_supervisor(self.services(stubborn, stubborn), stop_after=.3)
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(all(process.returncode == -signal.SIGKILL for _, process in instance.children))

    def test_preexisting_stop_starts_nothing(self):
        instance = serve.Supervisor(Path.cwd(), serve.child_environment())
        instance.request_stop()
        self.assertEqual(instance.run(self.services()), 0)
        self.assertEqual(instance.children, [])

    def test_lock_prevents_second_supervisor_and_releases_after_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            with serve.instance_lock(temporary):
                with self.assertRaisesRegex(RuntimeError, 'Another service'), serve.instance_lock(temporary):
                    pass
            with serve.instance_lock(temporary):
                pass

    def test_busy_port_is_not_reused_as_a_false_readiness_signal(self):
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, 'already in use'):
                serve.check_ports('127.0.0.1', port, port)


if __name__ == '__main__':
    unittest.main()
