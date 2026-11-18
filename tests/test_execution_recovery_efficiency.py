"""Isolated execution recovery and read-path regressions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.bootstrap import journal, operations


def record(identifier, status='running'):
    return {
        'run_id': f'{identifier:032x}',
        'pid': 'reports',
        'status': status,
        'created_at': f'2026-01-01 00:00:{identifier:02d}',
        'heartbeat': '2026-01-01 00:00:00',
        'db_synced': True,
    }


class ExecutionRecoveryEfficiencyTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.platform = stack.enter_context(patch.object(operations, 'GaussDB'))
        self.database = self.platform.return_value.__enter__.return_value
        self.database.execute_query_sql.return_value = []
        stack.enter_context(patch.object(operations, '_service_state', {'ready': False}))
        stack.enter_context(patch.object(operations, '_heartbeats', {}))
        stack.enter_context(patch.object(operations, '_directory', Path('unused-test-directory')))

    def test_overlapping_recent_lists_only_make_two_queries(self):
        records = [record(index) for index in range(50)]
        self.database.execute_query_sql.return_value = [(json.dumps(item),) for item in records]
        connection = MagicMock()
        store = connection.return_value.__enter__.return_value
        store.execute.return_value = [(json.dumps({**item, 'status': 'success'}),) for item in records]

        with patch.object(journal, 'connection', connection), patch.object(journal, '_spooled', return_value=[]):
            actual = operations.list_runs('reports', 50)

        self.assertEqual(len(actual), 50)
        self.assertTrue(all(item['status'] == 'success' for item in actual))
        self.database.execute_query_sql.assert_called_once()
        store.execute.assert_called_once()

    def test_missing_journal_rows_are_read_in_one_batch_with_spool_precedence(self):
        first, second, third = [record(index) for index in (1, 2, 3)]
        self.database.execute_query_sql.return_value = [(json.dumps(item),) for item in (first, second, third)]
        connection = MagicMock()
        store = connection.return_value.__enter__.return_value
        store.execute.side_effect = [
            [(json.dumps(first),)],
            [(json.dumps({**second, 'status': 'success'}),)],
        ]
        spool = {third['run_id']: {**third, 'status': 'failed'}}

        with patch.object(journal, 'connection', connection), patch.object(journal, '_spooled', return_value=[]), \
                patch.object(journal, 'read_spooled', side_effect=lambda directory, run_id: spool.get(run_id)):
            actual = operations.list_runs('reports', 3)

        self.assertEqual([item['status'] for item in actual], ['failed', 'success', 'running'])
        self.assertEqual(store.execute.call_count, 2)
        self.assertEqual(store.execute.call_args.args[1], (second['run_id'],))

    def test_listing_degrades_to_recovery_files_when_both_indexes_fail(self):
        pending = record(1)
        self.database.execute_query_sql.side_effect = RuntimeError('index offline')
        with patch.object(journal, 'connection', side_effect=RuntimeError('journal offline')), \
                patch.object(journal, '_spooled', return_value=[pending]), self.assertLogs(level='WARNING'):
            self.assertEqual(operations.list_runs('reports'), [pending])

    def test_periodic_replay_never_recovers_running_tasks_as_orphans(self):
        with patch.object(journal, 'recover_pending', return_value=[record(1)]) as replay, \
                patch.object(journal, 'pending', return_value=[]), patch.object(journal, 'expire', return_value=0), \
                patch('app.bootstrap.run_summary.backfill'), patch('app.bootstrap.storage_policy.run_cycle'), \
                patch.object(operations, '_recover_record') as recover:
            operations.maintenance()

        replay.assert_called_once()
        recover.assert_not_called()

    def test_startup_recovers_known_and_spool_only_runs_once(self):
        earlier, spool_only = record(1), record(2)
        self.database.execute_query_sql.side_effect = [[(earlier['run_id'],)], []]
        with patch.object(journal, 'recover_pending', return_value=[]), \
                patch.object(journal, 'active', return_value=[earlier, spool_only]) as active, \
                patch.object(journal, 'pending', return_value=[]), patch.object(journal, 'expire', return_value=0), \
                patch('app.bootstrap.run_summary.backfill'), patch.object(operations, '_recover_record') as recover, \
                patch.object(operations, 'read_run', side_effect=[earlier, spool_only]):
            operations.maintenance(recover=True)

        active.assert_called_once_with(operations._directory, spool_limit=None)
        self.assertEqual([call.args[0] for call in recover.call_args_list], [earlier, spool_only])

    def test_startup_does_not_stop_a_run_that_the_journal_already_marked_terminal(self):
        finished = record(1, status='success')
        finished['systemd_unit'] = 'wfs-task-' + finished['run_id'] + '.service'
        with patch('app.bootstrap.task_isolation.stop') as stop, patch.object(operations, 'update_run') as update:
            operations._recover_record(finished)

        stop.assert_not_called()
        update.assert_not_called()

    def test_replay_reads_latest_file_after_acquiring_the_run_lock(self):
        latest = record(1)
        run_id = latest['run_id']
        enumerated = threading.Event()

        def scan(*args):
            enumerated.set()
            yield run_id

        with patch.object(journal, '_spool_ids', side_effect=scan), \
                patch.object(journal, 'read_spooled', side_effect=lambda *args: latest.copy()) as read, \
                patch.object(journal, '_write_index', return_value=True), ThreadPoolExecutor(max_workers=1) as worker:
            with journal.run_lock(run_id):
                replay = worker.submit(journal.recover_pending, operations._directory, operations.TERMINAL, 1)
                self.assertTrue(enumerated.wait(timeout=2))
                read.assert_not_called()
                latest['status'] = 'success'
            self.assertEqual(replay.result(timeout=2), [latest])

    def test_heartbeat_only_updates_live_records_in_memory(self):
        running = record(1)
        stamp = '2026-01-01 00:01:00'
        with patch.object(journal, 'read', return_value=running), \
                patch.object(journal, 'recent', return_value=[running]), \
                patch.object(journal, 'write') as write, patch.object(operations, 'now', return_value=stamp):
            operations.touch_run(running['run_id'])
            self.assertEqual(operations.read_run(running['run_id'])['heartbeat'], stamp)
            self.assertEqual(operations.list_runs()[0]['heartbeat'], stamp)
            write.assert_not_called()

            operations.forget_run_heartbeat(running['run_id'])
            self.assertEqual(operations.read_run(running['run_id'])['heartbeat'], running['heartbeat'])

    def test_reconciliation_skips_recycled_tasks_and_retries_restored_tasks(self):
        self.database.execute_query_sql.side_effect = [
            [('task', '{"deleted_at":"2026-01-01"}'), ('other', '{"deleted_at":null}')],
            [('task', '{"deleted_at":null}')],
        ]
        with patch('app.bootstrap.core.aps_start') as refresh:
            operations._reconcile_configuration()
            refresh.assert_called_once_with(task_pid='other', action='refresh')
            refresh.reset_mock()
            operations._reconcile_configuration()
            refresh.assert_called_once_with(task_pid='task', action='refresh')
