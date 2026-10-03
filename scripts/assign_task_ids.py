"""Freeze existing task IDs before moving/renaming directories.

New tasks can opt into --new-ids. Existing manifests are never overwritten.
Copying a task must use a different ID; discovery detects duplicates.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.bootstrap.task_loader import iter_task_directories, build_task_pid, PID_PATTERN
from app.bootstrap.global_vars import TASK_DIR


def freeze(root=TASK_DIR,new_ids=False):
    locations = list(iter_task_directories(root))
    planned,seen = [],set()
    for group,folder,directory in locations:
        path = directory/'.wfs-task.json'
        identifier = json.loads(path.read_text(encoding='utf-8'))['task_id'] if path.exists() else uuid.uuid4().hex if new_ids else build_task_pid(group,folder)
        if not isinstance(identifier,str) or not PID_PATTERN.fullmatch(identifier) or identifier in seen:
            raise ValueError('任务编号无效或重复：'+str(identifier))
        seen.add(identifier)
        if not path.exists():
            planned.append((path,identifier))
    for path,identifier in planned:
        with path.open('x',encoding='utf-8') as stream:
            json.dump({'task_id':identifier},stream,ensure_ascii=False,indent=2)
            stream.write('\n')
    return len(planned)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(TASK_DIR))
    parser.add_argument('--new-ids',action='store_true')
    args = parser.parse_args()
    print('Assigned identities:',freeze(args.root,args.new_ids))
