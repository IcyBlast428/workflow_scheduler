"""Database governance checks run without executing or importing task code."""
from pathlib import Path
import tempfile
import unittest
from app.bootstrap.business_db_policy import inspect_source, inspect_tree, enforce


class BusinessDatabasePolicyTests(unittest.TestCase):
    def test_newdb_query_helpers_and_driver_requirements_are_not_code_execution(self):
        code = '''from app.common.database import NewDB
from sqlalchemy import text
with NewDB("reports") as db:
    data = db.query("select ?", (1,))
# import pymysql is documentation
example = "import psycopg"
'''
        self.assertEqual(inspect_source(code), [])

    def test_direct_drivers_platform_and_engine_aliases_report_exact_source(self):
        for code in ('import pymysql as driver', 'from psycopg import connect',
                     'from app.common.database import GaussDB',
                     'from app.bootstrap import database',
                     'import sqlalchemy as sa\nsa.create_engine("unused")',
                     'from sqlalchemy import create_engine as engine',
                     'import importlib as il\nil.import_module("pyodbc")',
                     '__import__("mysql.connector")'):
            with self.subTest(code=code):
                report = inspect_source('\n' + code, 'helpers/connect.py')
                self.assertTrue(report)
                self.assertEqual(report[0]['path'], 'helpers/connect.py')
                self.assertGreaterEqual(report[0]['line'], 2)

    def test_nested_files_and_clear_migration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.py').write_text('print("no task execution")')
            (root / 'helper.py').write_text('import pyodbc')
            result = inspect_tree(root)
            self.assertFalse(result['passed'])
            with self.assertRaisesRegex(ValueError, 'helper.py:1.*NewDB'):
                enforce(root)

    def test_check_does_not_claim_dynamic_code_is_a_sandbox(self):
        result = inspect_source('module_name = input()\n__import__(module_name)')
        self.assertEqual(result, [])
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(inspect_tree(root)['scope'], 'static_source_check')
        with self.assertRaises(ValueError):
            inspect_tree('/nonexistent-task-policy-test')
