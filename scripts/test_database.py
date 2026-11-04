"""Disposable real PostgreSQL test schemas; never reads production settings."""

import atexit
import json
import os
from pathlib import Path
import secrets
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def configure(root=None):
    import psycopg

    if os.environ.get("WFS_CI_POSTGRES") == "true":
        password = os.environ["PGPASSWORD"]
        port = int(os.environ.get("PGPORT", "5432"))
    else:
        config = json.loads((ROOT / "data/gauss-dev/environment.json").read_text())
        password = config["WFS_DB_PASSWORD"]
        port = 15433
    root = Path(root or tempfile.mkdtemp(prefix="wfs-test-"))
    root.mkdir(parents=True, exist_ok=True)
    schema = "test_" + uuid.uuid4().hex[:16]
    ini = root / "database.ini"
    ini.write_text(
        "[gauss_wfstest_"
        + schema
        + "]\nuser=wfstest\nhost=127.0.0.1\nport="
        + str(port)
        + "\npassword=\n"
    )
    os.environ.update(
        WFS_ENV="development",
        WFS_ENABLE_SCHEDULER="false",
        WFS_STATE_BACKEND="gauss",
        WFS_POSTGRES_TEST="true",
        WFS_DB_DRIVER="psycopg",
        WFS_DB_ID="wfstest_" + schema,
        WFS_DB_CONFIG_FILE=str(ini),
        WFS_DB_PASSWORD=password,
        WFS_DATA_DIR=str(root / "data"),
        WFS_LOG_DIR=str(root / "logs"),
        WFS_SECRET_KEY=secrets.token_urlsafe(32),
        WFS_COOKIE_SECURE="false",
        WFS_SCHEDULER_CONTROL_URL="",
    )
    os.environ.pop("WFS_LOCAL_DB_PATH", None)
    from scripts.init_database import initialize

    initialize()

    def cleanup():
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname="wfstest",
            user="wfstest",
            password=password,
            autocommit=True,
        ) as connection:
            connection.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE")

    atexit.register(cleanup)
    return root


def business_profile(identifier="pg_reports"):
    from configobj import ConfigObj

    cfg = ConfigObj(os.environ["WFS_DB_CONFIG_FILE"])
    values = next(iter(cfg.values()))
    return dict(
        id=identifier,
        dialect="postgresql",
        host="127.0.0.1",
        port=int(values["port"]),
        database="wfstest",
        user="wfstest",
        password=os.environ["WFS_DB_PASSWORD"],
        tls="disabled",
    )


def publish_fixture(spec, actor="test-fixture"):
    """Explicit fixture publication, with no source discovery or old data import."""
    import time
    from app.bootstrap import task_packages as packages
    from app.bootstrap.timebase import business_now

    record = dict(
        pid=spec["pid"],
        group_name=spec["group_name"],
        folder_name=spec["folder_name"],
        task_name=spec.get("task_name") or spec["folder_name"],
        active_version=None,
        deleted_at=None,
        created_at=str(business_now()),
        created_by=actor,
        revision=0,
    )
    release = packages._create(
        record,
        source=spec["task_dir"],
        entry=spec["main_file"],
        actor=actor,
        note="New disposable fixture",
    )
    record = packages._write_task(record, expected=0)
    release["base_revision"] = record["revision"]
    packages._write_release(release)
    packages.prepare(release["pid"], release["version"], release["main_file"])
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        prepared = packages.release(release["pid"], release["version"])
        if prepared["status"] != "preparing":
            if prepared["status"] != "ready":
                raise RuntimeError(prepared.get("message"))
            return packages.publish(
                release["pid"],
                release["version"],
                packages.task(release["pid"])["revision"],
                actor,
            )
        time.sleep(0.05)
    raise TimeoutError("Fixture preparation timed out")
