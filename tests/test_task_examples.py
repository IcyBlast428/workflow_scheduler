"""Run the exact Python sources displayed in the task publishing guide."""
import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_local_integration
from app.bootstrap import connection_settings as settings
from app.common.database import NewDB

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples' / 'tasks'


class TaskExampleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            'WFS_DATA_DIR': str(self.root), 'WFS_TASK_DATA_DIR': str(self.root / 'output'),
            'PYTHONPATH': str(ROOT), 'PYTHONIOENCODING': 'utf-8',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(NewDB.dispose_pool)
        # Keep the guide's ID, but route it to a disposable real SQLite file.
        settings.save(settings.validate({'id': 'mysql_orders', 'dialect': 'sqlite', 'database': 'guide.sqlite3'}))

    def run_example(self, name, *, success=True):
        environment = dict(os.environ, WFS_TASK_DATABASE_KEY=settings.task_database_key())
        for key in ('WFS_SECRET_KEY', 'WFS_CONNECTIONS_KEY'):
            environment.pop(key, None)
        result = subprocess.run([sys.executable, str(EXAMPLES / name / 'main.py')],
                                cwd=self.root, env=environment, capture_output=True, text=True,
                                encoding='utf-8', timeout=20)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_hello_and_parallel_safe_report_output(self):
        self.assertIn('5050', self.run_example('hello').stdout)
        self.run_example('file_output')
        self.run_example('file_output')
        reports = list((self.root / 'output').glob('report-*.csv'))
        self.assertEqual(len(reports), 2)
        with reports[0].open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(list(csv.reader(stream)), [['名称', '数量'], ['示例', '100']])

    def test_parameterized_query_and_repeatable_transaction(self):
        with NewDB('mysql_orders') as db:
            db.execute('CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT)')
            db.execute('CREATE TABLE task_demo_items(id INTEGER PRIMARY KEY, status TEXT)')
            db.executemany('INSERT INTO orders VALUES(?,?)', [(1, 'pending'), (2, 'done')])
            db.executemany('INSERT INTO task_demo_items VALUES(?,?)', [(1, 'pending'), (2, 'pending')])
        self.assertIn('1 条', self.run_example('database_query').stdout)
        self.run_example('database_transaction')
        self.run_example('database_transaction')
        with NewDB('mysql_orders') as db:
            self.assertEqual(db.query('SELECT id,status FROM task_demo_items ORDER BY id'), [(1, 'done'), (2, 'done')])

    def test_example_failure_rolls_back_and_exits_unsuccessfully(self):
        with NewDB('mysql_orders') as db:
            db.execute("CREATE TABLE task_demo_items(id INTEGER PRIMARY KEY, status TEXT CHECK(id != 2 OR status = 'pending'))")
            db.executemany('INSERT INTO task_demo_items VALUES(?,?)', [(1, 'pending'), (2, 'pending')])
        self.run_example('database_transaction', success=False)
        with NewDB('mysql_orders') as db:
            self.assertEqual(db.query('SELECT status FROM task_demo_items'), [('pending',), ('pending',)])

    def test_business_import_does_not_load_platform_driver(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; from app.common.database import NewDB; "
            "assert 'app.bootstrap.database' not in sys.modules; "
            "assert 'app.common.nacos' not in sys.modules; "
            "from app.common.database import GaussDB; assert GaussDB is not None"],
            env=os.environ.copy(), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
