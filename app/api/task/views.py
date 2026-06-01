import os
import subprocess
import datetime
import hashlib
import json
import time
from urllib.parse import urljoin

import requests
from flask import Response, request, stream_with_context
from flask_restful import Resource

from app.bootstrap.core import aps_start, call_task_once, kill_process
from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import TASK_DIR, error_msg, ignores, runnings, success_msg
from app.bootstrap.schedule_config import load_schedule, preview_schedule, save_schedule, set_schedule_enabled
from app.bootstrap.system_metrics import cpu_monitor_snapshot, recent_task_starts
from app.bootstrap.task_loader import discover_task_specs
from app.extensions import scheduler
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
        clauses.append("state <> 0")
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


def _proxy_scheduler_resource(resource_path):
    url = urljoin(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/', resource_path.lstrip('/'))
    headers = {}
    token = request.headers.get('X-Token')
    if token:
        headers['X-Token'] = token
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
    headers = {}
    token = request.headers.get('X-Token') or request.args.get('token')
    if token:
        headers['X-Token'] = token
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
    stdout, stderr = proc.communicate()
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')
    return proc.returncode, output, error_output


def _update_code_to_configured_branch():
    """把生产工作树切到配置的远端分支，避免把当前分支内容混进部署目录。"""
    target_ref = '{}/{}'.format(CODE_UPDATE_REMOTE, CODE_UPDATE_BRANCH)
    fetch_refspec = '+refs/heads/{}:refs/remotes/{}'.format(CODE_UPDATE_BRANCH, target_ref)
    commands = [
        ['fetch', '--prune', CODE_UPDATE_REMOTE, fetch_refspec],
        ['checkout', '-B', CODE_UPDATE_BRANCH, target_ref],
        ['reset', '--hard', target_ref],
    ]
    outputs = [
        'target branch: {}'.format(target_ref),
        'repo path: {}'.format(CODE_UPDATE_PATH),
    ]
    for command in commands:
        returncode, stdout, stderr = _run_git_command(command)
        outputs.append('$ git {}'.format(' '.join(command)))
        if stdout:
            outputs.append(stdout.rstrip())
        if stderr:
            outputs.append(stderr.rstrip())
        if returncode != 0:
            return False, '\n'.join(outputs)
    return True, '\n'.join(outputs)


def _load_job_stats():
    try:
        with GaussDB() as db:
            rows = db.execute_query_sql(
                """
                SELECT pid, group_name, folder_name, last_status, failed_times, last_sms_alarm
                FROM wfs_job_stats
                """,
                return_json=True,
            )
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
    trend = _empty_dashboard_trend()
    trend_by_hour = {item['hour']: item for item in trend}
    failures = {}
    recent_runs = []
    since = datetime.datetime.now() - datetime.timedelta(hours=RECENT_HOURS)
    try:
        with GaussDB() as db:
            try:
                rows = db.execute_query_sql(
                    """
                    SELECT pid, taskname, state, start_time, end_time, group_name, folder_name
                    FROM wfs_run_history
                    WHERE end_time >= ?
                    ORDER BY end_time DESC
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
                    WHERE end_time >= ?
                    ORDER BY end_time DESC
                    LIMIT 1000
                    """,
                    return_json=True,
                    params=(since,),
                )
    except Exception as exc:
        return {
            'trend': trend,
            'failure_rank': [],
            'recent_runs': [],
            'error': str(exc),
        }

    for row in rows:
        end_time = row.get('end_time')
        if hasattr(end_time, 'strftime'):
            hour_key = end_time.replace(minute=0, second=0, microsecond=0).strftime('%m-%d %H:00')
        else:
            hour_key = str(end_time)[:13] + ':00'
        if hour_key in trend_by_hour:
            if row.get('state') == 0:
                trend_by_hour[hour_key]['success'] += 1
            else:
                trend_by_hour[hour_key]['failed'] += 1

        if row.get('state') != 0:
            pid = row.get('pid')
            item = failures.setdefault(pid, {
                'id': pid,
                'name': row.get('taskname') or pid,
                'count': 0,
            })
            item['count'] += 1

    for row in rows[:8]:
        recent_runs.append({
            'id': row.get('pid'),
            'name': row.get('taskname') or row.get('pid'),
            'state': row.get('state'),
            'group_name': row.get('group_name') or '',
            'folder_name': row.get('folder_name') or '',
            'start_time': str(row.get('start_time') or ''),
            'end_time': str(row.get('end_time') or ''),
        })

    return {
        'trend': trend,
        'failure_rank': sorted(failures.values(), key=lambda item: item['count'], reverse=True)[:8],
        'recent_runs': recent_runs,
        'error': '',
    }


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

    by_key = {}
    for item in markers + recent_task_starts(since):
        start_time = _format_datetime_value(item.get('start_time'))
        key = '{}|{}'.format(item.get('id') or '', start_time)
        if not start_time or not item.get('id') or key in by_key:
            existing = by_key.get(key)
            if existing and existing.get('end_time'):
                continue
            if existing and not _format_datetime_value(item.get('end_time')):
                continue
        if not start_time or not item.get('id'):
            continue
        normalized = dict(item)
        normalized['start_time'] = start_time
        normalized['end_time'] = _format_datetime_value(item.get('end_time'))
        by_key[key] = normalized

    return sorted(
        by_key.values(),
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
                "SELECT max(end_time), count(*) FROM wfs_run_history",
                return_json=False,
            )
        if not rows:
            return {'latest_end_time': '', 'count': 0}
        return {
            'latest_end_time': str(rows[0][0] or ''),
            'count': int(rows[0][1] or 0),
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


def _sse_headers():
    return {
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'Content-Encoding': 'identity',
        'X-Accel-Buffering': 'no',
    }


def _snapshot_digest(snapshot):
    comparable = dict(snapshot)
    comparable.pop('server_time', None)
    text = json.dumps(comparable, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def _sse_event(event_name, payload):
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return 'event: {}\ndata: {}\n\n'.format(event_name, data)


def _proxy_scheduler_events():
    url = urljoin(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/', 'api/taskinfo/events')
    headers = {}
    token = request.headers.get('X-Token') or request.args.get('token')
    if token:
        headers['X-Token'] = token
    params = dict(request.args)
    params.pop('token', None)

    def generate():
        try:
            with requests.get(url, headers=headers, params=params, stream=True, timeout=(5, None)) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    yield '{}\n'.format(line or '')
        except requests.RequestException as exc:
            yield _sse_event('stream_error', {'message': 'scheduler event stream unavailable: {}'.format(exc)})

    return Response(stream_with_context(generate()), mimetype='text/event-stream', headers=_sse_headers())


class Events(Resource):
    def get(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_events()

        def generate():
            last_digest = ''
            last_heartbeat = 0
            while True:
                try:
                    snapshot = _event_snapshot()
                    digest = _snapshot_digest(snapshot)
                    if digest != last_digest:
                        last_digest = digest
                        snapshot['digest'] = digest
                        yield _sse_event('snapshot', snapshot)
                    elif time.time() - last_heartbeat >= 15:
                        last_heartbeat = time.time()
                        yield ': keepalive {}\n\n'.format(datetime.datetime.now().isoformat())
                    time.sleep(2)
                except GeneratorExit:
                    break
                except Exception as exc:
                    yield _sse_event('stream_error', {'message': str(exc)})
                    time.sleep(5)

        return Response(stream_with_context(generate()), mimetype='text/event-stream', headers=_sse_headers())


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
            if (job_stats.get(pid) or {}).get('last_status') not in (None, 0):
                counters['failed_jobs'] += 1

        recent = _load_recent_run_stats()
        cpu_metrics = cpu_monitor_snapshot(hours=CPU_TIMELINE_HOURS)
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

        state_list = []
        job_stats = _load_job_stats()
        for spec in discover_task_specs(TASK_DIR):
            if taskgroup and taskgroup != spec.get('group_name'):
                continue

            display_name = spec.get('task_name') or spec.get('folder_name')
            display_pid = spec.get('pid') or spec.get('folder_name')
            if taskname and taskname not in display_name:
                continue
            if taskid and taskid not in display_pid:
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
            data = save_schedule(pid, payload)
            aps_start(task_pid=pid, action='refresh')
            return success_msg(data)
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
            if state == "pause":
                ignores.add(pid)
                if scheduler.get_job(pid):
                    scheduler.remove_job(pid)
                set_schedule_enabled(pid, False)
                msg = 'task paused'
            elif state == "kill":
                ignores.add(pid)
                if scheduler.get_job(pid):
                    scheduler.remove_job(pid)
                self.kill(pid)
                set_schedule_enabled(pid, False)
                msg = 'task stopped'
            elif state == "start":
                ignores.remove(pid)
                self.kill(pid)
                set_schedule_enabled(pid, True)
                aps_start(task_pid=pid, action='start')
                msg = 'task started'
            elif state == 'refresh':
                ignores.remove(pid)
                aps_start(task_pid=pid, action='refresh')
                msg = 'task refreshed'
            else:
                return error_msg('unsupported state action')
            return success_msg(msg)
        except Exception as exc:
            return error_msg(str(exc))

    def kill(self, pid):
        process = runnings.get(pid)
        if process:
            cmd_pid = process.get(pid)
            if cmd_pid:
                try:
                    runnings.remove(process)
                    kill_process(cmd_pid)
                except Exception:
                    pass


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
            clauses, params = _build_task_log_filters(pid=pid, taskstate=taskstate, datetimeval=datetimeval)
            where_sql = ''
            if clauses:
                where_sql = ' AND ' + ' AND '.join(clauses)

            sql = '''SELECT id, pid, taskname, dirname, group_name, folder_name,
CASE WHEN state = 0 THEN '成功' ELSE '失败' END state, end_time, start_time, extract(epoch from (end_time - start_time))::bigint times
FROM wfs_run_history
WHERE 1=1{} ORDER BY end_time DESC LIMIT ? OFFSET ?'''.format(where_sql)
            limit = pagesize + 1
            offset = (current_page - 1) * pagesize
            with GaussDB() as db:
                try:
                    rows = db.execute_query_sql(sql=sql, return_json=False, params=tuple(params + [limit, offset]))
                except Exception as err:
                    if 'group_name' not in str(err).lower() and 'folder_name' not in str(err).lower():
                        raise
                    legacy_sql = '''SELECT id, pid, taskname, dirname, '' AS group_name, '' AS folder_name,
CASE WHEN state = 0 THEN '成功' ELSE '失败' END state, end_time, start_time, extract(epoch from (end_time - start_time))::bigint times
FROM wfs_run_history
WHERE 1=1{} ORDER BY end_time DESC LIMIT ? OFFSET ?'''.format(where_sql)
                    rows = db.execute_query_sql(sql=legacy_sql, return_json=False, params=tuple(params + [limit, offset]))
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
                scheduler.remove_all_jobs()
                aps_start()
            except Exception as exc:
                return success_msg('tasks reload warning: ' + str(exc))
            return success_msg('tasks reloaded')

        try:
            aps_start()
        except Exception as exc:
            return success_msg('tasks reload warning: ' + str(exc))
        return success_msg('new tasks loaded')


class Code(Resource):
    def post(self):
        try:
            ok, message = _update_code_to_configured_branch()
            if ok:
                return success_msg('code update succeeded\n' + message)
            return error_msg('code update failed\n' + message)
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
    def get(self):
        if _scheduler_control_enabled():
            return _proxy_scheduler_resource('/api/taskinfo/call_task')

        try:
            pid = request.args.get('pid')
            if not pid:
                return error_msg('missing task pid')
            call_task_once(pid)
        except Exception as exc:
            return error_msg('Task call failed: ' + str(exc))
        return success_msg('Task call succeeded')
