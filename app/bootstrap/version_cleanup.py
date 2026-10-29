"""Conservative deletion of complete, unreferenced release candidates only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from app.bootstrap import admission, task_packages as packages
from app.bootstrap.database import GaussDB
from app.bootstrap.timebase import business_now
from app.bootstrap.version_storage import snapshot

def plan(keep=20, full_references=None, scan_seconds=3):
    data=snapshot(keep,full_references=full_references,scan_seconds=scan_seconds,max_entries=10000000 if full_references is not None else 100000)
    candidates=[{'pid':v['pid'],'version':v['version'],'bytes':v['bytes']} for v in data['versions'] if v['candidate'] and v['complete']]
    fingerprint=hashlib.sha256(json.dumps([keep,candidates],sort_keys=True).encode()).hexdigest()
    return {'keep':keep,'candidates':candidates,'fingerprint':fingerprint,'truncated':data['truncated'],
            'bytes':sum(v['bytes'] for v in candidates),'confirm':'清理 '+str(len(candidates))+' 个未引用版本'}

def _no_links(root):
    if root.is_symlink(): raise ValueError('不能清理链接目录。')
    for directory,children,files in os.walk(root,followlinks=False):
        for name in children+files:
            path=Path(directory)/name
            if path.is_symlink():
                # Interpreter links are internal installation details: unlink,
                # never follow them. Directory links are not accepted.
                resolved=path.resolve()
                import sys
                if not resolved.is_relative_to(root) and resolved!=Path(sys.executable).resolve():
                    raise ValueError('版本包含外部链接，请由运维核对。')

def execute(form,actor,full_references=None,scan_seconds=3):
    from app.bootstrap.core import _configuration_lock
    if not admission.maintenance()['enabled']: raise RuntimeError('请先进入维护模式，再执行版本清理。')
    from app.bootstrap.global_vars import runnings, DATA_DIR
    from app.bootstrap import journal
    recovery=journal.health(Path(os.environ.get('WFS_DATA_DIR',DATA_DIR))/'executions')
    if recovery['pending_writes'] or recovery['legacy_scan_in_progress']:
        raise RuntimeError('仍有执行记录待恢复或补写，请先完成核对再清理。')
    if runnings.count(): raise RuntimeError('仍有活动或预留执行，不能清理。')
    with _configuration_lock, admission.lock:
        current=plan(form.get('keep',20),full_references=full_references,scan_seconds=scan_seconds)
        if current['truncated']: raise RuntimeError('扫描不完整，不能清理。请缩小版本数量后由运维核对。')
        if form.get('fingerprint')!=current['fingerprint'] or form.get('confirm')!=current['confirm']:
            raise RuntimeError('清理预览已变化或确认文字不匹配。')
        if len(current['candidates'])>100: raise ValueError('单次最多清理 100 个版本。')
        result=[]
        quarantine=packages.storage_root()/'.cleanup-quarantine'/uuid.uuid4().hex
        quarantine.mkdir(parents=True)
        for item in current['candidates']:
            pid,version=item['pid'],item['version']
            data=packages.release(pid,version)
            root=packages.release_dir(pid,version)
            _no_links(root)
            destination=quarantine/(pid+'-'+version)
            os.replace(root,destination)
            try:
                data.update(status='cleaned',cleaned_at=str(business_now()),cleaned_by=actor,manifest=[],python='',message='未引用版本已清理；审计元数据保留。')
                packages._write_release(data)
            except BaseException:
                os.replace(destination,root)
                raise
            # Only our freshly renamed validated directory is removed.
            for directory,children,files in os.walk(destination,followlinks=False):
                os.chmod(directory,0o700)
            shutil.rmtree(destination)
            result.append(item)
        return {'cleaned':result,'bytes':sum(v['bytes'] for v in result)}
