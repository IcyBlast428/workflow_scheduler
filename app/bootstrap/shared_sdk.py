"""Freeze the task-facing platform Python source; exclude config and business data."""
import hashlib
import json
from pathlib import Path
import shutil


def freeze(root):
    source=Path(__file__).resolve().parents[1]
    destination=Path(root)/'shared-sdk'/'app'
    if destination.exists():
        manifest=json.loads((destination.parent/'manifest.json').read_text())
        digest=hashlib.sha256(json.dumps([tuple(v) for v in manifest]).encode()).hexdigest()
        if not verify(root,digest): raise ValueError('原 SDK 快照已变化。')
        return digest
    records=[]
    for path in sorted(source.rglob('*.py')):
        rel=path.relative_to(source)
        if len(rel.parts)>1 and rel.parts[0] not in ('common','bootstrap'): continue
        if '__pycache__' in rel.parts or path.is_symlink(): continue
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        blob=path.read_bytes();target.write_bytes(blob)
        records.append((rel.as_posix(),hashlib.sha256(blob).hexdigest()))
    digest=hashlib.sha256(json.dumps(records).encode()).hexdigest()
    (destination.parent/'manifest.json').write_text(json.dumps(records,indent=2))
    return digest


def verify(root,expected):
    source=Path(root)/'shared-sdk'/'app'
    records=[]
    if not source.is_dir() or source.is_symlink(): return False
    for path in sorted(source.rglob('*.py')):
        if path.is_symlink(): return False
        records.append((path.relative_to(source).as_posix(),hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()==expected
