"""Execution provenance, without copying source for every invocation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from app.bootstrap.global_vars import BASE_DIR
from app.bootstrap.snapshot_cache import cached


def _release():
    marker = BASE_DIR.parent / '.release-revision'
    if marker.is_file():
        return marker.read_text(encoding='utf-8').strip()[:200]
    try:
        return subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE_DIR.parent,timeout=2,stderr=subprocess.DEVNULL).decode().strip()
    except (OSError,subprocess.SubprocessError):
        return 'development'


def execution_version(entry, python_executable=''):
    path = Path(entry).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    executable = python_executable or sys.executable
    def runtime():
        try:
            return subprocess.check_output([executable,'--version'],executable=executable if os.name == 'nt' else None,
                                           timeout=3,stderr=subprocess.STDOUT).decode().strip()[:200]
        except (OSError,subprocess.SubprocessError):
            return 'unknown'
    requirements = []
    for parent in (path.parent,path.parent.parent,BASE_DIR.parent):
        for name in ('requirements.txt','requirements-linux-py312.lock','poetry.lock','uv.lock'):
            lock = parent/name
            if lock.is_file() and lock.stat().st_size<=2*1024*1024:
                requirements.append((name,hashlib.sha256(lock.read_bytes()).hexdigest()))
    task_version = {}
    entry_label = path.name
    from app.bootstrap.task_packages import storage_root
    try:
        relative = path.relative_to(storage_root())
        if len(relative.parts) >= 5 and relative.parts[1] == 'releases' and relative.parts[3] == 'code':
            marker = storage_root().joinpath(*relative.parts[:3]) / '.release.json'
            task_version = json.loads(marker.read_text(encoding='utf-8'))
            entry_label = '/'.join(relative.parts[4:])
            package_requirements = storage_root().joinpath(*relative.parts[:4]) / 'requirements.txt'
            if package_requirements.is_file() and package_requirements.stat().st_size <= 2*1024*1024:
                requirements.append(('task/requirements.txt', hashlib.sha256(package_requirements.read_bytes()).hexdigest()))
    except (OSError, ValueError):
        pass
    return {**task_version, 'release':cached('release-revision',30,_release,mutable=False),
            'entry':entry_label,'entry_sha256':digest,'python':cached(('python-version',executable),300,runtime,mutable=False),
            'dependency_sha256':hashlib.sha256(repr(requirements).encode()).hexdigest(),
            'immutable_release':(BASE_DIR.parent/'.release-revision').is_file()}
