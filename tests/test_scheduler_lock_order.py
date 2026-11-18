"""Concurrency regressions at release, dispatch and scheduled firing boundaries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.bootstrap import admission, core, execution_requests
from app.bootstrap.timebase import business_now


class SchedulerLockOrderTests(unittest.TestCase):
    def test_dispatch_waiting_for_configuration_leaves_admission_available(self):
        configuration = threading.RLock()
        dispatch_waiting = threading.Event()

        class ConfigurationLock:
            def __enter__(self):
                dispatch_waiting.set()
                configuration.acquire()

            def __exit__(self, *args):
                configuration.release()

        @core.serialized_configuration
        def submit():
            return 'one-run'

        db = Mock()
        db.execute.return_value.fetchone.return_value = None
        with (
            patch.object(core, '_configuration_lock', ConfigurationLock()),
            patch.object(admission, 'store', return_value=nullcontext(db)),
            patch.object(admission, 'maintenance', return_value={'enabled': False}),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            # Release activation owns configuration, then needs admission to commit.
            with configuration:
                result = pool.submit(admission.manual_request, 'admin', 'task', 'request_123456789', submit)
                self.assertTrue(dispatch_waiting.wait(5))
                self.assertTrue(admission.lock.acquire(blocking=False),
                                'Dispatch held admission while waiting for release activation')
                admission.lock.release()
            self.assertEqual(result.result(timeout=5)['run_id'], 'one-run')

    def test_scheduled_firing_reads_maintenance_inside_the_enqueue_transaction(self):
        job = SimpleNamespace(args=['entry.py', 'sample'], kwargs={}, misfire_grace_time=60)
        db = Mock()

        def execute(sql, params=()):
            cursor = Mock()
            cursor.fetchone.return_value = ('{"enabled":true}',) if 'FROM settings' in sql else None
            return cursor

        db.execute.side_effect = execute
        policy = {'max_wait_seconds': 60, 'stagger_seconds': 0, 'parameters': {}}
        with (
            patch.object(execution_requests, 'load', return_value=policy),
            patch('app.bootstrap.task_packages.storage_root', return_value=Path.cwd()),
            patch.object(admission, 'store', return_value=nullcontext(db)),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            # APScheduler already holds its job-store lock on this thread. A
            # publisher can hold admission while waiting to register its job.
            with admission.lock:
                firing = pool.submit(execution_requests.enqueue_scheduled, job, business_now())
                self.assertTrue(firing.result(timeout=5).startswith('schedule_'))
        calls = db.execute.call_args_list
        self.assertEqual(calls[0].args, ('BEGIN',))
        self.assertIn('FROM settings', calls[-2].args[0])
        self.assertEqual(calls[-1].args[1][3], 'cancelled')
