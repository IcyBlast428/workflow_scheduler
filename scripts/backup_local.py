"""Consistent stopped-scheduler SQLite and execution-file backup (Linux/WSL)."""
import argparse
import contextlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def backup(database, data, output):
    import fcntl
    database, data, output = map(lambda value: Path(value).resolve(), (database, data, output))
    if not database.is_file() or not data.is_dir():
        raise ValueError('Existing local database and data directory are required')
    if output == data or data in output.parents:
        raise ValueError('Backup output must be outside the data directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an earlier backup. Scheduler lease prevents concurrent execution.
    with (data / '.scheduler.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / 'database.sqlite3'
            with contextlib.closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as source:
                with contextlib.closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Database integrity check failed')
            with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, 'database.sqlite3')
                for directory in ('executions','audit-spool'):
                    for path in (data / directory).rglob('*'):
                        if path.is_file() and not path.name.startswith('journal.sqlite3'):
                            archive.write(path,'data/'+path.relative_to(data).as_posix())
                journal = data / 'executions/journal.sqlite3'
                if journal.is_file():
                    journal_copy = Path(temporary) / 'journal.sqlite3'
                    with contextlib.closing(sqlite3.connect(f'file:{journal}?mode=ro',uri=True)) as source:
                        with contextlib.closing(sqlite3.connect(journal_copy)) as target:
                            source.backup(target)
                            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                                raise RuntimeError('Execution journal integrity check failed')
                    archive.write(journal_copy,'data/executions/journal.sqlite3')
                if (data / 'metrics.json').is_file():
                    archive.write(data / 'metrics.json', 'data/metrics.json')
                archive.writestr('manifest.json', json.dumps({'format':2,'database':'database.sqlite3','data':'data','credentials_included':False}))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(backup(args.database, args.data, args.output))
    except BlockingIOError:
        parser.exit(2, 'Scheduler is running: stop the local services before backing up.\n')
