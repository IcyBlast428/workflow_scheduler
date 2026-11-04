"""Fresh-only schema guards and the production GaussDB SQL path on a real test server."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import test_local_integration
from app.bootstrap import auxiliary_store, operations, run_summary
from app.bootstrap.database import GaussDB
from scripts.init_database import initialize, table_names


class FreshGaussTests(unittest.TestCase):
    def test_state_schema_matches_explicit_columns_and_primary_keys(self):
        schema = os.environ["WFS_DB_ID"].split("_", 1)[1]
        with GaussDB() as db:
            for namespace, tables in auxiliary_store.SCHEMAS.items():
                for table, (columns, keys) in tables.items():
                    actual = db.execute_query_sql(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
                        params=(schema, auxiliary_store.physical(namespace, table)),
                    )
                    self.assertEqual([r[0] for r in actual], columns.split())
            self.assertEqual(len(table_names()), 32)

    def test_nonempty_unversioned_schema_is_rejected_without_changes(self):
        with GaussDB() as db:
            db.execute_sql(
                "ALTER TABLE wfs_schema_version RENAME TO saved_schema_version"
            )
        try:
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                initialize()
            with GaussDB() as db:
                self.assertEqual(
                    db.execute_query_sql("SELECT version FROM saved_schema_version")[0][
                        0
                    ],
                    1,
                )
        finally:
            with GaussDB() as db:
                db.execute_sql(
                    "ALTER TABLE saved_schema_version RENAME TO wfs_schema_version"
                )

    def test_unsupported_backends_and_production_test_override_fail(self):
        for values in (
            {"WFS_STATE_BACKEND": "file"},
            {"WFS_LOCAL_DB_PATH": "unused.db"},
            {"WFS_ENV": "production", "WFS_POSTGRES_TEST": "true"},
        ):
            with (
                self.subTest(values=values),
                patch.dict(os.environ, values),
                self.assertRaises(RuntimeError),
            ):
                auxiliary_store.validate_backend()

    def test_no_file_database_adapter_or_old_business_config_fallback(self):
        from app.common.db.config import load_database_config

        with patch.dict(os.environ, {"WFS_TASK_CONNECTIONS_JSON": "{}"}):
            for key in ("unconfigured", "platform"):
                with self.assertRaises(PermissionError):
                    load_database_config(key)
        import ast

        root = Path(__file__).resolve().parents[1]
        for directory in ("app", "scripts", "examples"):
            for path in (root / directory).rglob("*.py"):
                if "dist" in path.parts:
                    continue
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                    if isinstance(node, ast.Import):
                        self.assertFalse(
                            any(a.name == "sqlite3" for a in node.names), str(path)
                        )
                    if isinstance(node, ast.ImportFrom):
                        self.assertNotEqual(node.module, "sqlite3", str(path))

    def test_gauss_completion_transactions_remain_exactly_once_under_concurrency(self):
        # Exercise the production SQL branch, not the optional PostgreSQL upsert optimization.
        with patch.object(GaussDB, "dialect", property(lambda self: "GaussDB/DWS")):

            def finish(index):
                identifier = operations.create_run(
                    "gauss-concurrency-" + str(index % 2)
                )
                record = operations.update_run(
                    identifier, status="success", state=0, end_time=operations.now()
                )
                operations.save_history(record)
                operations.save_history(operations.read_run(identifier))
                return identifier

            with ThreadPoolExecutor(max_workers=4) as pool:
                ids = list(pool.map(finish, range(12)))
            with GaussDB() as db:
                self.assertEqual(
                    db.execute_query_sql(
                        "SELECT SUM(executions) FROM wfs_run_summary WHERE pid LIKE 'gauss-concurrency-%'"
                    )[0][0],
                    12,
                )
                self.assertEqual(
                    db.execute_query_sql(
                        "SELECT COUNT(*) FROM wfs_run_history WHERE pid LIKE 'gauss-concurrency-%'"
                    )[0][0],
                    12,
                )
            self.assertEqual(run_summary.backfill(), 0)
