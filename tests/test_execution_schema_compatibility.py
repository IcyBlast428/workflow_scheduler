"""Exercise empty-string-to-NULL semantics using isolated PostgreSQL triggers.

This reproduces the relevant GaussDB A-mode behavior, not full DWS acceptance.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.bootstrap import admission, execution_requests, journal
from app.bootstrap.database import GaussDB
from scripts.init_database import initialize
from scripts.schema_compatibility import OPTIONAL_TEXT_COLUMNS, upgrade_optional_execution_fields
from scripts.sql_schema import statements


class ExecutionSchemaCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {'WFS_DATA_DIR': self.temp.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.remove_emulation)
        with GaussDB() as db:
            self.assertEqual(db.dialect, 'PostgreSQL')
            self.assertTrue(os.environ['WFS_DB_ID'].startswith('wfstest_test_'))
            for table, columns in OPTIONAL_TEXT_COLUMNS.items():
                assignments = ' '.join(f"NEW.{column} := NULLIF(NEW.{column}, '');" for column in columns)
                db.execute_sql(f'CREATE FUNCTION emulate_empty_{table}() RETURNS trigger AS $$ '
                               f'BEGIN {assignments} RETURN NEW; END; $$ LANGUAGE plpgsql')
                db.execute_sql(f'CREATE TRIGGER emulate_empty BEFORE INSERT OR UPDATE ON {table} '
                               f'FOR EACH ROW EXECUTE FUNCTION emulate_empty_{table}()')

    def remove_emulation(self):
        with GaussDB() as db:
            for table in OPTIONAL_TEXT_COLUMNS:
                db.execute_sql(f'DROP FUNCTION IF EXISTS emulate_empty_{table}() CASCADE')
            upgrade_optional_execution_fields(db)

    def test_legacy_failure_then_repeatable_upgrade_preserves_rows_and_required_ids(self):
        with GaussDB() as db:
            for table, columns in OPTIONAL_TEXT_COLUMNS.items():
                for column in columns:
                    db.execute_sql(f'ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT \'\'')
                    db.execute_sql(f'ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL')
        with admission.store() as db:
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?)',
                       ('admin', 'previous', 'task', 'accepted', 'old-run', 'retained', '2026-11-16'))
        with self.assertRaises(Exception) as failure:
            with admission.store() as db:
                db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?)',
                           ('admin', 'pending', 'task', 'pending', '', '', '2026-11-16'))
        self.assertEqual(failure.exception.sqlstate, '23502')
        self.assertIn('run_id', str(failure.exception))
        initialize()
        with admission.store() as db:
            self.assertEqual(db.execute('SELECT run_id,message FROM receipts WHERE key=?', ('previous',)).fetchone(),
                             ('old-run', 'retained'))
        with GaussDB() as db:
            self.assertEqual(upgrade_optional_execution_fields(db), [])
            for table, column in [('wfs_executions', 'run_id'), ('wfs_state_journal_journal', 'run_id'),
                                  ('wfs_state_admission_receipts', 'key'), ('wfs_state_admission_work_requests', 'id')]:
                value = db.execute_query_sql('SELECT is_nullable FROM information_schema.columns '
                                             'WHERE table_schema=current_schema() AND table_name=? AND column_name=?',
                                             params=(table, column))
                self.assertEqual(value[0][0], 'NO')
        self.assertEqual(admission.manual_request('admin', 'task', 'new_request_123456', lambda: 'new-run')['run_id'], 'new-run')

    def test_manual_pending_receipt_is_nullable_then_accepts_exactly_one_submission(self):
        def submit():
            with admission.store() as db:
                self.assertEqual(db.execute('SELECT status,run_id,message FROM receipts').fetchone(), ('pending', None, None))
            return 'a' * 32
        with patch('app.bootstrap.core.call_task_once', side_effect=submit) as start:
            first = admission.manual_request('admin', 'task', 'manual_request_123456', start)
            replay = admission.manual_request('admin', 'task', 'manual_request_123456', start)
            self.assertEqual(start.call_count, 1)
            self.assertFalse(first['replayed'])
            self.assertTrue(replay['replayed'])
            self.assertEqual(first['run_id'], replay['run_id'])

    def test_standalone_sql_repairs_old_fields_and_can_be_repeated(self):
        sql_file = Path(__file__).resolve().parents[1] / 'schema/upgrade_optional_execution_fields.sql'
        with GaussDB() as db:
            schema = db.execute_query_sql('SELECT current_schema()')[0][0]
            for table, columns in OPTIONAL_TEXT_COLUMNS.items():
                for column in columns:
                    db.execute_sql(f'ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL')
                    db.execute_sql(f'ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT \'\'')
            for _ in range(2):
                db.begin_transaction()
                try:
                    for sql in statements(sql_file):
                        if sql not in ('BEGIN', 'COMMIT'):
                            db.execute_sql(sql.replace('wfs.', schema + '.'))
                    self.assertEqual(upgrade_optional_execution_fields(db), [])
                    db.set_commit()
                except BaseException:
                    db.set_rollback()
                    raise
        # The already deployed code's empty-string placeholders work after DDL.
        with admission.store() as db:
            db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?)',
                       ('admin', 'old-code', 'task', 'pending', '', '', '2026-11-16'))
            self.assertEqual(db.execute('SELECT run_id,message FROM receipts').fetchone(), (None, None))

    def test_missing_start_receipt_stays_unknown_and_is_not_replayed(self):
        with patch('app.bootstrap.core.call_task_once', return_value=None) as start:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    admission.manual_request('admin', 'task', 'manual_request_123456', start)
            self.assertEqual(start.call_count, 1)
        with admission.store() as db:
            status, run_id, message = db.execute('SELECT status,run_id,message FROM receipts').fetchone()
        self.assertEqual(status, 'unknown')
        self.assertIsNone(run_id)
        self.assertTrue(message)

    def test_queue_pending_success_unknown_and_cancelled_allow_missing_optional_fields(self):
        for kind, effect, expected in [('manual', 'b' * 32, 'accepted'),
                                       ('trial', RuntimeError('start uncertain'), 'unknown'),
                                       ('manual', admission.PlanCancelled('plan changed'), 'cancelled')]:
            identifier = execution_requests.enqueue('task', kind, {}, 'admin')
            row = next(r for r in execution_requests.snapshot() if r['id'] == identifier)
            self.assertIsNone(row['run_id'])
            self.assertIsNone(row['message'])
            with patch('app.bootstrap.dispatch_control.available_slots', return_value=1), \
                 patch('app.bootstrap.dispatch_control.reason', return_value=''), \
                 patch('app.bootstrap.core.call_task_once', side_effect=effect if isinstance(effect, Exception) else None,
                       return_value=effect if isinstance(effect, str) else None) as start:
                execution_requests.dispatch()
                execution_requests.dispatch()
                self.assertEqual(start.call_count, 1)
            row = next(r for r in execution_requests.snapshot() if r['id'] == identifier)
            self.assertEqual(row['status'], expected)
            if expected == 'accepted':
                self.assertEqual(row['run_id'], 'b' * 32)
                self.assertIsNone(row['message'])
            else:
                self.assertIsNone(row['run_id'])
                self.assertTrue(row['message'])

    def test_expired_request_is_marked_before_capacity_checks(self):
        identifier = execution_requests.enqueue('task', 'manual', {}, 'admin')
        with admission.store() as db:
            db.execute('UPDATE work_requests SET expires_at=? WHERE id=?', ('2000-01-01', identifier))
        with patch('app.bootstrap.dispatch_control.available_slots', return_value=0), \
             patch('app.bootstrap.core.call_task_once') as start:
            execution_requests.dispatch()
            start.assert_not_called()
        self.assertEqual(execution_requests.snapshot()[0]['status'], 'expired')

    def test_cleaned_log_retains_journal_without_recovery_spool(self):
        directory = Path(self.temp.name) / 'executions'
        directory.mkdir()
        record = dict(run_id='c' * 32, pid='task', status='success', created_at='2026-11-16 12:00:00',
                      db_synced=True, history_saved=True, log_cleaned_at='2026-11-16 13:00:00')
        journal.write(directory, record, {'success'})
        self.assertFalse((directory / (record['run_id'] + '.json')).exists())
        with journal.connection(directory) as db:
            self.assertEqual(db.execute('SELECT run_id,log_path FROM journal').fetchone(), (record['run_id'], None))
