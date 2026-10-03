import os
import subprocess
import datetime
import time
import threading
from urllib.parse import urljoin

import requests
from flask import request, g
from flask_restful import Resource

from app.bootstrap.core import aps_start, call_task_once, kill_process
from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import BASE_DIR, TASK_DIR, error_msg, ignores, runnings, success_msg
from app.bootstrap.schedule_config import load_schedule, preview_schedule, resolve_task_spec, save_schedule, set_schedule_enabled
from app.bootstrap.system_metrics import cpu_monitor_snapshot, recent_task_starts
from app.bootstrap.task_loader import discover_task_specs
from app.extensions import scheduler
from app.bootstrap.execution_state import FAILURE_SQL, NON_FAILURE, is_failure
from app.bootstrap.run_summary import coverage
from app.bootstrap.snapshot_cache import cached
from app.settings import (
    CODE_UPDATE_BRANCH,
    CODE_UPDATE_PATH,
    CODE_UPDATE_REMOTE,
    WFS_ENABLE_SCHEDULER,
    WFS_SCHEDULER_CONTROL_URL,
)


MAX_PAGE_SIZE = 100
RECENT_HOURS = 24
CPU_TIMELINE_HOURS = 6


def _get_page_args(default_pagesize=10):
    try:
        current_page = int(request.args.get("currentPage") or 1)
    except (TypeError, ValueError):
        current_page = 1
    try:
        pagesize = int(request.args.get("pagesize") or default_pagesize)
    except (TypeError, ValueError):
        pagesize = default_pagesize
    return max(1, current_page), min(MAX_PAGE_SIZE, max(1, pagesize))


def _approx_total(current_page, pagesize, row_count, has_more):
    offset = (current_page - 1) * pagesize
    return offset + row_count + (1 if has_more else 0)


def _task_id_options():
    ids = {
        spec.get('pid') or spec.get('folder_name')
        for spec in discover_task_specs(TASK_DIR)
        if spec.get('pid') or spec.get('folder_name')
    }
    return [{"id": pid} for pid in sorted(ids)]


def _build_task_log_filters(pid=None, taskstate=None, datetimeval=None):
    clauses = []
    params = []
    if pid:
        clauses.append("pid = ?")
        params.append(pid)
    if taskstate in ("成功", "鎴愬姛"):
        clauses.append("state = 0")
    elif taskstate in ("失败", "澶辫触"):
        clauses.append(FAILURE_SQL)
    elif taskstate in ('已停止','重启中断','超时/终止','并发跳过','错过调度'):
        clauses.append('state = ?')
        params.append({'已停止':-15,'重启中断':-1,'超时/终止':-9,'并发跳过':-10001,'错过调度':-10002}[taskstate])
    if datetimeval and len(datetimeval) >= 2:
        clauses.append("end_time >= ?")
        clauses.append("end_time <= ?")
        params.extend([datetimeval[0], datetimeval[1]])
    return clauses, params


def _build_system_log_filters(systemids=None, datetimeval=None):
    clauses = []
    params = []
    if systemids:
        clauses.append("pid = ?")
        params.append(systemids)
    if datetimeval and len(datetimeval) >= 2:
        clauses.append("datetime_info >= ?")
        clauses.append("datetime_info <= ?")
        params.extend([datetimeval[0], datetimeval[1]])
    return clauses, params


def _scheduler_control_enabled():
    return (not WFS_ENABLE_SCHEDULER) and bool(WFS_SCHEDULER_CONTROL_URL)


def _internal_auth_headers():
    headers = {}
    if request.headers.get('Cookie'):
        headers['Cookie'] = request.headers['Cookie']
    if request.headers.get('X-CSRF-Token'):
        headers['X-CSRF-Token'] = request.headers['X-CSRF-Token']
    return headers


def _proxy_scheduler_resource(resource_path):
    g.audit_forwarded = True
    url = urljoin(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/', resource_path.lstrip('/'))
    headers = _internal_auth_headers()
    try:
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            params=request.args,
            json=request.get_json(silent=True),
            timeout=30,
        )
    except requests.RequestException as exc:
        return error_msg('scheduler control unavailable: {}'.format(exc))
    try:
        payload = response.json()
    except ValueError:
        return error_msg('scheduler control returned non-json response')
    return payload, response.status_code


def _scheduler_json(resource_path, params=None, timeout=10):
    url = urljoin(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/', resource_path.lstrip('/'))
    headers = _internal_auth_headers()
    response = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get('code') != 20000:
        raise RuntimeError(payload.get('message') or 'scheduler returned error')
    return payload.get('data') or {}


def _run_git_command(args):
    proc = subprocess.Popen(
        ["git"] + args,
        cwd=CODE_UPDATE_PATH,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return 124, '', 'git command timed out'
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')
    return proc.returncode, output, error_output


def _update_code_to_configured_branch():
    """检查远端版本；运行中的工作树只能通过部署流程更新。"""
    revision = BASE_DIR.parent / '.release-revision'
    if revision.is_file():
        current = revision.read_text(encoding='utf-8').strip()
    else:
        code, current, error = _run_git_command(['rev-parse', 'HEAD'])
        if code:
            return False, error
    code, remote, error = _run_git_command(['ls-remote', '--heads', CODE_UPDATE_REMOTE, 'refs/heads/{}'.format(CODE_UPDATE_BRANCH)])
    if code:
        return False, error
    if not remote.strip():
        return False, 'configured remote branch does not exist'
    available = remote.split()[0]
    if current.strip() == available.strip():
        return True, '当前已是最新版本：{}'.format(current.strip()[:12])
    return True, '发现新版本：{}。请通过部署流程发布并重启服务；当前版本：{}。'.format(
        available.strip()[:12], current.strip()[:12]
    )


_failure_totals_cache = {}
_failure_totals_expiry = 0
_failure_totals_lock = threading.Lock()


def _failure_totals():
    global _failure_totals_cache, _failure_totals_expiry
    with _failure_totals_lock:
        if time.monotonic() >= _failure_totals_expiry:
            from app.bootstrap.failure_totals import load_totals
            rows = load_totals()
            _failure_totals_cache = {row[0]: int(row[1]) for row in rows}
            _failure_totals_expiry = time.monotonic()+60
        return dict(_failure_totals_cache)


def _load_job_stats():
    try:
        with GaussDB() as db:
            rows = db.execute_query_sql(
                """
                SELECT s.pid, s.group_name, s.folder_name, s.last_status, s.failed_times, s.last_sms_alarm,
                       0 AS total_failures
                FROM wfs_job_stats s
                """,
                return_json=True,
            )
        totals = _failure_totals()
        for row in rows:
            row['total_failures'] = totals.get(row['pid'],0)
        return {row['pid']: row for row in rows}
    except Exception:
        return {}


def _empty_dashboard_trend():
    now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [now - datetime.timedelta(hours=index) for index in range(RECENT_HOURS - 1, -1, -1)]
    return [
        {
            'hour': hour.strftime('%m-%d %H:00'),
            'success': 0,
            'failed': 0,
        }
        for hour in hours
    ]


def _load_recent_run_stats():
    return cached('recent-statistics',10,_recent_run_stats,mutable=False)


def _recent_run_stats():
    trend = _empty_dashboard_trend()
    trend_by_hour = {item['hour']: item for item in trend}
    since = datetime.datetime.now().replace(minute=0,second=0,microsecond=0)-datetime.timedelta(hours=RECENT_HOURS-1)
    try:
        with GaussDB() as db:
            complete = coverage(db)['complete']
            if complete:
                rows = db.execute_query_sql('SELECT bucket,status,SUM(executions) FROM wfs_run_summary WHERE bucket>=? GROUP BY bucket,status',params=(since,))
                rank = db.execute_query_sql("SELECT pid,SUM(executions) FROM wfs_run_summary WHERE bucket>=? AND status IN ('failed','timed_out') GROUP BY pid ORDER BY SUM(executions) DESC LIMIT 8",params=(since,))
            else:
                # Exact, log-text-free fallback during bounded historical backfill.
                hour = "strftime('%Y-%m-%d %H:00:00',end_time)" if db._local_sqlite else "date_trunc('hour',end_time)"
                raw = db.execute_query_sql(f'SELECT {hour},state,COUNT(*) FROM wfs_run_history WHERE end_time>=? GROUP BY {hour},state',params=(since,))
                from app.bootstrap.execution_state import state_status
                rows = [(bucket,state_status(state),count) for bucket,state,count in raw]
                rank = db.execute_query_sql(f'SELECT pid,COUNT(*) FROM wfs_run_history WHERE end_time>=? AND {FAILURE_SQL} GROUP BY pid ORDER BY COUNT(*) DESC LIMIT 8',params=(since,))
            latest = db.execute_query_sql('SELECT pid,taskname,state,start_time,end_time,group_name,folder_name FROM wfs_run_history ORDER BY end_time DESC,id DESC LIMIT 8',return_json=True)
        for bucket,status,count in rows:
            key = datetime.datetime.fromisoformat(str(bucket)).strftime('%m-%d %H:00')
            if key in trend_by_hour:
                target = 'success' if status=='success' else 'failed' if status in ('failed','timed_out') else status
                trend_by_hour[key][target] = trend_by_hour[key].get(target,0)+int(count)
        names = {spec['pid']:spec.get('task_name') or spec['folder_name'] for spec in discover_task_specs()}
        return {'trend':trend,'failure_rank':[{'id':pid,'name':names.get(pid,pid),'count':int(count)} for pid,count in rank],
                'recent_runs':[dict(row,id=row['pid'],name=row['taskname'] or row['pid'],start_time=str(row['start_time']),end_time=str(row['end_time'])) for row in latest],
                'error':'' if complete else '历史统计正在后台补算；当前使用完整原始记录计算。'}
    except Exception as exc:
        return {'trend':trend,'failure_rank':[],'recent_runs':[],'error':str(exc)}


def _format_datetime_value(value):
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    text = str(value or '').strip()
    if not text:
        return ''
    return text.replace('T', ' ')[:19]


def _parse_datetime_value(value):
    text = _format_datetime_value(value)
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def _task_marker_end(item):
    end_time = _parse_datetime_value(item.get('end_time'))
    start_time = _parse_datetime_value(item.get('start_time'))
    return end_time or start_time


def _same_task_marker(left, right):
    if (left.get('id') or '') != (right.get('id') or ''):
        return False
    left_start = _parse_datetime_value(left.get('start_time'))
    right_start = _parse_datetime_value(right.get('start_time'))
    if not left_start or not right_start:
        return False
    if abs((left_start - right_start).total_seconds()) > 2:
        return False
    left_end = _task_marker_end(left)
    right_end = _task_marker_end(right)
    if not left_end or not right_end:
        return True
    overlap = min(left_end, right_end) >= max(left_start, right_start) - datetime.timedelta(seconds=1)
    similar_end = abs((left_end - right_end).total_seconds()) <= 5
    return overlap or similar_end


def _merge_task_marker(left, right):
    left_start = _parse_datetime_value(left.get('start_time'))
    right_start = _parse_datetime_value(right.get('start_time'))
    left_end = _parse_datetime_value(left.get('end_time'))
    right_end = _parse_datetime_value(right.get('end_time'))
    preferred = right if right.get('source') == 'history' else left
    start_time = min([item for item in (left_start, right_start) if item])
    merged = dict(left)
    merged.update(preferred)
    merged['start_time'] = _format_datetime_value(start_time)
    if left_end or right_end:
        merged['end_time'] = _format_datetime_value(max([item for item in (left_end, right_end) if item]))
        merged['source'] = preferred.get('source') or 'history'
    else:
        merged['end_time'] = ''
        merged['source'] = 'running'
    if left.get('state') not in (None, '') and right.get('state') in (None, ''):
        merged['state'] = left.get('state')
    return merged


def _dedupe_task_markers(items):
    merged = []
    for item in sorted(items, key=lambda value: (
        value.get('id') or '',
        _parse_datetime_value(value.get('start_time')) or datetime.datetime.min,
        0 if value.get('source') == 'history' else 1,
    )):
        start_time = _format_datetime_value(item.get('start_time'))
        if not start_time or not item.get('id'):
            continue
        normalized = dict(item)
        normalized['start_time'] = start_time
        normalized['end_time'] = _format_datetime_value(item.get('end_time'))
        for index, existing in enumerate(merged):
            if _same_task_marker(existing, normalized):
                merged[index] = _merge_task_marker(existing, normalized)
                break
        else:
            merged.append(normalized)
    return merged


def _load_task_start_markers(hours=CPU_TIMELINE_HOURS):
    since = datetime.datetime.now() - datetime.timedelta(hours=hours)
    markers = []
    try:
        with GaussDB() as db:
            try:
                rows = db.execute_query_sql(
                    """
                    SELECT pid, taskname, state, start_time, end_time, group_name, folder_name
                    FROM wfs_run_history
                    WHERE start_time >= ?
                    ORDER BY start_time ASC
                    LIMIT 1000
                    """,
                    return_json=True,
                    params=(since,),
                )
            except Exception as err:
                if 'group_name' not in str(err).lower() and 'folder_name' not in str(err).lower():
                    raise
                rows = db.execute_query_sql(
                    """
                    SELECT pid, taskname, state, start_time, end_time, '' AS group_name, '' AS folder_name
                    FROM wfs_run_history
                    WHERE start_time >= ?
                    ORDER BY start_time ASC
                    LIMIT 1000
                    """,
                    return_json=True,
                    params=(since,),
                )
        for row in rows:
            markers.append({
                'id': row.get('pid'),
                'name': row.get('taskname') or row.get('pid'),
                'state': row.get('state'),
                'group_name': row.get('group_name') or '',
                'folder_name': row.get('folder_name') or '',
                'start_time': _format_datetime_value(row.get('start_time')),
                'end_time': _format_datetime_value(row.get('end_time')),
                'source': 'history',
            })
    except Exception:
        markers = []

    return sorted(
        _dedupe_task_markers(markers + recent_task_starts(since)),
        key=lambda item: _parse_datetime_value(item.get('start_time')) or datetime.datetime.min,
    )


def _log_content(value):
    if value in (None, ''):
        return ' '
    return str(value)


def _latest_log_marker():
    try:
        with GaussDB() as db:
            rows = db.execute_query_sql(
                "SELECT end_time,id FROM wfs_run_history ORDER BY end_time DESC,id DESC LIMIT 1",
                return_json=False,
            )
            if not rows:
                return {'latest_end_time': '', 'count': 0}
            count = db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history WHERE end_time=?', params=(rows[0][0],))[0][0]
        return {
            'latest_end_time': str(rows[0][0] or ''),
            'latest_id': rows[0][1],
            'count': int(count),
        }
    except Exception as exc:
        return {'latest_end_time': '', 'count': 0, 'error': str(exc)}


def _event_snapshot():
    specs = discover_task_specs(TASK_DIR)
    tasks = []
    for spec in specs:
        pid = spec.get('pid') or spec.get('folder_name')
        state = spec.get('raw_start', 'false')
        next_run_time = ''
        if spec.get('error'):
            state = 'invalid'
        elif spec.get('main_file_error'):
            state = 'invalid'
        elif pid in ignores:
            state = 'pause'
        else:
            job = scheduler.get_job(pid)
            if job:
                state = 'true'
                next_run_time = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else ''
            else:
                state = 'false'
        tasks.append({
            'id': pid,
            'state': state,
            'pending': runnings.is_running(pid),
            'running_instances': runnings.count(pid),
            'max_instances': spec.get('max_instances') or 1,
            'next_run_time': next_run_time,
            'schedule_configured': spec.get('schedule_configured'),
            'schedule_enabled': spec.get('schedule_enabled'),
        })
    return {
        'server_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'tasks': sorted(tasks, key=lambda item: item['id'] or ''),
        'logs': _latest_log_marker(),
        'scheduler': {
            'enabled': WFS_ENABLE_SCHEDULER,
            'job_count': len(scheduler.get_jobs()) if WFS_ENABLE_SCHEDULER else 0,
        },
    }


class Events(Resource):
    def get(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/events')
        try:
            return success_msg(_event_snapshot())
        except Exception as exc:
            return error_msg(str(exc)), 503


class Dashboard(Resource):
    def get(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/dashboard')

        specs = discover_task_specs(TASK_DIR)
        job_stats = _load_job_stats()
        counters = {
            'total': len(specs),
            'running': 0,
            'pending': 0,
            'paused': 0,
            'stopped': 0,
            'invalid': 0,
            'failed_jobs': 0,
        }

        for spec in specs:
            pid = spec.get('pid') or spec.get('folder_name')
            if spec.get('error') or spec.get('main_file_error'):
                counters['invalid'] += 1
                continue
            if pid in ignores:
                counters['paused'] += 1
            elif scheduler.get_job(pid):
                counters['running'] += 1
            else:
                counters['stopped'] += 1
            if runnings.is_running(pid):
                counters['pending'] += 1
            if is_failure((job_stats.get(pid) or {}).get('last_status')):
                counters['failed_jobs'] += 1

        recent = _load_recent_run_stats()
        cpu_metrics = cpu_monitor_snapshot(hours=CPU_TIMELINE_HOURS, after=request.args.get('after','')[:19])
        data = {
            'scheduler': {
                'enabled': WFS_ENABLE_SCHEDULER,
                'control_url': WFS_SCHEDULER_CONTROL_URL,
                'job_count': len(scheduler.get_jobs()) if WFS_ENABLE_SCHEDULER else 0,
            },
            'summary': counters,
            'trend': recent['trend'],
            'failure_rank': recent['failure_rank'],
            'recent_runs': recent['recent_runs'],
            'cpu_timeline': {
                'samples': cpu_metrics['samples'],
                'cursor': cpu_metrics['cursor'],
                'incremental': cpu_metrics['incremental'],
                'markers': _load_task_start_markers(CPU_TIMELINE_HOURS),
                'current': cpu_metrics['current'],
                'current_memory': cpu_metrics['current_memory'],
                'sample_interval_seconds': cpu_metrics['sample_interval_seconds'],
                'retention_hours': cpu_metrics['retention_hours'],
                'warning': cpu_metrics['warning'],
            },
            'warning': recent['error'],
        }
        return success_msg(data)


class State(Resource):
    def get(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/state')

        current_page, pagesize = _get_page_args()
        taskgroup = request.args.get("taskgroup")
        taskname = request.args.get("taskname")
        taskid = request.args.get("taskid")
        owner = request.args.get("owner")
        selected_ids = set(request.args.getlist("ids[]"))

        state_list = []
        job_stats = _load_job_stats()
        with GaussDB() as db:
            applications = {row['pid']: row for row in db.execute_query_sql('SELECT pid,version,status,message FROM wfs_config_application', return_json=True)}
        for spec in discover_task_specs(TASK_DIR):
            if taskgroup and taskgroup != spec.get('group_name'):
                continue

            display_name = spec.get('task_name') or spec.get('folder_name')
            display_pid = spec.get('pid') or spec.get('folder_name')
            if taskname and taskname not in display_name:
                continue
            if taskid and taskid not in display_pid:
                continue

            if selected_ids and display_pid not in selected_ids:
                continue
            if owner and owner.lower() not in str((spec.get('schedule_form') or {}).get('owner','')).lower():
                continue
            stats = job_stats.get(display_pid) or {}
            task_state = {
                'id': display_pid,
                'name': display_name,
                'dirname': spec.get('dir_name'),
                'group_name': spec.get('group_name') or stats.get('group_name') or '',
                'folder_name': spec.get('folder_name') or stats.get('folder_name') or '',
                'main_file': spec.get('main_file') or '',
                'schedule_configured': bool(spec.get('schedule_configured')),
                'schedule_enabled': bool(spec.get('schedule_enabled')),
                'pending': False,
                'state': spec.get('raw_start', 'false'),
                'last_status': stats.get('last_status'),
                'failed_times': stats.get('failed_times') or 0,
                'last_sms_alarm': str(stats.get('last_sms_alarm') or ''),
                'max_instances': spec.get('max_instances') or 1,
                'running_instances': runnings.count(display_pid),
                'total_failures': stats.get('total_failures') or 0,
                'owner': (spec.get('schedule_form') or {}).get('owner',''),
                'application': applications.get(display_pid,{}),
            }

            if spec.get('error') or spec.get('main_file_error'):
                task_state['state'] = 'invalid'
                task_state['config_error'] = spec.get('error') or spec.get('main_file_error')
                task_state['group_name'] = spec.get('group_name') or ''
                task_state['folder_name'] = spec.get('folder_name') or ''
            else:
                pid = spec.get('pid')
                job = scheduler.get_job(pid)
                if job:
                    task_state['state'] = 'true'
                    task_state['next_run_time'] = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    task_state['state'] = 'false'
                task_state['pending'] = runnings.is_running(pid)
                if pid in ignores:
                    task_state['state'] = 'pause'
            status_filter = request.args.get('status')
            if status_filter == 'active' and not task_state['pending']:
                continue
            if status_filter == 'failed' and not is_failure(task_state['last_status']):
                continue
            if status_filter == 'invalid' and task_state['state'] != 'invalid':
                continue
            if status_filter == 'enabled' and task_state['state'] != 'true':
                continue
            state_list.append(task_state)

        start = (current_page - 1) * pagesize
        data = {
            'items': state_list[start:start + pagesize],
            'total': len(state_list),
        }
        return success_msg(data)


class Schedule(Resource):
    def get(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/schedule')

        pid = request.args.get('pid')
        if not pid:
            return error_msg('missing task pid')
        try:
            return success_msg(load_schedule(pid))
        except Exception as exc:
            return error_msg(str(exc))

    def post(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/schedule')

        payload = request.get_json(silent=True) or {}
        try:
            return success_msg({
                'preview': preview_schedule(form=payload),
            })
        except Exception as exc:
            return error_msg(str(exc))

    def put(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/schedule')

        payload = request.get_json(silent=True) or {}
        pid = payload.get('pid') or request.args.get('pid')
        if not pid:
            return error_msg('missing task pid')
        try:
            payload['updated_by'] = g.identity['username']
            if 'version' not in payload:
                return error_msg('缺少配置版本，请重新打开配置。'), 409
            data = save_schedule(pid, payload)
            if data.get('pid') != pid:
                return error_msg('schedule save pid mismatch: request {}, response {}'.format(pid, data.get('pid')))
            from app.api.operations import _apply
            return success_msg(_apply(pid, data))
        except Exception as exc:
            return error_msg(str(exc))


class Action(Resource):
    def post(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/editTask')

        req_data = request.args
        pid = req_data.get('id')
        state = req_data.get('state')
        try:
            spec = resolve_task_spec(pid=pid)
            pid = spec.get('pid')
            if state == "pause":
                set_schedule_enabled(pid, False, actor=g.identity['username'])
                ignores.add(pid)
                if scheduler.get_job(pid):
                    scheduler.remove_job(pid)
                msg = 'task paused'
            elif state == "kill":
                set_schedule_enabled(pid, False, actor=g.identity['username'])
                ignores.add(pid)
                if scheduler.get_job(pid):
                    scheduler.remove_job(pid)
                self.kill(pid)
                msg = 'task stopped'
            elif state == "start":
                set_schedule_enabled(pid, True, actor=g.identity['username'])
                ignores.remove(pid)
                aps_start(task_pid=pid, action='start')
                msg = 'task started'
            elif state == 'refresh':
                ignores.remove(pid)
                aps_start(task_pid=pid, action='refresh')
                msg = 'task refreshed'
            else:
                return error_msg('unsupported state action')
            from app.bootstrap.schedule_config import record_application
            saved = load_schedule(pid)
            record_application(pid, saved.get('version',0), 'applied')
            return success_msg(msg)
        except Exception as exc:
            if pid and state in ('start', 'refresh'):
                from app.bootstrap.schedule_config import record_application
                saved = load_schedule(pid)
                record_application(pid, saved.get('version',0), 'failed', str(exc))
            return error_msg(str(exc))

    def kill(self, pid):
        for process_id in runnings.cancel(pid):
            kill_process(process_id)


class TaskLogs(Resource):
    def todict(self, data):
        return {
            "logid": data[0],
            "id": data[1],
            "name": data[2],
            "dirname": data[3],
            "group_name": data[4],
            "folder_name": data[5],
            "state": data[6],
            "datetime": f"{data[7]}",
            "starttime": f"{data[8]}",
            "times": f"{data[9]}",
        }

    def post(self):
        current_page, pagesize = _get_page_args()
        pid = request.args.get("taskid")
        taskstate = request.args.get("taskstate")
        datetimeval = request.args.getlist("datetimeval[]")
        try:
            from app.bootstrap.history import date_range, page
            dates = date_range(datetimeval)
            scope = request.args.get('scope', 'online')
            cursor = request.args.get('cursor', '')
            if current_page > 1 and not cursor:
                raise ValueError('请通过下一页继续查询，或重新搜索。')
            clauses, params = _build_task_log_filters(pid=pid, taskstate=taskstate, datetimeval=dates)
            val, has_more, next_cursor = page(clauses, params, pagesize, scope, cursor, [pid,taskstate,dates,scope,pagesize])
            data = {
                "total": _approx_total(current_page, pagesize, len(val), has_more),
                "has_more": has_more,
                "total_exact": False,
                "next_cursor": next_cursor,
                "date_range": [str(value) for value in dates],
                "data": list(map(self.todict, val)),
            }
            return success_msg(data)
        except ValueError as err:
            return error_msg(str(err)), 400
        except Exception as err:
            return error_msg(str(err))


class SystemLogs(Resource):
    def todict(self, data):
        return {
            "id": data[0],
            "name": data[1],
            "systeminfo": data[2],
            "datetime": f"{data[3]}",
        }

    def post(self):
        current_page, pagesize = _get_page_args()
        systemids = request.args.get("systemids")
        datetimeval = request.args.getlist("datetimeval[]")
        try:
            clauses, params = _build_system_log_filters(systemids=systemids, datetimeval=datetimeval)
            where_sql = ''
            if clauses:
                where_sql = ' AND ' + ' AND '.join(clauses)

            sql = '''SELECT pid, taskname, system_info, datetime_info
FROM wfs_schedule_history
WHERE 1=1{} ORDER BY datetime_info DESC LIMIT ? OFFSET ?'''.format(where_sql)
            limit = pagesize + 1
            offset = (current_page - 1) * pagesize
            with GaussDB() as db:
                rows = db.execute_query_sql(sql=sql, return_json=False, params=tuple(params + [limit, offset]))
            has_more = len(rows) > pagesize
            val = rows[:pagesize]
            data = {
                "total": _approx_total(current_page, pagesize, len(val), has_more),
                "has_more": has_more,
                "total_exact": False,
                "data": list(map(self.todict, val)),
            }
            return success_msg(data)
        except Exception as err:
            return error_msg(str(err))


class TaskIds(Resource):
    def post(self):
        return success_msg(_task_id_options())


class Groups(Resource):
    def post(self):
        groups = sorted({spec.get('group_name') for spec in discover_task_specs(TASK_DIR)})
        return success_msg(groups)


class SystemIds(Resource):
    def post(self):
        return success_msg(_task_id_options())


class Reload(Resource):
    def post(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/overloading')

        refresh = request.args.get("refresh")
        if refresh:
            try:
                for job in scheduler.get_jobs():
                    if not str(job.id).startswith('manual_'):
                        scheduler.remove_job(job.id)
                aps_start()
            except Exception as exc:
                return error_msg('tasks reload failed: ' + str(exc))
            return success_msg('tasks reloaded')

        try:
            aps_start()
        except Exception as exc:
            return error_msg('tasks reload failed: ' + str(exc))
        return success_msg('new tasks loaded')


class Code(Resource):
    def post(self):
        try:
            ok, message = _update_code_to_configured_branch()
            if ok:
                return success_msg(message)
            return error_msg('检查更新失败：' + message)
        except Exception as exp:
            return error_msg('code update exception: ' + str(exp))


class DetailLog(Resource):
    def post(self):
        try:
            pid = request.args.get('id')
            sql = "SELECT tasklog FROM wfs_run_history where pid=? order by end_time desc limit 1"
            with GaussDB() as db:
                res = db.execute_query_sql(sql=sql, return_json=False, params=(pid,))
        except Exception as exc:
            return error_msg('log read failed: ' + str(exc))
        return success_msg(_log_content(res[0][0]) if res else ' ')


class TaskLogDetail(Resource):
    def post(self):
        try:
            log_id = request.args.get('id')
            end_time = request.args.get('end_time')
            pid = request.args.get('pid')
            if log_id and end_time:
                sql = "SELECT tasklog FROM wfs_run_history WHERE id=? AND end_time=? LIMIT 1"
                with GaussDB() as db:
                    res = db.execute_query_sql(sql=sql, return_json=False, params=(log_id, end_time))
                    if not res:
                        res = db.execute_query_sql(sql=sql.replace('wfs_run_history', 'wfs_run_history_archive'), return_json=False, params=(log_id,end_time))
            elif pid:
                sql = "SELECT tasklog FROM wfs_run_history WHERE pid=? ORDER BY end_time DESC LIMIT 1"
                with GaussDB() as db:
                    res = db.execute_query_sql(sql=sql, return_json=False, params=(pid,))
            else:
                return error_msg('missing log id')
        except Exception as exc:
            return error_msg('log read failed: ' + str(exc))
        return success_msg(_log_content(res[0][0]) if res else ' ')


class CallTask(Resource):
    def post(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/call_task')

        try:
            pid = request.args.get('pid')
            if not pid:
                return error_msg('missing task pid')
            run_id = call_task_once(pid, actor=g.identity['username'])
        except Exception as exc:
            return error_msg('Task call failed: ' + str(exc))
        return success_msg({'message':'任务已排队', 'run_id':run_id})
