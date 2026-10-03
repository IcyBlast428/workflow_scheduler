"""Stopped-scheduler platform backup using the matching vendor dump utility.

Passwords are never command arguments. Configure tool authentication beforehand.
--container is only a convenience for the dedicated local PostgreSQL test image.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile


def bundle(data, tasks, output, database, schema, user, host='127.0.0.1',port=5432,tool='pg_dump',container=None):
    import fcntl
    data,tasks,output=map(lambda value:Path(value).resolve(),(data,tasks,output))
    if not data.is_dir() or not tasks.is_dir() or output.exists() or data in output.parents or tasks in output.parents:
        raise ValueError('需要有效数据/任务目录，以及位于这两个目录之外的新备份文件。')
    output.parent.mkdir(parents=True,exist_ok=True)
    with (data/'.scheduler.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory() as temporary:
            dump=Path(temporary)/'database.dump'
            if container:
                if tool!='pg_dump':
                    raise ValueError('容器模式仅用于 PostgreSQL 本地测试。')
                with dump.open('xb') as target:
                    subprocess.run(['docker','exec',container,'pg_dump','-U',user,'-F','c','-n',schema,database],stdout=target,check=True)
            else:
                subprocess.run([tool,'-h',host,'-p',str(port),'-U',user,'-F','c','-n',schema,'-f',str(dump),database],check=True)
            digest=hashlib.sha256()
            with dump.open('rb') as source:
                for block in iter(lambda:source.read(1024*1024),b''):
                    digest.update(block)
            journal=data/'executions/journal.sqlite3'
            snapshot=Path(temporary)/'journal.sqlite3'
            if journal.is_file():
                with contextlib.closing(sqlite3.connect(f'file:{journal}?mode=ro',uri=True)) as source:
                    with contextlib.closing(sqlite3.connect(snapshot)) as target:
                        source.backup(target)
                        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                            raise RuntimeError('本地执行记录校验失败')
            # Reserve with restrictive permissions and refuse all overwrites.
            descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as target,zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(dump,'database.dump')
                if snapshot.exists():
                    archive.write(snapshot,'data/executions/journal.sqlite3')
                for name in ('executions','audit-spool'):
                    for path in (data/name).rglob('*'):
                        if path.is_file() and not path.is_symlink() and not path.name.startswith('journal.sqlite3'):
                            archive.write(path,'data/'+path.relative_to(data).as_posix())
                for path in tasks.rglob('*'):
                    relative=path.relative_to(tasks)
                    if path.is_file() and not path.is_symlink() and not any(part in ('.venv','__pycache__','.git','.wfs-secrets') or part.startswith('.env') for part in relative.parts):
                        archive.write(path,'jobs/'+relative.as_posix())
                archive.writestr('manifest.json',json.dumps({'format':'wfs-platform-1','database':database,'schema':schema,
                    'dump_tool':tool,'created_at':dt.datetime.now().isoformat(' '),'dump_sha256':digest.hexdigest(),
                    'connection_passwords_included':False,'restore_target':'new database only'},indent=2))
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('data','tasks','output','database','schema','user'):
        parser.add_argument('--'+option,required=True)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=5432)
    parser.add_argument('--tool',default='pg_dump')
    parser.add_argument('--container')
    args=parser.parse_args()
    print(bundle(**vars(args)))
