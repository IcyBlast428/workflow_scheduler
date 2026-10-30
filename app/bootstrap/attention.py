"""Bounded read-only operator attention list; notification addresses stay private."""
import datetime as dt
import json
import os
import shutil
from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import DATA_DIR
from app.bootstrap import operations, journal
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.timebase import business_now, TIMEZONE_NAME


def snapshot(admin=False):
    now = business_now()
    state = operations.service_state()
    healthy = bool(state.get('ready') and state.get('heartbeat'))
    if healthy:
        healthy = (now-dt.datetime.fromisoformat(state['heartbeat'])).total_seconds() < 120
    issues = []
    def add(key, title, message, **extra):
        issues.append(dict(key=key, title=title, message=message, **extra))
    specs = {spec['pid']:spec for spec in discover_task_specs()}
    from app.bootstrap.operational_policy import all_tasks,TASK_DEFAULT
    task_policies=all_tasks()
    with GaussDB() as db:
        applications = db.execute_query_sql("SELECT pid,status,message FROM wfs_config_application WHERE status<>'applied' LIMIT 100")
        runs = db.execute_query_sql("SELECT run_id,pid,status,payload FROM wfs_executions WHERE (status IN ('running','queued') OR (status IN ('failed','timed_out','interrupted','skipped','missed') AND created_at>=?)) ORDER BY created_at DESC LIMIT 101", params=(now-dt.timedelta(hours=24),))
        dialect = db.dialect
        for pid,status,message in applications:
            if pid in specs:
                add('config-'+pid, (specs[pid].get('task_name') or pid)+' · 配置未生效', message or '等待调度器应用配置。', pid=pid)
        for run_id,pid,status,payload in runs[:100]:
            record = json.loads(payload)
            began = record.get('start_time') or record['created_at']
            age = max(0,(now-dt.datetime.fromisoformat(began)).total_seconds())
            if status in ('running','queued') and age < task_policies.get(pid,TASK_DEFAULT)['slow_minutes']*60:
                continue
            title = {'failed':'执行失败','timed_out':'执行超时','interrupted':'重启中断','skipped':'已跳过','missed':'错过调度','running':'长时间执行','queued':'长时间等待'}.get(status,status)
            add('run-'+run_id, (record.get('task_name') or pid)+' · '+title, (record.get('reason') or f'已持续 {int(age//60)} 分钟')[:400], pid=pid,run_id=run_id,time=record.get('end_time') or began)
        if admin:
            alerts = dict(db.execute_query_sql("SELECT status,COUNT(*) FROM wfs_notifications WHERE status IN ('failed','unknown','pending') GROUP BY status"))
            if alerts.get('unknown'): add('alerts-unknown','通知需要核对',f"{alerts['unknown']} 条发送结果不明，请先核对接收情况。")
            if alerts.get('failed'): add('alerts-failed','通知发送失败',f"{alerts['failed']} 条通知发送失败。")
            if alerts.get('pending'): add('alerts-pending','通知等待发送',f"{alerts['pending']} 条通知在等待发送。")
    if admin:
        from app.bootstrap.execution_requests import queue_status
        queue=queue_status();counts=queue['counts']
        if counts.get('pending'):
            add('queue-pending','任务等待派发',f"{counts['pending']} 个请求等待执行。"+(queue['reason'] or '按名额与启动间隔依次派发。'))
        if counts.get('expired') or counts.get('rejected'):
            add('queue-expired','计划未能启动',f"最近 24 小时 {counts.get('expired',0)} 个请求等待超时、{counts.get('rejected',0)} 个计划被拒绝。请在执行队列中核对。")
        if counts.get('unknown'):
            add('queue-unknown','执行请求需要核对',f"{counts['unknown']} 个请求派发结果不明，不会自动重放。")
        health = journal.health(operations._directory)
        if health['pending_writes']: add('journal','执行记录等待补写',f"{health['pending_writes']} 条记录尚未完成数据库补写。")
        free = shutil.disk_usage(DATA_DIR).free // 1024**2
        if free < int(os.environ.get('WFS_MIN_FREE_MB','100'))*5: add('disk','数据空间不足',f'剩余空间 {free} MiB，请检查版本与日志占用。')
    for pid,spec in specs.items():
        if spec.get('error') or spec.get('main_file_error'):
            add('invalid-'+pid,(spec.get('task_name') or pid)+' · 配置异常',str(spec.get('error') or spec.get('main_file_error'))[:400],pid=pid)
    from app.bootstrap import admission
    due=[pid for pid,spec in specs.items() if task_policies.get(pid,TASK_DEFAULT)['expected_by'] and spec.get('schedule_enabled') and now.strftime('%H:%M')>=task_policies[pid]['expected_by']]
    completed=set()
    with GaussDB() as db:
        for offset in range(0,len(due),200):
            group=due[offset:offset+200]
            rows=db.execute_query_sql('SELECT DISTINCT pid FROM wfs_run_history WHERE state=0 AND end_time>=? AND pid IN ('+','.join('?' for _ in group)+')',params=(now.replace(hour=0,minute=0,second=0,microsecond=0),*group))
            completed.update(row[0] for row in rows)
    for pid in due:
        if pid not in completed:
            add('deadline-'+str(now.date())+'-'+pid,(specs[pid].get('task_name') or pid)+' · 今日尚未完成',
                '期望在 '+task_policies[pid]['expected_by']+' 前成功完成，请核对执行记录与业务数据。',pid=pid)
    with admission.store() as db:
        handled={key[6:]:json.loads(raw) for key,raw in db.execute("SELECT key,payload FROM settings WHERE key LIKE 'issue:%'")}
    for item in issues:
        item['resolution']=handled.get(item['key'],{})
    return {'scheduler':{'healthy':healthy,'message':'心跳异常或尚未就绪' if not healthy else '正常'},'database':dialect,
            'timezone':TIMEZONE_NAME,'issues':issues[:100],'truncated':len(runs)>100 or len(issues)>100}
