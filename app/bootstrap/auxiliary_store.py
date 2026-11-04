"""GaussDB state storage for the fresh-install production profile.

Expose the small DB-API subset used by existing state modules. Logical table
names are isolated by namespace. Replace operations use portable DELETE/INSERT
inside a GaussDB transaction protected by a namespace lock.
"""

from contextlib import contextmanager
import os
import re

# column order and primary keys are explicit; no untrusted identifiers are used.
SCHEMAS = {
    "admission": {
        "settings": ("key payload", "key"),
        "receipts": ("actor key pid status run_id message created_at", "actor key"),
        "work_requests": (
            "id pid kind status payload created_at due_at run_id message expires_at",
            "id",
        ),
        "ddl_history": ("pid revision payload", "pid revision"),
        "hook_events": ("id at", "id"),
    },
    "connections": {"profiles": ("id revision payload", "id")},
    "publishing": {"settings": ("name revision payload", "name")},
    "gitlab": {
        "configuration": ("id revision payload", "id"),
        "snapshot": ("id payload", "id"),
        "scan_lease": ("id token expires", "id"),
        "acknowledgements": ("username fingerprint", "username"),
    },
    "journal": {
        "journal": (
            "run_id pid status created_at pending retry_at payload log_path",
            "run_id",
        )
    },
}
BINARY = {
    ("connections", "profiles"),
    ("publishing", "settings"),
    ("gitlab", "configuration"),
}


def validate_backend():
    if os.environ.get("WFS_STATE_BACKEND", "gauss") != "gauss":
        raise RuntimeError(
            "Platform state requires GaussDB; configure WFS_STATE_BACKEND=gauss"
        )
    if os.environ.get("WFS_LOCAL_DB_PATH"):
        raise RuntimeError(
            "File database configuration is no longer supported; use the GaussDB fresh deployment"
        )

    if (
        os.environ.get("WFS_ENV") == "production"
        and os.environ.get("WFS_POSTGRES_TEST") == "true"
    ):
        raise RuntimeError(
            "Production requires the real GaussDB/DWS driver; local test overrides are forbidden"
        )


def physical(namespace, table):
    if table not in SCHEMAS[namespace]:
        raise ValueError("Unknown state table")
    return "wfs_state_" + namespace + "_" + table


class Result:
    def __init__(self, rows=(), rowcount=-1):
        self.rows = list(rows)
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def __iter__(self):
        return iter(self.rows)


class Store:
    def __init__(self, namespace, database):
        self.namespace, self.database, self.locked = namespace, database, False

    def _lock(self):
        if self.locked:
            return
        tables = ",".join(
            physical(self.namespace, table) for table in SCHEMAS[self.namespace]
        )
        self.database.cursor.execute(
            "LOCK TABLE " + tables + " IN SHARE ROW EXCLUSIVE MODE"
        )
        self.locked = True

    def _mapped(self, sql):
        # Do not replace identifiers inside SQL literals.
        parts = re.split(r"('(?:[^']|'')*')", sql)
        pattern = r"\b(" + "|".join(SCHEMAS[self.namespace]) + r")\b"
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(
                pattern, lambda match: physical(self.namespace, match[0]), parts[index]
            )
        return "".join(parts)

    def _run(self, sql, params=()):
        cursor = self.database.conn.cursor()
        try:
            cursor.execute(
                self._mapped(sql),
                tuple(
                    value.decode("utf-8") if isinstance(value, bytes) else value
                    for value in params
                ),
            )
            rows = (
                [tuple(row) for row in cursor.fetchall()] if cursor.description else []
            )
            columns = (
                [column[0].lower() for column in cursor.description]
                if cursor.description
                else []
            )
            table = re.search(r"\bFROM\s+(\w+)", sql, re.I)
            if table and (self.namespace, table[1]) in BINARY and "payload" in columns:
                position = columns.index("payload")
                rows = [
                    tuple(
                        value.encode("utf-8")
                        if i == position and isinstance(value, str)
                        else value
                        for i, value in enumerate(row)
                    )
                    for row in rows
                ]
            return Result(rows, cursor.rowcount)
        finally:
            cursor.close()

    def execute(self, sql, params=()):
        sql = sql.strip()
        if sql.upper() == "BEGIN":
            self._lock()
            return Result()
        if not sql.upper().startswith("SELECT"):
            self._lock()
        return self._run(sql, params)

    def executemany(self, sql, rows):
        self._lock()
        cursor = self.database.conn.cursor()
        try:
            cursor.executemany(self._mapped(sql), rows)
            return Result(rowcount=cursor.rowcount)
        finally:
            cursor.close()

    def replace(self, table, columns, values):
        if table not in SCHEMAS[self.namespace]:
            raise ValueError("Unknown state table")
        known, keys = SCHEMAS[self.namespace][table]
        if not set(columns) <= set(known.split()):
            raise ValueError("Unknown state column")
        self._lock()
        row = dict(zip(columns, values))
        self._run(
            "DELETE FROM "
            + table
            + " WHERE "
            + " AND ".join(k + "=?" for k in keys.split()),
            [row[k] for k in keys.split()],
        )
        return self._run(
            "INSERT INTO "
            + table
            + "("
            + ",".join(columns)
            + ") VALUES("
            + ",".join("?" for _ in columns)
            + ")",
            values,
        )


@contextmanager
def gauss_store(namespace):
    from app.bootstrap.database import GaussDB

    with GaussDB() as database:
        local_postgres = (
            os.environ.get("WFS_POSTGRES_TEST") == "true"
            and database.dialect == "PostgreSQL"
            and os.environ.get("WFS_DB_ID", "").startswith("wfstest_")
        )
        if database.dialect != "GaussDB/DWS" and not local_postgres:
            raise RuntimeError("GaussDB state storage requires GaussDB/DWS")
        database.begin_transaction()
        try:
            yield Store(namespace, database)
            database.conn.commit()
        except BaseException:
            database.conn.rollback()
            raise
