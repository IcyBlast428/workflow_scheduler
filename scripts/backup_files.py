"""Shared managed-task archive traversal, including prepared environments."""
import os
from pathlib import Path
import sys


def add_connection_settings(archive, data, temporary):
    """Consistent encrypted settings snapshot. Encryption keys stay external."""
    import contextlib
    import sqlite3
    source_path = Path(data) / 'database-connections.sqlite3'
    if not source_path.exists():
        return False
    if source_path.is_symlink():
        raise ValueError('Connection settings must be a real local file')
    snapshot = Path(temporary) / 'database-connections.sqlite3'
    with contextlib.closing(sqlite3.connect(f'file:{source_path.as_posix()}?mode=ro', uri=True)) as source:
        with contextlib.closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Connection settings integrity check failed')
    if os.name != 'nt':
        snapshot.chmod(0o600)
    archive.write(snapshot, 'data/database-connections.sqlite3')
    return True


def add_task_storage(archive, data, releases=None, output=None):
    data = Path(data).resolve()
    release_root = Path(releases).resolve() if releases else data / 'task-packages'
    output = Path(output or archive.filename).resolve()
    if output == release_root or release_root in output.parents:
        raise ValueError('Backup output must be outside the task release directory')
    interpreter = Path(sys.executable).resolve()
    for root, prefix in ((release_root, 'data/task-packages'), (data / 'task-data', 'data/task-data')):
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError('Task storage must be a real directory')
        for directory, children, names in os.walk(root, followlinks=True):
            relative_directory = Path(directory).relative_to(root)
            if relative_directory.parts:
                archive.write(directory, prefix + '/' + relative_directory.as_posix() + '/')
            children[:] = [name for name in children if name != '__pycache__']
            for name in children:
                child = Path(directory) / name
                if child.is_symlink():
                    resolved = child.resolve(strict=True)
                    environment = any(part.startswith('environment-') for part in child.relative_to(root).parts)
                    current = Path(directory).resolve()
                    if not environment or not resolved.is_relative_to(root) or resolved == current or resolved in current.parents:
                        raise ValueError('External or cyclic directory links require a separate backup')
            for name in names:
                path = Path(directory) / name
                relative = path.relative_to(root)
                if path.is_symlink():
                    # Flatten venv interpreter links so restore cannot create links
                    # outside its new directory. Other external links are refused.
                    resolved = path.resolve(strict=True)
                    environment = any(part.startswith('environment-') for part in relative.parts)
                    if not environment or not (resolved.is_relative_to(root) or resolved == interpreter):
                        raise ValueError('External links in task storage require a separate backup')
                if path.is_file():
                    archive.write(path, prefix + '/' + relative.as_posix())
