"""Run regression tests against fresh real PostgreSQL schemas, with per-test reset."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import test_local_integration as shared
from app.bootstrap.database import GaussDB
from scripts.init_database import table_names
from app.bootstrap import task_loader

BASE_TABLES = ("wfs_package_tasks", "wfs_task_releases")
with GaussDB() as db:
    baseline = {
        table: db.execute_query_sql("SELECT * FROM " + table) for table in BASE_TABLES
    }


class ResetResult(unittest.TextTestResult):
    def startTest(self, test):
        from app.common.database import NewDB

        NewDB.dispose_pool()
        with GaussDB() as db:
            db.execute_sql(
                "TRUNCATE "
                + ",".join(t for t in table_names() if t != "wfs_schema_version")
            )
            if not any(c.__name__ == "PackageTests" for c in type(test).__mro__):
                for table, rows in baseline.items():
                    for row in rows:
                        db.execute_sql(
                            "INSERT INTO "
                            + table
                            + " VALUES("
                            + ",".join("?" for _ in row)
                            + ")",
                            params=tuple(row),
                        )
        task_loader.invalidate_task_cache()
        super().startTest(test)


if __name__ == "__main__":
    names = sys.argv[1:]
    suite = (
        unittest.defaultTestLoader.loadTestsFromNames(names)
        if names
        else unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    )
    result = unittest.TextTestRunner(verbosity=2, resultclass=ResetResult).run(suite)
    raise SystemExit(not result.wasSuccessful())
