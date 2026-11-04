"""Extract a GaussDB platform backup into a NEW directory only; never overwrite live data."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile
import hashlib


def restore(backup, destination):
    backup,destination=Path(backup).resolve(),Path(destination).resolve()
    if destination.exists():
        raise ValueError('恢复目录必须不存在，不能覆盖运行中的数据。')
    with zipfile.ZipFile(backup) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'wfs-platform-1' or archive.testzip():
            raise ValueError('备份格式或校验无效。')
        if manifest.get('format')=='wfs-platform-1':
            digest=hashlib.sha256()
            with archive.open('database.dump') as source:
                for block in iter(lambda:source.read(1024*1024),b''):
                    digest.update(block)
            if digest.hexdigest()!=manifest['dump_sha256']:
                raise ValueError('数据库备份摘要校验失败。')
        for item in archive.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename:
                raise ValueError('备份内含无效路径。')
        destination.mkdir(parents=True)
        try:
            directory_modes = []
            for item in archive.infolist():
                target=destination/item.filename
                target.parent.mkdir(parents=True,exist_ok=True)
                if item.is_dir():
                    target.mkdir(exist_ok=True)
                    directory_modes.append((target, (item.external_attr >> 16) & 0o777))
                else:
                    with archive.open(item) as source,target.open('xb') as output:
                        shutil.copyfileobj(source,output)
                    # Keep executable interpreters, without restoring setuid bits.
                    mode = (item.external_attr >> 16) & 0o777
                    if mode:
                        target.chmod(mode)
            for directory, mode in reversed(directory_modes):
                if mode:
                    directory.chmod(mode)
        except Exception:
            # Preserve failed material for inspection; never remove a computed tree.
            raise
    receipt={'scope':'archive paths and dump checksum','database_restore_verified':False}
    (destination/'restore-receipt.json').write_text(json.dumps(receipt),encoding='utf-8')
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--destination',required=True)
    args=parser.parse_args()
    print(restore(args.backup,args.destination))
