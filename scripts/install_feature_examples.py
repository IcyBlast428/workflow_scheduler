"""Install the four standalone feature examples as managed, scheduling-disabled local tasks."""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import time
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SOURCE=ROOT/'examples/tasks/feature_suite'

def install():
    from app.bootstrap import task_packages as packages, operational_policy as policies, task_schema, admission
    from app.bootstrap.schedule_config import save_schedule
    if admission.maintenance()['enabled']:raise RuntimeError('维护期间不安装示例。')
    profiles=json.loads((SOURCE/'catalog.json').read_text())
    results=[]
    for profile in profiles:
        existing=next((r for r in packages.registry().values() if r['group_name']=='功能示例' and r['folder_name']==profile['folder']),None)
        if existing:
            print('保留已有示例:',existing['pid'],existing['task_name'],flush=True);results.append(existing);continue
        directory=SOURCE/profile['folder'];buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(directory.rglob('*')):
                if file.is_file() and not file.is_symlink() and '__pycache__' not in file.parts and file.name!='.wfs-task.json':archive.write(file,file.relative_to(directory).as_posix())
        release=packages.stage(buffer.getvalue(),dict(group_name='功能示例',folder_name=profile['folder'],task_name=profile['task_name'],main_file='main.py',archive_layout='preserve'), 'example-installer')
        pid,version=release['pid'],release['version'];packages.prepare(pid,version,'main.py')
        deadline=time.monotonic()+90
        while True:
            prepared=packages.release(pid,version)
            if prepared['status']!='preparing':break
            if time.monotonic()>deadline:raise RuntimeError('示例环境准备超时：'+pid)
            time.sleep(.2)
        if prepared['status']!='ready':raise RuntimeError(prepared['message'])
        record=packages.publish(pid,version,packages.task(pid)['revision'],'example-installer')
        save_schedule(pid,dict(schedule_type='every_hour',main_file='main.py',enabled=False,task_name=profile['task_name'],max_instances=1,timeout_seconds=20 if profile['folder']=='queue_observer' else 30,description=(directory/'README.md').read_text(),owner='示例管理员'))
        current=policies.load('task',pid)
        values={key:profile[key] for key in ('parameters','idempotent','retry_enabled','retry_limit','retry_delay','stagger_seconds','slow_minutes')}
        policies.save('task',pid,{**current,**values},'example-installer')
        admission.save_grant(pid,dict(mode='restricted',connections=[],revision=admission.grant(pid)['revision']),'example-installer')
        task_schema.save_tags(pid,dict(revision=task_schema.tags(pid)['revision'],tags=profile['tags']),'example-installer')
        results.append(record);print('已安装，自动调度关闭:',pid,profile['task_name'],flush=True)
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--env-file',required=True);parser.add_argument('--install',action='store_true');args=parser.parse_args()
    if not args.install:
        print((SOURCE/'catalog.json').read_text());return
    from scripts.service_config import read_environment
    values,removed=read_environment(args.env_file)
    for key in removed:os.environ.pop(key,None)
    os.environ.update(values)
    os.environ.update(WFS_ENABLE_SCHEDULER='false',WFS_SCHEDULER_CONTROL_URL='')
    os.environ.pop('WFS_LOCAL_DB_PATH',None)
    from app import create_app
    app=create_app()
    with app.app_context():install()
if __name__=='__main__':main()
