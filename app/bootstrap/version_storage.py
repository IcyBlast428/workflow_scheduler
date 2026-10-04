"""Read-only, bounded release capacity and conservative retention preview."""
import json
import os
import time
from pathlib import Path
from app.bootstrap.database import GaussDB
from app.bootstrap.task_packages import registry, release_dir


def snapshot(keep=20):
    if not 20 <= keep <= 500:
        raise ValueError('保留版本数应在 20 至 500 之间。')
    tasks = registry()
    with GaussDB() as db:
        releases = db.execute_query_sql('SELECT payload FROM wfs_task_releases ORDER BY created_at DESC LIMIT 10001')
        runs = db.execute_query_sql('SELECT payload FROM wfs_executions LIMIT 10001')
    protected = set()
    for (payload,) in runs:
        run = json.loads(payload)
        version = (run.get('code_version') or {}).get('task_release')
        if version: protected.add((run['pid'],version))
    truncated = len(releases)>10000 or len(runs)>10000
    result, counts, applied_counts, entries = [], {}, {}, 0
    deadline = time.monotonic()+3
    total = candidate = trash = 0
    for (payload,) in releases[:10000]:
        data = json.loads(payload); pid, version = data['pid'], data['version']
        task = tasks.get(pid,{})
        counts[pid] = counts.get(pid,0)+1
        if data.get('status') == 'applied':
            applied_counts[pid] = applied_counts.get(pid,0)+1
        reasons = []
        if version == task.get('active_version'): reasons.append('当前使用')
        pending_intent = task.get('pending') or {}
        if version in (pending_intent.get('version'), (pending_intent.get('previous') or {}).get('active_version')): reasons.append('发布中')
        if data.get('status') == 'preparing': reasons.append('正在准备')
        if (pid,version) in protected: reasons.append('执行记录引用')
        if counts[pid]<=keep: reasons.append('最近保留版本')
        if data.get('status') == 'applied' and applied_counts[pid]<=keep: reasons.append('可回退的已发布版本')
        if len(runs)>10000: reasons.append('执行引用未完整检查')
        directory = release_dir(pid,version)
        size, complete = 0, True
        pending = [directory]
        while pending:
            if time.monotonic()>deadline or entries>=100000:
                complete=False; truncated=True; break
            current = pending.pop()
            try:
                with os.scandir(current) as children:
                    for item in children:
                        entries+=1
                        if item.is_symlink(): continue
                        if item.is_dir(follow_symlinks=False): pending.append(Path(item.path))
                        elif item.is_file(follow_symlinks=False): size+=item.stat(follow_symlinks=False).st_size
                        if time.monotonic()>deadline or entries>=100000:
                            complete=False; truncated=True; break
            except FileNotFoundError:
                complete=False
        if not complete: reasons.append('容量未完整扫描')
        total+=size
        if task.get('deleted_at'): trash+=size
        if not reasons: candidate+=size
        result.append({'pid':pid,'name':task.get('task_name') or pid,'version':version,'status':data.get('status'),
                       'bytes':size,'complete':complete,'protected':reasons,'candidate':not bool(reasons),'trash':bool(task.get('deleted_at'))})
    return {'keep':keep,'bytes':total,'candidate_bytes':candidate,'trash_bytes':trash,'versions':result,'truncated':truncated,
            'message':'仅预估占用和保留建议，不删除文件。历史归档的源码追溯需求仍须核对。'}
