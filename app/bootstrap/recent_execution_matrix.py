"""Latest completed results per task; indexed bounded reads, no log bodies."""
from app.bootstrap.database import GaussDB
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.execution_state import state_status
from app.bootstrap.execution_matrix import timestamp
from app.bootstrap.timebase import business_now


def snapshot(limit=10):
    tasks = [{'pid':spec['pid'], 'name':spec.get('task_name') or spec.get('folder_name') or spec['pid'],
              'group':spec.get('group_name') or '未分组', 'records':[]}
             for spec in sorted(discover_task_specs(),key=lambda spec:(spec.get('group_name',''),spec['pid']))]
    if len(tasks)>1000:
        raise ValueError('最近执行结果支持最多 1000 个任务。')
    # Each branch uses (pid,end_time,id) and stops at the selected depth.
    with GaussDB() as db:
        for start in range(0,len(tasks),50):
            batch=tasks[start:start+50]
            rows=[]
            for table in ('wfs_run_history','wfs_run_history_archive'):
                query=' UNION ALL '.join(f'(SELECT id,pid,state,start_time,end_time FROM {table} WHERE pid=? ORDER BY end_time DESC,id DESC LIMIT ?)' for task in batch)
                params=tuple(value for task in batch for value in (task['pid'],limit))
                rows.extend(db.execute_query_sql(query,params=params))
            by_pid={task['pid']:{} for task in batch}
            for identifier,pid,state,began,ended in rows:
                key=str(identifier)+'@'+str(ended)
                by_pid[pid][key]={'key':key,'run_id':str(identifier),'pid':pid,'status':state_status(state),
                                 'time':timestamp(ended),'start_time':timestamp(began),'end_time':timestamp(ended),
                                 'query_start':str(ended),'query_end':str(ended),'count':1,'scope':'all'}
            for task in batch:
                task['records']=sorted(by_pid[task['pid']].values(),key=lambda item:(item['query_end'],item['run_id']),reverse=True)[:limit]
    return {'tasks':tasks,'server_time':timestamp(business_now()),'limit':limit}


def cached_snapshot(limit='10'):
    from app.bootstrap.snapshot_cache import cached
    if limit not in ('10', '25'):
        raise ValueError('最近执行次数可选 10 或 25。')
    count = int(limit)
    return cached(('recent-execution-matrix', count), 5, lambda: snapshot(count))
