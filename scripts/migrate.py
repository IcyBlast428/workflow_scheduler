"""Apply numbered WFS schema migrations with a database transaction per file."""

from pathlib import Path
import hashlib
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bootstrap.database import GaussDB  # noqa: E402


MIGRATIONS = ROOT / 'migrations'
REQUIRED_TABLES = ('wfs_task_config', 'wfs_job_stats', 'wfs_run_history', 'wfs_schedule_history')


def statements(path):
    content = path.read_text(encoding='utf-8')
    result, current, quote, index = [], [], '', 0
    while index < len(content):
        if quote:
            if content.startswith(quote, index):
                current.append(quote)
                index += len(quote)
                if quote in ("'", '"') and content.startswith(quote, index):
                    current.append(quote)
                    index += len(quote)
                else:
                    quote = ''
            else:
                current.append(content[index]); index += 1
            continue
        if content.startswith('--', index):
            end = content.find('\n', index)
            index = len(content) if end < 0 else end
            continue
        if content.startswith('/*', index):
            end = content.find('*/', index + 2)
            if end < 0:
                raise ValueError('unclosed SQL comment')
            current.append(' '); index = end + 2
            continue
        char = content[index]
        dollar = re.match(r'\$[A-Za-z0-9_]*\$', content[index:]) if char == '$' else None
        if char in ("'", '"') or dollar:
            quote = dollar.group() if dollar else char
            current.append(quote); index += len(quote)
        elif char == ';':
            if ''.join(current).strip():
                result.append(''.join(current).strip())
            current = []; index += 1
        else:
            current.append(char); index += 1
    if quote:
        raise ValueError('unclosed SQL literal')
    if ''.join(current).strip():
        result.append(''.join(current).strip())
    return result


def main():
    with GaussDB() as db:
        for table in REQUIRED_TABLES:
            db.execute_query_sql(f'SELECT 1 FROM {table} LIMIT 0')
        db.execute_sql('CREATE TABLE IF NOT EXISTS wfs_schema_migrations (name varchar(200) PRIMARY KEY, applied_at timestamp NOT NULL, checksum varchar(64))')
        db.begin_transaction()
        try:
            if not db._local_sqlite:
                db.execute_sql('LOCK TABLE wfs_schema_migrations IN EXCLUSIVE MODE')
            db.execute_query_sql('SELECT * FROM wfs_schema_migrations LIMIT 0')
            if 'checksum' not in [column[0] for column in db.cursor.description]:
                db.execute_sql('ALTER TABLE wfs_schema_migrations ADD COLUMN checksum varchar(64)')
            db.set_commit()
        except Exception:
            db.set_rollback(); raise
        for path in sorted(MIGRATIONS.glob('[0-9][0-9][0-9]_*.sql')):
            checksum = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            db.begin_transaction()
            try:
                if not db._local_sqlite:
                    db.execute_sql('LOCK TABLE wfs_schema_migrations IN EXCLUSIVE MODE')
                previous = db.execute_query_sql('SELECT checksum FROM wfs_schema_migrations WHERE name=?', params=(path.name,))
                if previous:
                    if previous[0][0] and previous[0][0] != checksum:
                        raise RuntimeError(f'Applied migration changed: {path.name}; add a new numbered migration')
                    db.execute_sql('UPDATE wfs_schema_migrations SET checksum=? WHERE name=?', params=(checksum,path.name))
                    db.set_commit()
                    continue
                for statement in statements(path):
                    if db._local_sqlite and statement.startswith('ALTER TABLE wfs_run_history ADD COLUMN summary_version'):
                        if 'summary_version' in [row[1] for row in db.conn.execute('PRAGMA table_info(wfs_run_history)')]:
                            continue
                    db.execute_sql(statement)
                db.execute_sql('INSERT INTO wfs_schema_migrations (name, applied_at, checksum) VALUES (?, CURRENT_TIMESTAMP, ?)', params=(path.name, checksum))
                db.set_commit()
            except Exception:
                db.set_rollback()
                raise
            print(f'Applied {path.name}')


if __name__ == '__main__':
    main()
