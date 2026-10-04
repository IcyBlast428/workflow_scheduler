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
            if status in ('running','queued') and age < int(os.environ.get('WFS_LONG_RUN_SECONDS','3600')):
                continue
            title = {'failed':'执行失败','timed_out':'执行超时','interrupted':'重启中断','skipped':'并发跳过','missed':'错过调度','running':'长时间执行','queued':'长时间等待'}.get(status,status)
            add('run-'+run_id, (record.get('task_name') or pid)+' · '+title, (record.get('reason') or f'已持续 {int(age//60)} 分钟')[:400], pid=pid,run_id=run_id,time=record.get('end_time') or began)
        if admin:
            alerts = dict(db.execute_query_sql("SELECT status,COUNT(*) FROM wfs_notifications WHERE status IN ('failed','unknown','pending') GROUP BY status"))
            if alerts.get('unknown'): add('alerts-unknown','通知需要核对',f"{alerts['unknown']} 条发送结果不明，请先核对接收情况。")
            if alerts.get('failed'): add('alerts-failed','通知发送失败',f"{alerts['failed']} 条通知发送失败。")
            if alerts.get('pending'): add('alerts-pending','通知等待发送',f"{alerts['pending']} 条通知在等待发送。")
    if admin:
        health = journal.health(operations._directory)
        if health['pending_writes']: add('journal','执行记录等待补写',f"{health['pending_writes']} 条记录尚未完成数据库补写。")
        free = shutil.disk_usage(DATA_DIR).free // 1024**2
        if free < int(os.environ.get('WFS_MIN_FREE_MB','100'))*5: add('disk','数据空间不足',f'剩余空间 {free} MiB，请检查版本与日志占用。')
    for pid,spec in specs.items():
        if spec.get('error') or spec.get('main_file_error'):
            add('invalid-'+pid,(spec.get('task_name') or pid)+' · 配置异常',str(spec.get('error') or spec.get('main_file_error'))[:400],pid=pid)
    return {'scheduler':{'healthy':healthy,'message':'心跳异常或尚未就绪' if not healthy else '正常'},'database':dialect,
            'timezone':TIMEZONE_NAME,'issues':issues[:100],'truncated':len(runs)>100 or len(issues)>100}
