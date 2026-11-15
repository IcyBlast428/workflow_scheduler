"""Real isolated PostgreSQL checks for NewDB's bounded thread-offload API."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

import test_local_integration  # Initializes only the disposable local wfstest DB.
from app.bootstrap import connection_settings as settings
from app.common.database import NewDB
from app.common.db import async_worker


class NewDBAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.environment = patch.dict(os.environ, {'WFS_DATA_DIR': temporary.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(NewDB.dispose_pool)
        from scripts.test_database import business_profile
        self.profile = settings.validate(business_profile())
        settings.save(self.profile)
        # Business connections deliberately use a separate, unique test table.
        self.table = 'async_newdb_' + uuid.uuid4().hex[:12]
        with NewDB('pg_reports') as db:
            db.execute(f'CREATE TABLE {self.table}(id INTEGER PRIMARY KEY, value TEXT)')
        self.addCleanup(self.drop_table)

    def drop_table(self):
        with NewDB('pg_reports') as db:
            db.execute(f'DROP TABLE IF EXISTS {self.table}')

    async def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail('Worker did not finish within the test deadline')
            await asyncio.sleep(0.01)

    async def test_crud_batch_parameters_and_legacy_aliases(self):
        async with NewDB('pg_reports') as db:
            self.assertEqual(await db.async_execute(
                f'INSERT INTO {self.table} VALUES(?, ?)', (1, "中文'100%")), 1)
            self.assertEqual(await db.async_executemany(
                f'INSERT INTO {self.table} VALUES(:id, :value)',
                [{'id': 2, 'value': 'two'}, {'id': 3, 'value': 'three'}]), 2)
            self.assertEqual(await db.async_execute_single_sql(
                f'UPDATE {self.table} SET value=? WHERE id=?', ('changed', 2)), 1)
            self.assertEqual(await db.async_query(
                f'SELECT value FROM {self.table} WHERE id=?', (1,), as_dict=True),
                [{'value': "中文'100%"}])
            self.assertEqual(await db.async_query_sql(
                f'SELECT value FROM {self.table} WHERE id=:id', {'id': 2}), [('changed',)])
            self.assertEqual(await db.async_query_sql(
                'SELECT ? AS value', (42,), as_dict=True), [{'value': 42}])
            self.assertEqual(await db.async_query_sql_return_json(
                'SELECT ? AS value', (7,)), [{'value': 7}])
            self.assertEqual(await db.async_insert_many(f'INSERT INTO {self.table} VALUES(?, ?)', []), 0)
            await db.async_insert_many(f'INSERT INTO {self.table} VALUES(?, ?)', [(4, 'four')])
            self.assertEqual(await db.async_execute(f'DELETE FROM {self.table} WHERE id=?', (3,)), 1)
            self.assertEqual(await db.async_query(f'SELECT COUNT(*) FROM {self.table}'), [(3,)])
            with self.assertRaises(ValueError):
                await db.async_query('SELECT ?, ?', (1,))
            with self.assertRaisesRegex(NotImplementedError, 'AsyncEngine'):
                await db.get_async_engine()
            self.assertEqual(db.get_engine().pool.checkedout(), 0)

    async def test_transactions_commit_rollback_and_share_worker_connection(self):
        owner = threading.get_ident()
        db = NewDB('pg_reports')
        def save(tx):
            self.assertNotEqual(owner, threading.get_ident())
            first = tx.query('SELECT pg_backend_pid()')[0][0]
            tx.execute(f'INSERT INTO {self.table} VALUES(?, ?)', (1, 'one'))
            tx.execute(f'INSERT INTO {self.table} VALUES(?, ?)', (2, 'two'))
            self.assertEqual(tx.query('SELECT pg_backend_pid()')[0][0], first)
            return tx.query(f'SELECT COUNT(*) FROM {self.table}')[0][0]
        self.assertEqual(await db.async_transaction(save), 2)
        def fail(tx):
            tx.execute(f'INSERT INTO {self.table} VALUES(?, ?)', (3, 'rolled back'))
            tx.execute(f'INSERT INTO {self.table} VALUES(?, ?)', (1, 'duplicate'))
        with self.assertRaises(IntegrityError):
            await db.async_transaction(fail)
        self.assertEqual(await db.async_query(f'SELECT COUNT(*) FROM {self.table}'), [(2,)])
        self.assertEqual(db.get_engine().pool.checkedout(), 0)
        db.close()

    async def test_concurrency_uses_worker_handles_and_keeps_event_loop_responsive(self):
        db = NewDB('pg_reports')
        worker_threads = set()
        engine = db.get_engine()
        def checkout(*_args):
            worker_threads.add(threading.get_ident())
        event.listen(engine, 'checkout', checkout)
        calls = [asyncio.create_task(db.async_query('SELECT ?, pg_sleep(0.03)', (index,))) for index in range(12)]
        ticks = 0
        while not all(call.done() for call in calls):
            ticks += 1
            await asyncio.sleep(0.005)
        results = await asyncio.gather(*calls)
        self.assertEqual([result[0][0] for result in results], list(range(12)))
        self.assertGreater(ticks, 3)
        self.assertGreater(len(worker_threads), 1)
        self.assertNotIn(threading.get_ident(), worker_threads)
        self.assertEqual(engine.pool.checkedout(), 0)
        db.close()

    async def test_sync_transaction_and_async_callback_are_rejected(self):
        async with NewDB('pg_reports') as db:
            with db.transaction():
                with self.assertRaisesRegex(RuntimeError, '同步事务'):
                    await db.async_execute(f'INSERT INTO {self.table} VALUES(?, ?)', (1, 'no'))
            async def invalid(tx):
                return tx.query('SELECT 1')
            with self.assertRaisesRegex(TypeError, '同步函数'):
                await db.async_transaction(invalid)
            def returns_coroutine(tx):
                tx.execute(f'INSERT INTO {self.table} VALUES(?, ?)', (1, 'rolled back'))
                return invalid(tx)
            with self.assertRaisesRegex(TypeError, 'awaitable'):
                await db.async_transaction(returns_coroutine)
            self.assertEqual(await db.async_query(f'SELECT COUNT(*) FROM {self.table}'), [(0,)])

    async def test_running_cancellation_does_not_retry_or_abandon_connection(self):
        db = NewDB('pg_reports')
        engine = db.get_engine()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def work(tx):
            calls.append(1)
            tx.execute(f'INSERT INTO {self.table} VALUES(?, ?)', (1, 'committed after await cancellation'))
            started.set()
            try:
                if not release.wait(5):
                    raise TimeoutError('Test worker release timed out')
            finally:
                finished.set()
        operation = asyncio.create_task(db.async_transaction(work))
        try:
            await self.wait_for(started.is_set)
            operation.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await operation
            self.assertEqual(engine.pool.checkedout(), 1)
        finally:
            release.set()
            await self.wait_for(lambda: finished.is_set() and engine.pool.checkedout() == 0)
        self.assertEqual(calls, [1])
        self.assertEqual(await db.async_query(f'SELECT COUNT(*) FROM {self.table}'), [(1,)])
        db.close()

    async def test_authorization_is_required_and_snapshot_does_not_reload_in_worker(self):
        with patch.dict(os.environ, {'WFS_TASK_CONNECTIONS_JSON': '{}'}):
            with self.assertRaises(PermissionError):
                NewDB('pg_reports')
            with self.assertRaises(ValueError):
                NewDB('platform')
        db = NewDB('pg_reports')
        with patch('app.common.db.factory.load_database_config', side_effect=AssertionError('unexpected reload')):
            self.assertEqual(await db.async_query('SELECT ?', (123,)), [(123,)])
        db.close()

    async def test_pending_budget_and_queued_cancellation_release_permits(self):
        started, release = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        permits = threading.BoundedSemaphore(2)
        state = (os.getpid(), executor, permits)
        def blocked():
            started.set()
            if not release.wait(5):
                raise TimeoutError('Test worker release timed out')
            return 'finished'
        try:
            with patch.object(async_worker, '_state', state):
                first = asyncio.create_task(async_worker.run_in_database_worker(blocked))
                await self.wait_for(started.is_set)
                second = asyncio.create_task(async_worker.run_in_database_worker(lambda: 'queued'))
                await asyncio.sleep(0)
                with self.assertRaises(async_worker.AsyncDatabaseBusyError):
                    await async_worker.run_in_database_worker(lambda: 'overflow')
                second.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await second
                release.set()
                self.assertEqual(await first, 'finished')
                self.assertEqual(await async_worker.run_in_database_worker(lambda: 'recovered'), 'recovered')
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)

    @unittest.skipUnless(hasattr(os, 'fork'), 'fork is not available on this platform')
    async def test_worker_pool_is_recreated_after_fork(self):
        # Warm parent threads first; the child must not reuse that executor.
        self.assertEqual(await async_worker.run_in_database_worker(lambda: 7), 7)
        reader, writer = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(reader)
            try:
                value = asyncio.run(async_worker.run_in_database_worker(lambda: 9))
                os.write(writer, str(value).encode())
                os._exit(0)
            except BaseException:
                os._exit(1)
        os.close(writer)
        import select
        try:
            ready, _, _ = select.select([reader], [], [], 5)
            if not ready:
                import signal
                os.kill(child, signal.SIGKILL)
            self.assertTrue(ready, 'Child reused an inherited worker pool and stalled')
            self.assertEqual(os.read(reader, 10), b'9')
        finally:
            os.close(reader)
            _, status = os.waitpid(child, 0)
        self.assertEqual(status, 0)


if __name__ == '__main__':
    unittest.main()
