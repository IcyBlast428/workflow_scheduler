# -*- coding=utf-8 -*-
import datetime
import logging
import os
import random
import re
import threading
from functools import wraps

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED, EVENT_JOB_MAX_INSTANCES
from configobj import ConfigObj

from app.bootstrap.global_vars import runnings, TASK_DIR, uuidhex, ignores,CONFIG_DIR
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.schedule_config import SCHEDULER_TZ, apply_persisted_schedule, build_scheduler_trigger, record_application
from app.extensions import scheduler
from app.bootstrap.execution import execute_py, kill_process
from app.bootstrap.database import GaussDB
from app.settings import FLASK_ENV
from app.bootstrap.operations import create_run, update_run, now, start_operations, mark_ready, audit
from app.bootstrap.operations import save_history
from app.bootstrap.execution_state import SKIPPED, MISSED

if FLASK_ENV == 'development':
    dev_ini = os.path.join(CONFIG_DIR, 'development.ini')
    config_base = ConfigObj(dev_ini, encoding='utf-8')
    dev_run_job = config_base.get('dev_run_job') or {}
    dev_run_job_pid = dev_run_job.get('pid')
    dev_run_all = dev_run_job.get('run_all')


# 项目重启时 interval 任务可能同时进入下一次运行，这里只给首轮注册加内存态错峰。
INTERVAL_START_STAGGER_MAX_SECONDS = 300
_manual_reservations = {}
_manual_lock = threading.Lock()
_configuration_lock = threading.RLock()


def serialized_configuration(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _configuration_lock:
            return function(*args, **kwargs)
    return wrapped


def execute_manual(*args, manual_job_id, run_id=None, limits=None, scheduled_time=None):
    with _manual_lock:
        _manual_reservations.pop(manual_job_id, None)
    return execute_py(*args, run_id=run_id, limits=limits,scheduled_time=scheduled_time)


def getReceiverList(receiver_str, send_type, connection) -> list:
    import pandas as pd
    cnname_list = []
    grpname_list = []
    individual_receiver_list = []
    group_receiver_list = []
    for match in re.finditer(r"(?P<cnname>[\u4e00-\u9fff]+)|(?P<grpname>[\w+]+)", receiver_str):
        if cnname := match.group("cnname"):
            cnname_list.append(cnname)
        if grpname := match.group("grpname"):
            grpname_list.append(grpname)
    if len(cnname_list) != 0:
        individual_formatted_clause = '\'' + '\',\''.join(cnname_list) + '\''
        individual_receiver_df = pd.read_sql_query(f"select {send_type} from immp_cfg_user_mail_sms where cnname in ({individual_formatted_clause});", connection)
        individual_receiver_list = individual_receiver_df[send_type].tolist()
    if len(grpname_list) != 0:
        group_formatted_clause = ' or '.join(["is_" + grpname + " = 1" for grpname in grpname_list])
        group_receiver_df = pd.read_sql_query(f"select {send_type} from immp_cfg_user_mail_sms where {group_formatted_clause};", con = connection)
        group_receiver_list = group_receiver_df[send_type].tolist()
    receiver_list = list(set(individual_receiver_list + group_receiver_list)) # list去重
    return receiver_list


# 监听系统日志
def my_listener(event):
    # 获取错误码
    warning_code = event.code
    # 任务id  pid
    job_id = event.job_id
    with _manual_lock:
        pending = _manual_reservations.pop(job_id, None)
    if pending is not None:
        reservation, run_id = pending
        runnings.remove(reservation)
        result = update_run(run_id, status='missed', state=MISSED, end_time=now(), reason='手动执行错过调度窗口，未启动。')
        save_history(result)
    # 报警信息
    warning_log = ""
    # 获取队列中的任务
    job = scheduler.get_job(job_id)
    job_name = job.name if job else job_id
    # 进程阻塞
    if warning_code == EVENT_JOB_MAX_INSTANCES:
        next_run_time = event.scheduled_run_times
        if next_run_time:
            warning_log = r'''Execution of job:{} next run at:{} CST skipped: maximum number of running instances 
            reached\n一般是由于运行所需的时间大于周期造成阻塞导致的问题,可以在配置文件中增加最大线程数MAX_INSTANCES'''.format(
                job_id, next_run_time[0])
    elif warning_code == EVENT_JOB_MISSED:
        warning_log = "APScheduler EVENT_JOB_MISSED"
    elif warning_code == EVENT_JOB_ERROR:
        warning_log = "APScheduler EVENT_JOB_ERROR"
    else:
        warning_log = "APScheduler报错码:{}".format(warning_code)

    if pending is None and warning_code in (EVENT_JOB_MAX_INSTANCES,EVENT_JOB_MISSED):
        times = getattr(event,'scheduled_run_times',None) or [getattr(event,'scheduled_run_time',None)]
        spec = next((spec for spec in discover_task_specs() if spec['pid']==job_id),None)
        if spec:
            for planned in times:
                run_id = create_run(job_id,job_name,group_name=spec['group_name'],folder_name=spec['folder_name'],dir_name=spec['dir_name'],
                                    scheduled_time=planned.astimezone().replace(tzinfo=None).isoformat(' ') if planned else '')
                skipped = warning_code==EVENT_JOB_MAX_INSTANCES
                record = update_run(run_id,status='skipped' if skipped else 'missed',state=SKIPPED if skipped else MISSED,end_time=now(),
                                    reason='此任务的并发名额已满，本次调度跳过。' if skipped else '错过允许的调度窗口，本次未执行。')
                save_history(record)

    sql = '''INSERT INTO wfs_schedule_history(id,pid,taskname,system_info,datetime_info)
             VALUES (?,?,?,?,?)'''
    with GaussDB() as db:
        db.execute_sql(
            sql = sql,
            params=(
                uuidhex(),
                job_id,
                job_name,
                warning_log,
                datetime.datetime.now(),
            )
        )


def parse_rules(rules, trigger=None):
    '''
    调度规则
    :param rules: ->config.ini配置文件规则: {'SECONDS': '10', 'MINUTES': '0', 'HOURS': '0', 'DAYS': '0', 'WEEKS': '0', 'START_DATE': '0'}
    :return: ->已配置的项{'seconds': 10}
    '''
    new_rules = {}
    for k, v in rules.items():
        config_name = k.lower()
        if v in ('', None):
            continue
        if trigger != 'cron' and v in ('0', 0):
            continue
        if v in ('last', 'LAST'):
            new_rules[config_name] = v.lower()
        else:
            try:
                new_rules[config_name] = int(v)
            except ValueError:
                if 'date' in config_name:
                    configtime = datetime.datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
                    if configtime < datetime.datetime.now():
                        raise Exception('开始日期必须大于当前时间')
                new_rules[config_name] = v
    return new_rules


def _remove_scheduler_job(pid):
    if pid and scheduler.get_job(pid):
        scheduler.remove_job(pid)


def _ensure_listener_registered():
    try:
        scheduler.remove_listener(my_listener)
    except Exception:
        pass
    scheduler.add_listener(my_listener, EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES)


def _should_process_in_dev(pid):
    if os.environ.get('WFS_DEV_RUN_ALL', '').lower() in {'1', 'true', 'yes'}:
        return True
    if FLASK_ENV != 'development' or dev_run_all != 'false':
        return True
    if isinstance(dev_run_job_pid, list):
        return pid in dev_run_job_pid
    if isinstance(dev_run_job_pid, str):
        return pid == dev_run_job_pid
    return True


def _sync_job_stats(job_list, prune_missing=True):
    with GaussDB() as db:
        existing = {row[0] for row in db.execute_query_sql('SELECT pid FROM wfs_job_stats')}
        current = {row[0] for row in job_list}
        db.begin_transaction()
        try:
            if prune_missing:
                for pid in existing - current:
                    db.execute_sql('DELETE FROM wfs_job_stats WHERE pid=?', params=(pid,))
            for pid, group, folder, name, enabled in job_list:
                if pid in existing:
                    db.execute_sql('UPDATE wfs_job_stats SET group_name=?,folder_name=?,task_name=?,scheduling_stat=? WHERE pid=?', params=(group,folder,name,enabled,pid))
                else:
                    db.execute_sql('INSERT INTO wfs_job_stats(pid,group_name,folder_name,task_name,scheduling_stat,failed_times) VALUES(?,?,?,?,?,0)', params=(pid,group,folder,name,enabled))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise

def call_task_once(pid, actor='admin'):
    for spec in discover_task_specs(TASK_DIR):
        if spec.get('pid') != pid:
            continue
        if spec.get('error'):
            raise ValueError('invalid task config for {}: {}'.format(pid, spec.get('error')))
        if spec.get('main_file_error'):
            raise ValueError('task entry file is invalid for {}: {}'.format(pid, spec.get('main_file_error')))
        reservation = runnings.claim(pid, spec.get('max_instances') or 1)
        if reservation is None:
            raise ValueError('task concurrency limit reached')
        manual_job_id = 'manual_{}_{}'.format(pid, uuidhex())
        try:
            run_id = create_run(pid, spec.get('task_name') or spec.get('folder_name'), source='manual', actor=actor,
                                dir_name=spec.get('dir_name'), group_name=spec.get('group_name'), folder_name=spec.get('folder_name'))
        except Exception:
            runnings.remove(reservation)
            raise
        with _manual_lock:
            _manual_reservations[manual_job_id] = (reservation, run_id)
        try:
            scheduler.add_job(
                func=execute_manual,
                trigger='date',
                run_date=datetime.datetime.now(),
                args=[
                    str(spec.get('main_file_path')),
                    pid,
                    spec.get('task_name'),
                    spec.get('dir_name'),
                    spec.get('timeout_seconds') or 0,
                    spec.get('group_name') or '',
                    spec.get('folder_name') or '',
                    spec.get('python_executable') or '',
                    spec.get('max_instances') or 1,
                    reservation,
                ],
                id=manual_job_id,
                kwargs={'manual_job_id': manual_job_id, 'run_id': run_id, 'limits': spec.get('schedule_form') or {}},
                name='Manual run: {}'.format(spec.get('task_name') or pid),
                replace_existing=False,
                max_instances=1,
                misfire_grace_time=60,
            )
        except Exception:
            with _manual_lock:
                _manual_reservations.pop(manual_job_id, None)
            runnings.remove(reservation)
            update_run(run_id, status='interrupted', state=-1, end_time=now(), reason='Could not enqueue execution.')
            raise
        return run_id
    raise ValueError('task not found: {}'.format(pid))


def _rule_int(rules, key):
    try:
        return int((rules or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _interval_seconds(rules):
    return (
        _rule_int(rules, 'WEEKS') * 7 * 24 * 60 * 60
        + _rule_int(rules, 'DAYS') * 24 * 60 * 60
        + _rule_int(rules, 'HOURS') * 60 * 60
        + _rule_int(rules, 'MINUTES') * 60
        + _rule_int(rules, 'SECONDS')
    )


def _stagger_interval_rules(pid, rules, enabled=True):
    if not enabled:
        return rules
    if (rules or {}).get('START_DATE'):
        return rules

    seconds = _interval_seconds(rules)
    if seconds <= 1:
        return rules

    max_offset = min(seconds - 1, INTERVAL_START_STAGGER_MAX_SECONDS)
    offset = random.randint(0, max_offset)
    if offset <= 0:
        return rules

    next_rules = dict(rules or {})
    # 只改本次注册用的 trigger 参数，不回写数据库，因此不会改变用户配置的调度策略。
    next_rules['START_DATE'] = datetime.datetime.now(SCHEDULER_TZ) + datetime.timedelta(seconds=offset)
    logging.getLogger(__name__).info('stagger interval job %s by %s seconds after scheduler bootstrap', pid, offset)
    return next_rules


@serialized_configuration
def aps_start(task_pid=None, action='refresh'):
    """
    扫描任务目录、合并数据库配置，并把可运行任务注册到 APScheduler。
    :param task_pid: 全任务扫描为 None，否则只处理指定 PID
    :param action: refresh/start/reload 等任务控制动作
    """
    if task_pid is None:
        start_operations()
        from app.bootstrap.system_metrics import cpu_monitor_snapshot
        cpu_monitor_snapshot()
    from app.bootstrap.task_loader import invalidate_task_cache
    invalidate_task_cache()
    job_list = []
    matched_target = task_pid is None
    discovered_pids = set()

    logging.getLogger(__name__).info('begin to run aps_start pid={} action={}'.format(task_pid, action))
    for spec in discover_task_specs(TASK_DIR):
        pid = spec.get('pid')
        if pid:
            discovered_pids.add(pid)

        if task_pid and pid != task_pid:
            continue
        if task_pid and pid == task_pid:
            matched_target = True
            _remove_scheduler_job(pid)

        if not pid:
            continue
        if task_pid is None and not _should_process_in_dev(pid):
            continue

        if spec.get('error'):
            message = 'invalid task config for {}: {}'.format(pid, spec.get('error'))
            logging.getLogger(__name__).warning(message)
            _remove_scheduler_job(pid)
            if spec.get('config_record'):
                record_application(pid, spec['config_record'].get('version',1), 'failed', message)
            if task_pid == pid:
                raise ValueError(message)
            continue

        # 读取前端持久化的调度策略，覆盖任务目录中的默认推断。
        spec = apply_persisted_schedule(spec)
        version = (spec.get('config_record') or {}).get('version',0)
        if spec.get('schedule_enabled') and pid in ignores:
            ignores.remove(pid)

        job_list.append([
            pid,
            spec.get('group_name'),
            spec.get('folder_name'),
            spec.get('task_name'),
            spec.get('raw_start', 'false'),
        ])

        if pid in ignores:
            _remove_scheduler_job(pid)
            if spec.get('schedule_configured'):
                record_application(pid, version, 'applied')
            continue

        if spec.get('main_file_error'):
            logging.getLogger(__name__).warning('invalid task entry for %s: %s', pid, spec.get('main_file_error'))
            _remove_scheduler_job(pid)
            record_application(pid, version, 'failed', spec.get('main_file_error'))
            if task_pid == pid:
                raise ValueError('task entry file is invalid for {}: {}'.format(pid, spec.get('main_file_error')))
            continue

        if not spec.get('schedule_configured'):
            _remove_scheduler_job(pid)
            if task_pid == pid and action == 'start':
                raise ValueError('task {} has no schedule strategy yet'.format(pid))
            continue

        should_start = spec.get('start_enabled') or action == 'start'
        if not should_start:
            _remove_scheduler_job(pid)
            record_application(pid, version, 'applied')
            continue
        if scheduler.get_job(pid):
            record_application(pid, version, 'applied')
            continue

        try:
            raw_rules = spec.get('schedule_rules')
            if raw_rules is None:
                raw_rules = {}
            # 仅全量启动时对 interval 任务错峰，单个任务手动启动不额外延迟。
            raw_rules = _stagger_interval_rules(
                pid,
                raw_rules,
                enabled=(task_pid is None and spec.get('trigger') == 'interval'),
            )
            trigger = build_scheduler_trigger(spec.get('trigger'), raw_rules)
            scheduler.add_job(
                func=execute_py,
                trigger=trigger,
                args=[
                    str(spec.get('main_file_path')),
                    pid,
                    spec.get('task_name'),
                    spec.get('dir_name'),
                    spec.get('timeout_seconds') or 0,
                    spec.get('group_name') or '',
                    spec.get('folder_name') or '',
                    spec.get('python_executable') or '',
                    spec.get('max_instances') or 1,
                ],
                name=spec.get('task_name') or pid,
                kwargs={'limits': spec.get('schedule_form') or {}},
                replace_existing=True,
                max_instances=spec.get('max_instances') or 1,
                coalesce=True,
                id=pid,
                misfire_grace_time=int((spec.get('schedule_form') or {}).get('misfire_grace_seconds', 600)),
            )
            scheduler.resume_job(pid)
            record_application(pid, version, 'applied')
        except Exception as exc:
            logging.getLogger(__name__).warning('failed to register job %s: %s', pid, exc)
            _remove_scheduler_job(pid)
            record_application(pid, version, 'failed', str(exc))
            if task_pid == pid:
                raise

    if task_pid and not matched_target:
        raise ValueError('task not found: {}'.format(task_pid))

    if task_pid is None:
        for job in scheduler.get_jobs():
            if str(job.id).startswith('manual_'):
                continue
            if job.id not in discovered_pids:
                scheduler.remove_job(job.id)

    _ensure_listener_registered()
    logging.getLogger(__name__).info("lens(job_list):" + str(len(job_list)))
    # 单任务刷新只同步当前 PID，不能用局部 job_list 删除其他任务的统计行。
    _sync_job_stats(job_list, prune_missing=(task_pid is None))
    if task_pid is None:
        mark_ready()
    logging.getLogger(__name__).info('end to run aps_start pid={} action={}'.format(task_pid, action))
