"""Bounded, log-text-free day snapshots for the task execution matrix."""
import datetime as dt
import json
import math

from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import ignores
from app.bootstrap.operations import read_run
from app.bootstrap.task_loader import discover_task_specs
from app.extensions import scheduler
from app.bootstrap.execution_state import state_status, is_failure

MAX_MARKS = 5000
MAX_ACTIVE = 1000


def timestamp(value):
    return value.isoformat(' ', timespec='seconds') if isinstance(value, dt.datetime) else str(value or '')


def snapshot(date=None):
    now = dt.datetime.now()
    try:
        day = dt.date.fromisoformat(date) if date else now.date()
    except (TypeError, ValueError):
        raise ValueError('日期格式无效。')
    if day > now.date() or day < now.date() - dt.timedelta(days=89):
        raise ValueError('执行矩阵支持最近90天，请通过调度日志查询更早的归档。')
    start = dt.datetime.combine(day, dt.time())
    end = start + dt.timedelta(days=1)
    tasks = []
    for spec in sorted(discover_task_specs(), key=lambda item: (item.get('group_name', ''), item['pid'])):
        job = scheduler.get_job(spec['pid'])
        invalid = bool(spec.get('error') or spec.get('main_file_error'))
        paused = spec['pid'] in ignores
        next_time = getattr(job, 'next_run_time', None) if not paused and not invalid else None
        if next_time and next_time.tzinfo:
            next_time = next_time.astimezone().replace(tzinfo=None)
        tasks.append({'pid':spec['pid'], 'name':spec.get('task_name') or spec.get('folder_name') or spec['pid'],
                      'group':spec.get('group_name') or '未分组', 'invalid':invalid,
                      'configured':bool(spec.get('schedule_configured')),
                      'enabled':bool(job) and not paused and not invalid,
                      'next_run_time':timestamp(next_time)})
    if len(tasks) > 1000:
        raise ValueError('当前任务超过1000个，请先按业务拆分任务目录。')
    records, active = [], []
    aggregated, bucket = False, 0
    warnings = []
    pids = {task['pid'] for task in tasks}
    if pids:
        predicate = 'end_time>=? AND end_time<? AND pid IN ({})'.format(','.join('?' for _ in tasks))
        params = (start, min(end, now), *[task['pid'] for task in tasks])
        with GaussDB() as db:
            rows = db.execute_query_sql(
                f'SELECT id,pid,state,start_time,end_time FROM wfs_run_history WHERE {predicate} '
                'ORDER BY end_time DESC,id DESC LIMIT ?', params=(*params, MAX_MARKS+1))
            if len(rows) <= MAX_MARKS:
                for identifier, pid, state, began, ended in rows:
                    began = dt.datetime.fromisoformat(str(began))
                    ended = dt.datetime.fromisoformat(str(ended))
                    records.append({'key':str(identifier)+'@'+timestamp(ended), 'pid':pid,
                                    'run_id':str(identifier), 'status':state_status(state),
                                    'time':timestamp(ended), 'start_time':timestamp(began),
                                    'end_time':timestamp(ended), 'duration':max(0,(ended-began).total_seconds()),
                                    'query_start':ended.isoformat(' '), 'query_end':ended.isoformat(' '),
                                    'count':1, 'failed':int(is_failure(state))})
            else:
                aggregated = True
                bucket = max(15, math.ceil(1440*len(tasks)/MAX_MARKS/5)*5)
                while math.ceil(1440/bucket)*len(tasks) > MAX_MARKS:
                    bucket += 5
                minute = ("CAST(strftime('%H',end_time) AS INTEGER)*60+CAST(strftime('%M',end_time) AS INTEGER)"
                          if db._local_sqlite else 'CAST(EXTRACT(HOUR FROM end_time) AS INTEGER)*60+CAST(EXTRACT(MINUTE FROM end_time) AS INTEGER)')
                bin_sql = f'CAST(({minute}) / {bucket} AS INTEGER)'
                rows = db.execute_query_sql(f'''SELECT pid,{bin_sql} AS slot,COUNT(*),
SUM(CASE WHEN state=0 THEN 1 ELSE 0 END),
SUM(CASE WHEN state IS NOT NULL AND state NOT IN (0,-15,-1,-10001,-10002) THEN 1 ELSE 0 END),
SUM(CASE WHEN state=-15 THEN 1 ELSE 0 END),MAX(end_time),
SUM(CASE WHEN state=-1 THEN 1 ELSE 0 END),SUM(CASE WHEN state=-9 THEN 1 ELSE 0 END),
SUM(CASE WHEN state=-10001 THEN 1 ELSE 0 END),SUM(CASE WHEN state=-10002 THEN 1 ELSE 0 END)
FROM wfs_run_history WHERE {predicate} GROUP BY pid,{bin_sql} ORDER BY pid,slot''', params=params)
                for pid, slot, count, success, failed, cancelled, last, interrupted, timed_out, skipped, missed in rows:
                    began = start+dt.timedelta(minutes=int(slot)*bucket)
                    ended = min(began+dt.timedelta(minutes=bucket), end)
                    status = 'failed' if failed > timed_out else 'timed_out' if timed_out else 'interrupted' if interrupted else 'missed' if missed else 'skipped' if skipped else 'cancelled' if cancelled else 'success' if success==count else 'unknown'
                    records.append({'key':f'{pid}@{slot}', 'pid':pid, 'run_id':'', 'status':status,
                                    'time':timestamp(last), 'start_time':timestamp(began), 'end_time':timestamp(ended),
                                    'query_start':began.isoformat(' '), 'query_end':(ended-dt.timedelta(microseconds=1)).isoformat(' '),
                                    'count':int(count), 'success':int(success), 'failed':int(failed), 'cancelled':int(cancelled),
                                    'interrupted':int(interrupted), 'timed_out':int(timed_out),'skipped':int(skipped),'missed':int(missed)})
            if day == now.date():
                # Only active executions; never enumerate the file journal or read historical log text.
                rows = db.execute_query_sql("SELECT run_id,payload FROM wfs_executions WHERE status IN ('queued','running') AND created_at<? ORDER BY created_at DESC LIMIT ?", params=(end, MAX_ACTIVE+1))
                if len(rows)>MAX_ACTIVE:
                    warnings.append('活动实例超过显示上限，部分实例未绘制。')
                for run_id, payload in rows[:MAX_ACTIVE]:
                    try:
                        item = json.loads(payload)
                    except (TypeError, ValueError):
                        warnings.append('一条活动实例记录无法读取，请查看系统日志。')
                        continue
                    if not isinstance(item, dict):
                        continue
                    try:
                        item = read_run(run_id)  # Fresh journal for this known active ID only.
                    except (ValueError, OSError):
                        pass
                    if item.get('pid') not in pids or item.get('status') not in {'running','queued'}:
                        continue
                    active.append({'key':run_id, 'run_id':run_id, 'pid':item['pid'], 'status':item['status'],
                                   'time':timestamp(now), 'start_time':item.get('start_time') or item.get('created_at') or timestamp(now),
                                   'end_time':'', 'count':1, 'failed':0, 'inspectable':True})
    pending = []
    if day == now.date():
        for task in tasks:
            if task['next_run_time'] and start <= dt.datetime.fromisoformat(task['next_run_time']) < end:
                pending.append({'key':'plan:'+task['pid'], 'pid':task['pid'], 'run_id':'', 'status':'pending',
                                'time':task['next_run_time'], 'start_time':task['next_run_time'], 'end_time':'', 'count':1, 'failed':0})
    return {'date':day.isoformat(), 'server_time':timestamp(now), 'tasks':tasks,
            'records':records, 'active':active, 'pending':pending, 'aggregated':aggregated,
            'bucket_minutes':bucket, 'total_executions':sum(item['count'] for item in records),
            'warnings':warnings, 'max_marks':MAX_MARKS}


_revisions = {}
import threading
import hashlib
_revision_lock = threading.RLock()


def cached_snapshot(date=None, cursor=None):
    from app.bootstrap.snapshot_cache import cached
    day = date or dt.date.today().isoformat()
    result = cached(('matrix',day,MAX_MARKS), 5 if day == dt.date.today().isoformat() else 60, lambda:snapshot(day),mutable=False)
    # Incremental transport also handles changing aggregation buckets and removals.
    current = {item['key']:item for item in result['records']}
    revision = hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()[:24]
    result['cursor'] = day+':'+revision
    with _revision_lock:
        old = _revisions.get(cursor)
        if old is not None and cursor.startswith(day+':'):
            result['records'] = [item for key,item in current.items() if old.get(key) != item]
            result['removed'] = [key for key in old if key not in current]
            result['incremental'] = True
        else:
            result['incremental'] = False
        _revisions[result['cursor']] = current
        while len(_revisions) > 8:
            _revisions.pop(next(iter(_revisions)))
    return result
