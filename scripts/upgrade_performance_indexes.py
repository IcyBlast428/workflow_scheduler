"""Add missing global timeline indexes to an existing schema; preview by default."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
INDEXES = {
    'idx_wfs_run_start_id': ('wfs_run_history', 'start_time DESC,id DESC'),
    'idx_wfs_executions_created_id': ('wfs_executions', 'created_at,run_id'),
}


def plan(db):
    rows = db.execute_query_sql('SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()')
    existing = {row[0] for row in rows}
    return [(name, f'CREATE INDEX {name} ON {table}({columns})')
            for name, (table, columns) in INDEXES.items() if name not in existing]


def upgrade(db, apply=False):
    pending = plan(db)
    if apply:
        # Serialize repeat invocations using the supported lock for each backend.
        db.begin_transaction()
        try:
            if db.dialect == 'PostgreSQL':
                db.execute_query_sql('SELECT pg_advisory_xact_lock(184762902)')
            else:
                db.execute_sql('LOCK TABLE wfs_schema_version IN EXCLUSIVE MODE')
            pending = plan(db)
            for _, sql in pending:
                db.execute_sql(sql)
            db.set_commit()
        except BaseException:
            db.set_rollback()
            raise
    return [name for name, _ in pending]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create missing indexes; schedule a maintenance window for large tables.')
    args = parser.parse_args()
    from app.bootstrap.database import GaussDB
    with GaussDB() as db:
        names = upgrade(db, args.apply)
    print(('Created indexes: ' if args.apply else 'Preview, missing indexes: ') + (', '.join(names) or 'none'))
    if names and not args.apply:
        print('Existing rows are retained. Creating indexes can block writes; use --apply during a maintenance window.')


if __name__ == '__main__':
    main()
