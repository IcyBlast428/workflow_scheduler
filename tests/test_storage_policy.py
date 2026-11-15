"""Production-shaped history storage behavior on a disposable PostgreSQL schema."""
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

import test_local_integration as fixture
from app import create_app
from app.bootstrap import operations, storage_policy, run_summary
from app.bootstrap.database import GaussDB
from app.bootstrap.history import RUN_COLUMNS, archive_batch
from app.bootstrap.timebase import business_now
from app.bootstrap.snapshot_cache import invalidate
from app.api.task import views
from scripts.upgrade_performance_indexes import INDEXES, upgrade


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        storage_policy.invalidate_policy()
        invalidate()
        self.pid = 'storage-' + uuid.uuid4().hex
        self.client = create_app().test_client()
        result = self.client.post('/api/user/login', json={'username': 'admin', 'password': 'test-password'})
        self.headers = {'X-CSRF-Token': result.json['data']['csrf_token']}
        self.url = '/api/admin/operational/history-storage'

    def tearDown(self):
        storage_policy.invalidate_policy()

    def insert(self, identifier, state=0):
        ended = business_now() - dt.timedelta(days=120)
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           params=(identifier, self.pid, 'test', '', '', '', state, 'KEEP 中文', ended, ended))
            run_summary.summarize_row(db, identifier, self.pid, state, ended)

    def test_policy_api_validation_cas_and_csrf(self):
        current = self.client.get(self.url).json['data']
        self.assertFalse(current['policy']['archive_enabled'])
        self.assertEqual(current['archive_location'], 'same_database')
        form = {**current['policy'], 'archive_enabled': True, 'archive_batch_size': 20}
        self.assertEqual(self.client.post(self.url, json=form).status_code, 403)
        result = self.client.post(self.url, json=form, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['data']['policy']['revision'], 1)
        self.assertEqual(storage_policy.load()['archive_batch_size'], 20)
        self.assertEqual(self.client.post(self.url, json=form, headers=self.headers).status_code, 409)
        for key, value in [('online_days', 89), ('success_excerpt_kib', -1),
                           ('failure_excerpt_kib', 64), ('archive_enabled', 'yes'),
                           ('archive_budget_seconds', True), ('archive_batch_size', 1001)]:
            with self.subTest(key=key):
                invalid = {**result.json['data']['policy'], key: value}
                self.assertEqual(self.client.post(self.url, json=invalid, headers=self.headers).status_code, 400)

    def test_bounded_cycle_retains_all_rows_and_reports_remaining(self):
        for i in range(5):
            self.insert(self.pid + str(i), state=1 if i % 2 else 0)
        self.assertIsNone(storage_policy.run_cycle())
        storage_policy.save({**storage_policy.DEFAULT, 'archive_enabled': True,
                             'archive_batch_size': 2, 'archive_batches_per_cycle': 1}, 'admin')
        state = storage_policy.run_cycle()
        self.assertEqual((state['moved'], state['batches'], state['has_more']), (2, 1, True))
        self.assertFalse(state['error'])
        with GaussDB() as db:
            online = db.execute_query_sql('SELECT count(*) FROM wfs_run_history WHERE pid=?', params=(self.pid,))[0][0]
            archived = db.execute_query_sql('SELECT count(*) FROM wfs_run_history_archive WHERE pid=?', params=(self.pid,))[0][0]
        self.assertEqual((online, archived), (3, 2))
        self.assertEqual(storage_policy.snapshot()['status']['moved'], 2)
        storage_policy.run_cycle()
        final = storage_policy.run_cycle()
        self.assertFalse(final['has_more'])

    def test_time_budget_stops_between_batches_and_surfaces_failures(self):
        form = {**storage_policy.DEFAULT, 'archive_enabled': True,
                'archive_batch_size': 2, 'archive_batches_per_cycle': 2, 'archive_budget_seconds': 1}
        storage_policy.save(form, 'admin')
        with patch('app.bootstrap.history.archive_batch', return_value=2) as batch, \
             patch('app.bootstrap.history.archive_pending', return_value=True), \
             patch.object(storage_policy, '_clock', side_effect=[0, 0.1, 1.1, 1.2, 1.3]):
            state = storage_policy.run_cycle()
        self.assertEqual(batch.call_count, 1)
        self.assertTrue(state['budget_exhausted'])
        with patch('app.bootstrap.history.archive_batch', side_effect=RuntimeError('rollback')), \
             self.assertLogs('app.bootstrap.storage_policy', level='ERROR'):
            state = storage_policy.run_cycle()
        self.assertTrue(state['error'])
        self.assertEqual(state['moved'], 0)
        self.assertFalse(storage_policy._cycle_lock.locked())

    def test_batch_archive_verifies_content_without_per_row_round_trips(self):
        for i in range(50):
            self.insert(self.pid + str(i), state=1)
        original_query, original_write = GaussDB.execute_query_sql, GaussDB.execute_sql
        counts = [0, 0]
        def query(db, *args, **kwargs):
            counts[0] += 1
            return original_query(db, *args, **kwargs)
        def write(db, *args, **kwargs):
            counts[1] += 1
            return original_write(db, *args, **kwargs)
        with patch.object(GaussDB, 'execute_query_sql', query), patch.object(GaussDB, 'execute_sql', write):
            self.assertEqual(archive_batch(business_now() - dt.timedelta(days=90), 100), 50)
        self.assertLessEqual(sum(counts), 8, 'batch archival must not execute a query per row')
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT archived_failures FROM wfs_history_rollup WHERE pid=?', params=(self.pid,))[0][0], 50)
            rows = db.execute_query_sql('SELECT tasklog FROM wfs_run_history_archive WHERE pid=?', params=(self.pid,))
        self.assertEqual([row[0] for row in rows], ['KEEP 中文'] * 50)

    def test_short_summaries_preserve_utf8_error_tail_and_retained_file(self):
        success = storage_policy.history_excerpt({'state': 0}, '开始' + '汉字' * 2000)
        failure = storage_policy.history_excerpt({'state': 1, 'reason': '任务超时'}, '汉字' * 10000 + 'ERROR: end')
        self.assertLess(len(success.encode()), 2300)
        self.assertNotIn('\ufffd', success + failure)
        self.assertTrue(success.startswith('开始'))
        self.assertIn('ERROR: end', failure)
        self.assertTrue(failure.startswith('任务超时'))
        with tempfile.TemporaryDirectory() as folder, patch.object(operations, '_directory', Path(folder)):
            identifier = operations.create_run(self.pid)
            path = operations.run_path(identifier, 'log')
            output = 'HEAD\n' + '汉字' * 15000 + '\nTAIL'
            path.write_text(output, encoding='utf-8')
            record = operations.update_run(identifier, status='success', state=0,
                                           start_time=operations.now(), end_time=operations.now())
            with patch('app.bootstrap.notifications.enqueue_result') as notification:
                operations.save_history(record)
            self.assertGreater(len(notification.call_args.args[2].encode()), 60000)
            self.assertEqual(path.read_text(), output)
            with GaussDB() as db:
                stored = db.execute_query_sql('SELECT tasklog FROM wfs_run_history WHERE id=?', params=(identifier,))[0][0]
            self.assertLess(len(stored.encode()), 2300)
            self.assertTrue(operations.read_log(identifier, 'tail')['content'].endswith('TAIL'))
            preview = self.client.post('/api/taskinfo/taskLogDetail', query_string={'pid': self.pid}, headers=self.headers)
            self.assertEqual(preview.status_code, 200)
            self.assertTrue(preview.json['data'].endswith('TAIL'))

    def test_new_indexes_and_existing_schema_upgrade_are_repeatable(self):
        with GaussDB() as db:
            self.assertEqual(upgrade(db), [])
            db.execute_sql('DROP INDEX idx_wfs_run_start_id')
            self.assertEqual(upgrade(db), ['idx_wfs_run_start_id'])
            self.assertEqual(upgrade(db, apply=True), ['idx_wfs_run_start_id'])
            self.assertEqual(upgrade(db, apply=True), [])

    def test_index_upgrade_uses_supported_serialization_for_each_backend(self):
        for dialect in ('PostgreSQL', 'GaussDB/DWS'):
            with self.subTest(dialect=dialect):
                db = Mock(dialect=dialect)
                db.execute_query_sql.return_value = []
                self.assertEqual(upgrade(db, apply=True), list(INDEXES))
                queries = [call.args[0] for call in db.execute_query_sql.call_args_list]
                writes = [call.args[0] for call in db.execute_sql.call_args_list]
                if dialect == 'PostgreSQL':
                    self.assertIn('SELECT pg_advisory_xact_lock(184762902)', queries)
                    self.assertFalse(any(sql.startswith('LOCK TABLE') for sql in writes))
                else:
                    self.assertFalse(any('pg_advisory' in sql for sql in queries))
                    self.assertEqual(writes[0], 'LOCK TABLE wfs_schema_version IN EXCLUSIVE MODE')
                db.set_commit.assert_called_once()
                db.set_rollback.assert_not_called()

    def test_overview_marker_cache_keeps_live_events_fresh_and_invalidates(self):
        marker = {'id': self.pid, 'name': 'running', 'start_time': str(business_now()), 'source': 'live'}
        with patch.object(views, '_history_task_start_markers', return_value=[]) as read:
            self.assertEqual(views._load_task_start_markers(2, []), [])
            live = views._load_task_start_markers(2, [marker])
            self.assertEqual(len(live), 1)
            self.assertEqual(live[0]['id'], marker['id'])
            self.assertEqual(live[0]['source'], 'live')
            self.assertEqual(read.call_count, 1)
            invalidate()
            views._load_task_start_markers(2, [])
            self.assertEqual(read.call_count, 2)
