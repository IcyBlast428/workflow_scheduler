"""Initialize an empty platform schema; existing installations are only validated."""

import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sql_schema import statements

SCHEMA_FILE = ROOT / "schema/gauss.sql"
VERSION = 1


def schema_name():
    from app.bootstrap.database import DEFAULT_DB_ID, _split_db_id

    return _split_db_id(os.environ.get("WFS_DB_ID", DEFAULT_DB_ID))[1]


def table_names():
    return re.findall(r"CREATE TABLE (wfs_\w+)", SCHEMA_FILE.read_text())


def validate(db):
    for table in table_names():
        db.execute_query_sql("SELECT 1 FROM " + table + " LIMIT 0")
    if [
        tuple(row)
        for row in db.execute_query_sql("SELECT version FROM wfs_schema_version")
    ] != [(VERSION,)]:
        raise RuntimeError("Platform schema version does not match this release")


def initialize():
    from app.bootstrap.database import GaussDB

    schema = schema_name()
    with GaussDB() as db:
        db.begin_transaction()
        try:
            db.execute_query_sql("SELECT pg_advisory_xact_lock(184762901)")
            tables = db.execute_query_sql(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=?",
                params=(schema,),
            )
            if tables:
                if "wfs_schema_version" not in {row[0] for row in tables}:
                    raise RuntimeError(
                        "Target schema is not empty. Use a fresh database/schema; data import is not supported."
                    )
                validate(db)
            else:
                exists = db.execute_query_sql(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name=?",
                    params=(schema,),
                )
                for sql in statements(SCHEMA_FILE):
                    if sql == "CREATE SCHEMA wfs":
                        if not exists:
                            db.execute_sql("CREATE SCHEMA " + schema)
                    elif sql == "SET search_path TO wfs":
                        db.execute_sql("SET search_path TO " + schema)
                    else:
                        db.execute_sql(sql)
                validate(db)
            db.set_commit()
        except BaseException:
            db.set_rollback()
            raise
    print(
        "Platform schema ready:", len(table_names()), "tables; fresh baseline", VERSION
    )


if __name__ == "__main__":
    initialize()
