"""Rebuild into a NEW directory using retained wheels and hashes, without network."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
import tempfile

def rebuild(release,destination):
    release,destination=Path(release).resolve(),Path(destination).resolve()
    if destination.exists(): raise ValueError('目标环境目录必须尚不存在。')
    if (release/'dependency-bundle.json').is_symlink(): raise ValueError('不能读取链接形式的依赖清单。')
    bundle=json.loads((release/'dependency-bundle.json').read_text())
    current=[list(sys.version_info[:3]),platform.system(),platform.machine()]
    if bundle['runtime']!=current: raise ValueError('Python 补丁版本、系统或架构不匹配，请使用原运行环境。')
    directory=bundle['directory']
    if Path(directory).name!=directory or not directory.startswith('dependency-wheels-'): raise ValueError('依赖目录无效。')
    wheels=release/directory
    if wheels.is_symlink(): raise ValueError('依赖目录不能使用链接。')
    locked=[]
    from packaging.utils import parse_wheel_filename
    for item in bundle['wheels']:
        if Path(item['file']).name!=item['file']: raise ValueError('wheel 文件名无效。')
        path=wheels/item['file']
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']: raise ValueError('wheel 校验失败。')
        name,version,_,_=parse_wheel_filename(item['file'])
        locked.append(str(name)+'=='+str(version)+' --hash=sha256:'+item['sha256'])
    subprocess.run([sys.executable,'-I','-m','venv',str(destination)],check=True)
    python=destination/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    with tempfile.TemporaryDirectory(prefix='wfs-rebuild-') as temporary:
        lock=Path(temporary)/'requirements.txt';lock.write_text('\n'.join(locked)+'\n')
        subprocess.run([str(python),'-I','-m','pip','--isolated','install','--no-index','--no-deps','--require-hashes','--find-links',str(wheels),'-r',str(lock)],check=True)
    subprocess.run([str(python),'-I','-m','pip','check'],check=True)
    return python

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',required=True);parser.add_argument('--destination',required=True)
    args=parser.parse_args();print(rebuild(args.release,args.destination))
