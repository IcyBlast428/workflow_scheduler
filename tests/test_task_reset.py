"""Targeted reset uses isolated PostgreSQL and temporary task storage only."""
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import test_gitlab_tasks as gitlab_tests
import test_task_packages as package_tests
from app.bootstrap import gitlab_tasks, gitlab_updates, task_packages
from app.bootstrap.database import GaussDB
from scripts.reset_task import plan, apply, checked_path, PID_TABLES


class TaskResetTests(unittest.TestCase):
    setUp = package_tests.PackageTests.setUp
    tearDown = gitlab_tests.GitLabTaskTests.tearDown
    connect = gitlab_tests.GitLabTaskTests.connect
    scan = gitlab_tests.GitLabTaskTests.scan
    path = 'app/jobs/acceptance/git_new'
    old = 'original-task'

    def fixture(self):
        self.connect()
        self.record = dict(pid=self.old, group_name='acceptance', folder_name='git_new', task_name='Original',
                           active_version=None, deleted_at='2026-11-16', git_source={})
        task_packages._write_task(self.record)
        task_packages._write_task(dict(pid='unrelated', group_name='other', folder_name='other', task_name='Other', active_version=None))
        config = gitlab_updates.configuration()
        gitlab_updates.save_configuration({**config, 'tasks': [{'pid': self.old, 'path': self.path, 'commit': ''}]})
        run = 'a' * 32
        with GaussDB() as db:
            # Populate each task-owned table, including orphan records left by partial cleanup.
            for table in PID_TABLES:
                if table == 'wfs_package_tasks':
                    continue
                columns = db.execute_query_sql('SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position', params=(table,))
                data = {}
                for name, kind in columns:
                    data[name] = '2026-11-16 12:00:00' if kind.startswith('timestamp') else 1 if kind in ('integer', 'bigint', 'smallint', 'double precision') else ''
                data.update(pid=self.old)
                for name in ('id', 'run_id'):
                    if name in data:
                        data[name] = run
                for name, value in [('group_name', 'acceptance'), ('folder_name', 'git_new'), ('task_name', 'Original'), ('status', 'failed'), ('payload', '{}'), ('log_path', 'logs/2026-11-16/aa/' + run + '.log')]:
                    if name in data:
                        data[name] = value
                db.execute_sql('INSERT INTO ' + table + '(' + ','.join(data) + ') VALUES(' + ','.join('?' for _ in data) + ')', params=tuple(data.values()))
            for key, payload in [('task:' + self.old, {}), ('tags:' + self.old, {}), ('notification:' + run, {}), ('issue:run-' + run, {}), ('task:unrelated', {'keep': True}), ('access:maintainer', {'revision': 1, 'tasks': [self.old, 'unrelated'], 'groups': [], 'capabilities': ['run']})]:
                db.execute_sql('INSERT INTO wfs_state_admission_settings(key,payload) VALUES(?,?)', params=(key, json.dumps(payload)))
        self.code = self.root / 'packages' / self.old / 'releases' / 'v1' / 'code' / 'main.py'
        self.output = self.root / 'task-data' / self.old / 'result.csv'
        self.log = self.root / 'executions/logs/2026-11-16/aa' / (run + '.log')
        for file in (self.code, self.output, self.log):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('old data')
        self.other = self.root / 'task-data/unrelated/result.csv'
        self.other.parent.mkdir(parents=True)
        self.other.write_text('keep')

    def preview(self, db):
        return plan(db, self.old, self.path, self.root, self.root / 'packages')

    def test_full_reset_becomes_new_and_preserves_other_tasks_and_credentials(self):
        self.fixture()
        before = gitlab_updates.configuration()
        with GaussDB() as db:
            value = self.preview(db)
            self.assertTrue(self.code.exists())
            self.assertEqual(set(PID_TABLES), {table for table in PID_TABLES if value['tables'][table]})
            backup = apply(db, value, self.root / 'reset-backup')
            for table in PID_TABLES:
                self.assertFalse(db.execute_query_sql('SELECT pid FROM ' + table + ' WHERE pid=?', params=(self.old,)), table)
            access = db.execute_query_sql("SELECT payload FROM wfs_state_admission_settings WHERE key='access:maintainer'")[0][0]
            self.assertEqual(json.loads(access)['tasks'], ['unrelated'])
            self.assertEqual(db.execute_query_sql("SELECT payload FROM wfs_state_admission_settings WHERE key='task:unrelated'")[0][0], '{"keep": true}')
        for file in (self.code, self.output, self.log):
            self.assertFalse(file.exists())
        self.assertEqual(self.other.read_text(), 'keep')
        self.assertTrue((backup / 'COMPLETED').exists())
        self.assertNotIn(self.old, task_packages.registry())
        self.assertIn('unrelated', task_packages.registry())
        after = gitlab_updates.configuration()
        for key in ('token', 'url', 'project', 'task_roots', 'target'):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(after['tasks'], [])
        self.scan()
        candidate = next(i for i in gitlab_tasks.changes()['items'] if i['path'] == self.path)
        self.assertEqual(candidate['kind'], 'new')
        self.assertFalse(candidate['blocked'])
        # A retry after completion is safe and never touches another task.
        with GaussDB() as db:
            again = self.preview(db)
            self.assertFalse(any(again['tables'][table] for table in PID_TABLES))
        staged = gitlab_tasks.stage(candidate['id'], 'admin')
        self.assertEqual(staged['pid'], candidate['pid'])
        self.assertNotEqual(staged['pid'], self.old)
        self.assertIsNone(task_packages.task(staged['pid'])['active_version'])

    def test_every_pid_table_in_schema_is_covered(self):
        schema = (Path(__file__).resolve().parents[1] / 'schema/gauss.sql').read_text()
        pid_tables = {name for name, columns in re.findall(r'CREATE TABLE (\w+)\s*\((.*?)\);', schema, re.S) if re.search(r'\bpid\s+varchar', columns, re.I)}
        self.assertEqual(pid_tables, set(PID_TABLES))

    def test_move_failure_rolls_back_database_and_restores_files(self):
        self.fixture()
        original = Path.rename
        calls = []
        def fail_second(source, destination):
            calls.append(str(source))
            if len(calls) == 2:
                raise OSError('simulated disk failure')
            return original(source, destination)
        with GaussDB() as db:
            value = self.preview(db)
            with patch.object(Path, 'rename', fail_second), self.assertRaisesRegex(OSError, 'disk failure'):
                apply(db, value, self.root / 'reset-backup')
            self.assertTrue(db.execute_query_sql('SELECT pid FROM wfs_package_tasks WHERE pid=?', params=(self.old,)))
        self.assertTrue(self.code.exists())
        self.assertTrue(self.output.exists())
        self.assertTrue(self.log.exists())
        self.assertEqual(gitlab_updates.configuration()['tasks'][0]['pid'], self.old)

    def test_mismatched_directory_and_unsafe_path_are_rejected(self):
        self.fixture()
        with GaussDB() as db, self.assertRaisesRegex(ValueError, 'different directory'):
            plan(db, self.old, 'app/jobs/other/wrong', self.root, self.root / 'packages')
        with self.assertRaises(ValueError):
            checked_path(self.root, '../outside')
        with self.assertRaises(ValueError):
            checked_path(self.root, self.root)
