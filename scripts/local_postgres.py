"""Isolated Docker PostgreSQL acceptance for native Windows development.

Never reads production database credentials or writes .env.local. Credentials
are kept in ignored data/gauss-dev, not in Docker command arguments.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE_ROOT = ROOT / "data/gauss-dev"
CONTAINER = "wfs-gauss-dev"
IMAGE = "postgres:18.1"


def configuration():
    target = STATE_ROOT / "environment.json"
    if target.exists():
        return json.loads(target.read_text(encoding="utf-8"))
    from scripts.service_config import read_environment

    source = ROOT / ".env.local"
    values, _ = read_environment(source) if source.is_file() else ({}, set())
    values.update(
        {
            key: os.environ[key]
            for key in (
                "WFS_SECRET_KEY",
                "WFS_ADMIN_USERNAME",
                "WFS_ADMIN_PASSWORD_HASH",
            )
            if os.environ.get(key)
        }
    )
    values.setdefault("WFS_SECRET_KEY", secrets.token_urlsafe(48))
    values.setdefault("WFS_ADMIN_USERNAME", "admin")
    if not values.get("WFS_ADMIN_PASSWORD_HASH"):
        import getpass
        from werkzeug.security import generate_password_hash

        admin_password = getpass.getpass(
            "Set local administrator password (at least 12 characters): "
        )
        if len(admin_password) < 12 or admin_password != getpass.getpass(
            "Confirm password: "
        ):
            raise ValueError("Passwords must match and contain at least 12 characters")
        values["WFS_ADMIN_PASSWORD_HASH"] = generate_password_hash(admin_password)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(32)
    settings = {
        key: values[key]
        for key in ("WFS_SECRET_KEY", "WFS_ADMIN_USERNAME", "WFS_ADMIN_PASSWORD_HASH")
    }
    settings.update(
        WFS_CONNECTIONS_KEY=secrets.token_urlsafe(48),
        WFS_ENV="development",
        WFS_POSTGRES_TEST="true",
        WFS_DB_DRIVER="psycopg",
        WFS_STATE_BACKEND="gauss",
        WFS_DB_ID="wfstest_wfs",
        WFS_DB_PASSWORD=password,
        WFS_DB_CONFIG_FILE=str(STATE_ROOT / "database.ini"),
        WFS_COOKIE_SECURE="false",
        WFS_SESSION_COOKIE_NAME="wfs_postgres_native_session",
        WFS_PORT="18008",
        WFS_HOST="127.0.0.1",
        WFS_DATA_DIR=str(STATE_ROOT / "state"),
        WFS_LOG_DIR=str(STATE_ROOT / "logs"),
        PYTHONIOENCODING="utf-8",
    )
    (STATE_ROOT / "database.ini").write_text(
        "[gauss_wfstest_wfs]\nuser=wfstest\nhost=127.0.0.1\nport=15433\npassword=\n",
        encoding="utf-8",
    )
    (STATE_ROOT / "container.env").write_text(
        "POSTGRES_DB=wfstest\nPOSTGRES_USER=wfstest\nPOSTGRES_PASSWORD="
        + password
        + "\n",
        encoding="utf-8",
    )
    target.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    if os.name != "nt":
        for path in (target, STATE_ROOT / "database.ini", STATE_ROOT / "container.env"):
            path.chmod(0o600)
    return settings


def environment(scheduler=False):
    values = configuration()
    os.environ.update(values)
    for key in (
        "WFS_LOCAL_DB_PATH",
        "WFS_TASK_RELEASE_DIR",
        "WFS_IGNORE_MANAGED_DATABASE",
    ):
        os.environ.pop(key, None)
    os.environ.update(
        WFS_ENABLE_SCHEDULER="true" if scheduler else "false",
        WFS_SCHEDULER_CONTROL_URL="",
    )
    os.chdir(ROOT)
    return values


def prepare():
    configuration()
    found = subprocess.run(
        ["docker", "inspect", CONTAINER], capture_output=True, text=True
    )
    if found.returncode == 0:
        info = json.loads(found.stdout)[0]
        if (info["Config"].get("Labels") or {}).get(
            "wfs.project"
        ) != "workflow_scheduler" or info["Config"]["Image"] != IMAGE:
            raise RuntimeError("Container belongs to another installation")
        subprocess.run(
            ["docker", "start", CONTAINER], check=True, stdout=subprocess.DEVNULL
        )
    else:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                CONTAINER,
                "--label",
                "wfs.project=workflow_scheduler",
                "--restart",
                "unless-stopped",
                "--publish",
                "127.0.0.1:15433:5432",
                "--env-file",
                str(STATE_ROOT / "container.env"),
                "--mount",
                "type=volume,source=wfs-gauss-dev-data,target=/var/lib/postgresql",
                "--memory",
                "1g",
                IMAGE,
                "-c",
                "timezone=Asia/Shanghai",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    for _ in range(40):
        ready = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER,
                "pg_isready",
                "-U",
                "wfstest",
                "-d",
                "wfstest",
            ],
            capture_output=True,
        )
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL did not become ready")
    environment()
    from app.bootstrap.database import GaussDB
    from scripts.init_database import initialize

    initialize()
    with GaussDB() as db:
        count = db.execute_query_sql(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='wfs'"
        )[0][0]
    print("PostgreSQL prepared on 127.0.0.1:15433; tables:", count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "serve"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        environment(scheduler=True)
        import runpy

        runpy.run_path(str(ROOT / "backend_dev_runner.py"), run_name="__main__")


if __name__ == "__main__":
    main()
