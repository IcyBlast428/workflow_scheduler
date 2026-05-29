# -*- coding=utf-8 -*-
import datetime
import logging
import os
import random
import re
import signal
import subprocess
import sys

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED, EVENT_JOB_MAX_INSTANCES
from configobj import ConfigObj
import pandas as pd
from app.bootstrap.global_vars import runnings, TASK_DIR, uuidhex, ignores,CONFIG_DIR
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.schedule_config import SCHEDULER_TZ, apply_persisted_schedule, build_scheduler_trigger
from app.extensions import scheduler
from app.common.mail import send_mail
from app.common.sms import send_sms
from app.bootstrap.database import GaussDB
from app.settings import FLASK_ENV
from app.bootstrap.system_metrics import record_task_end, record_task_start

if FLASK_ENV == 'development':
    dev_ini = os.path.join(CONFIG_DIR, 'development.ini')
    config_base = ConfigObj(dev_ini, encoding='utf-8')
    dev_run_job = config_base.get('dev_run_job') or {}
    dev_run_job_pid = dev_run_job.get('pid')
    dev_run_all = dev_run_job.get('run_all')


# 项目重启时 interval 任务可能同时进入下一次运行，这里只给首轮注册加内存态错峰。
INTERVAL_START_STAGGER_MAX_SECONDS = 300


def getReceiverList(receiver_str, send_type, connection) -> list:
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


def kill_process(pid):
    if not pid:
        return
    try:
        if os.name == 'nt':
            os.kill(pid, signal.SIGTERM)
        else:
            # Linux 下任务以独立进程组启动，超时或强停时可以一起清理子进程。
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _task_dir_parts(dir_name='', group_name='', folder_name=''):
    if group_name or folder_name:
        return group_name or '', folder_name or ''
    normalized_dir = str(dir_name or '').strip('/')
    if not normalized_dir:
        return '', ''
    parts = normalized_dir.split('/', 1)
    return (parts + [''])[:2]


def execute_py(path, PID, task_name='', dir_name='', timeout_seconds=0, group_name='', folder_name='', python_executable=''):
    '''
    执行py文件 并记录到日志中
    :param task_name:
    :param dir_name:
    :param path: 文件相对路径
    :param PID: task的唯一id
    :return: 执行不返回
    '''
    start_time = datetime.datetime.now()
    event_group_name, event_folder_name = _task_dir_parts(dir_name, group_name, folder_name)
    # 先记录内存中的开始事件，总览页可以立刻看到正在运行的任务色块。
    record_task_start(PID, task_name, event_group_name, event_folder_name, start_time)
    dic = {}
    output = ''
    output_simple = ''
    state = 1
    try:
        popen_kwargs = {}
        if os.name == 'nt':
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs['start_new_session'] = True

        # 每个任务可以使用自己的 .venv；没有独立环境时回退到启动平台的 Python。
        executable = python_executable or sys.executable
        cmd = subprocess.Popen(
            [str(executable), str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **popen_kwargs
        )
        dic[PID] = cmd.pid
        runnings.append(dic)
        try:
            stdout, err = cmd.communicate(timeout=timeout_seconds or None)
        except subprocess.TimeoutExpired:
            # 超时后先温和终止进程组，仍不退出再强制 kill，避免任务残留。
            kill_process(cmd.pid)
            try:
                stdout, err = cmd.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                cmd.kill()
                stdout, err = cmd.communicate()
            state = -9
            output += 'Task exceeded TIMEOUT_SECONDS={} and was terminated.\n'.format(timeout_seconds)
        output += stdout.decode("utf-8", errors="replace")
        output += err.decode("utf-8", errors="replace")
        # 监听进程状态
        if state != -9:
            state = cmd.returncode
    except Exception as err:
        state = 1
        output += f'{err}'
        if dic.get(PID):
            try:
                kill_process(dic.get(PID))
            except ProcessLookupError:
                # 此进程并没有开始就中断了
                pass
    finally:
        end_time = datetime.datetime.now()
        # 任务结束后补齐内存事件的 end_time，避免总览页显示无限延伸的运行块。
        record_task_end(PID, start_time, end_time)
        output_encode = output.encode('utf-8')
        output_size = len(output_encode) // 1000
        if output_size >= 64:
            # 数据库存储完整大日志不划算，超过阈值时截断并提示任务侧落文件。
            output = output_encode[:1000 * 63].decode('utf-8')
            warning = '\nThe log size exceed the limit, please consider saving the output as a file.'
            output += warning
        if state in ["-9", -9]:
            output = "管理员介入kill了此进程"
        
        wfs_obj = GaussDB()
        wfs_connection = wfs_obj.get_connection()
        # 成功任务last_sms_alarm置空，failed_time置0
        if state == 0 and FLASK_ENV == 'production':
            wfs_obj.execute_sql(
                sql="update wfs_job_stats set last_sms_alarm = NULL, failed_times = 0 where pid = ?",
                params=(PID,)
            )
        # 失败任务进行提示
        if state != 0 and FLASK_ENV == 'production':
            failed_job_df = pd.read_sql_query(
                sql="select * from wfs_job_stats where pid = ?",
                con=wfs_connection,
                params=(PID,),
            )
            wfs_obj.execute_sql(
                sql="update wfs_job_stats set failed_times = failed_times + 1 where pid = ?",
                params=(PID,)
            )
            # 任务失败短信提示
            if (sms_receiver_str := failed_job_df["sms_receiver"].values.tolist()[0]) and (failed_job_df["last_sms_alarm"].values[0] == None):
                sms_receiver_list = getReceiverList(receiver_str = sms_receiver_str, send_type = "telephone", connection = wfs_connection)
                logging.getLogger(__name__).info(f"sms_receiver_list: {sms_receiver_list}")
                # output_simple为简化版错误信息，供任务出错时短信提示使用
                logging.getLogger(__name__).info(f"output: {output}")
                output_replaced = output.replace("\n", "")
                logging.getLogger(__name__).info(f"output: {output_replaced}")
                output_simple = re.search(r".+\.py\",? ?(?P<errmsg>.+)$", output_replaced).group("errmsg")
                # 发送短信
                send_sms(sms_receiver_list, f"WFS任务: {PID}执行失败。\n{output_simple}")
                # 更新last_sms_alarm时间
                wfs_obj.execute_sql(
                    sql="update wfs_job_stats set last_sms_alarm = NOW() where pid = ?",
                    params=(PID,)
                )
            # 任务失败邮件提示
            if email_receiver_str := failed_job_df["email_receiver"].values.tolist()[0]:
                email_receiver_list = getReceiverList(receiver_str = email_receiver_str, send_type = "email", connection = wfs_connection)
                logging.getLogger(__name__).info(f"email_receiver_list: {email_receiver_list}")
                body = "PID: " + PID + "<br/><br/>"
                body += output.replace("'", "\\'")
                send_mail(to_receivers = email_receiver_list, subject = "WFS任务:" + task_name + " 执行失败，请检查", body = body)
        
        # 写入运行历史，CPU/内存图中的历史任务色块也依赖这张表。
        try:
            tasklog = output.replace("'", "\\'")
            run_history_sql = '''
            INSERT INTO wfs_run_history(
                    id,
                    pid,
                    taskname,
                    dirname,
                    group_name,
                    folder_name,
                    state,
                    tasklog,
                    start_time,
                    end_time
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            group_name, folder_name = _task_dir_parts(dir_name, group_name, folder_name)
            wfs_obj.execute_sql(
                sql=run_history_sql,
                params=(
                    uuidhex(),
                    PID,
                    task_name,
                    dir_name,
                    group_name,
                    folder_name,
                    state,
                    tasklog,
                    start_time,
                    end_time,
                )
            )
            job_stats_sql = "update wfs_job_stats set last_status = ? where pid = ?"
            wfs_obj.execute_sql(sql=job_stats_sql, params=(state, PID))
        except Exception as e:
            if PID == 'table_sync_policy':
                app_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                log_path = os.path.join(app_path, 'jobs', 'databaseSync', 'table_sync_policy', 'log.txt')
                with open(log_path, 'r', encoding='utf-8') as f:
                    output = f.read()
                    output_size = sys.getsizeof(output) // 1000
                    if output_size >= 64:
                        output = output[:1000 * 50]
                        warning = '\nThe log size exceed the limit, please consider saving the output as a file.'
                        output += warning
                    output += '以上日志为从文件中读取'
                    output += str(e)
            group_name, folder_name = _task_dir_parts(dir_name, group_name, folder_name)
            sql = r"""INSERT INTO wfs_run_history(id,pid,taskname,dirname,state,tasklog,start_time,end_time) VALUES 
            ('{}','{}','{}','{}','{}','{}','{}','{}')""".format(uuidhex(), PID, task_name, dir_name, state,
                                                                output.replace("'", "\\'"), start_time,
                                                                end_time)
            wfs_obj.execute_sql(sql, params=None)
        wfs_obj.close()

        # finally:
        #     sql = ''
        #     Connection.exec_sql(sql)
        #     pass

        # 执行状态改变
        if dic in runnings:
            try:
                pass
            except ProcessLookupError:
                # 到了此处是此进程真的结束了
                pass
            except PermissionError:
                # print("访问进程失败,权限不足,拒绝访问")
                pass
            finally:
                runnings.remove(dic)


# 监听系统日志
def my_listener(event):
    # 获取错误码
    warning_code = event.code
    # 任务id  pid
    job_id = event.job_id
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
    if FLASK_ENV != 'development' or dev_run_all != 'false':
        return True
    if isinstance(dev_run_job_pid, list):
        return pid in dev_run_job_pid
    if isinstance(dev_run_job_pid, str):
        return pid == dev_run_job_pid
    return True


def _sync_job_stats(job_list, prune_missing=True):
    # 每次扫描后把文件系统中的任务清单同步到统计表，前端列表以这张表为基础展示状态。
    current_job_df = pd.DataFrame(job_list, columns=["pid", "group_name", "folder_name", "task_name", "scheduling_stat"])
    with GaussDB() as wfs_obj:
        wfs_connection = wfs_obj.get_connection()
        current_job_in_database_df = pd.read_sql_query("select * from wfs_job_stats", wfs_connection)

        current_pids = set(current_job_df["pid"].tolist()) if not current_job_df.empty else set()
        database_pids = set(current_job_in_database_df["pid"].tolist()) if not current_job_in_database_df.empty else set()

        if prune_missing:
            for removed_pid in sorted(database_pids - current_pids):
                wfs_obj.execute_sql(
                    sql="delete from wfs_job_stats where pid = ?",
                    params=(removed_pid,)
                )
                logging.getLogger(__name__).info("remove_job: %s", removed_pid)

        if current_job_df.empty:
            return

        add_job_df = current_job_df[~current_job_df["pid"].isin(current_job_in_database_df["pid"])]
        for _, row in add_job_df.iterrows():
            try:
                add_job_sql = """
                INSERT INTO wfs_job_stats (
                        pid,
                        group_name,
                        folder_name,
                        task_name,
                        scheduling_stat,
                        sms_receiver,
                        email_receiver,
                        last_status,
                        last_sms_alarm,
                        failed_times
                    ) VALUES (?,?,?,?,?,?,?,?,?,?);
                """
                wfs_obj.execute_sql(
                    sql=add_job_sql,
                    params=(
                        row['pid'],
                        row['group_name'],
                        row['folder_name'],
                        row['task_name'],
                        row['scheduling_stat'],
                        None,
                        None,
                        None,
                        None,
                        0,
                    )
                )
            except Exception:
                add_job_sql = """
                INSERT INTO wfs_job_stats (
                        pid,
                        task_name,
                        scheduling_stat,
                        sms_receiver,
                        email_receiver,
                        last_status,
                        last_sms_alarm,
                        failed_times
                    ) VALUES (?,?,?,?,?,?,?,?);
                """
                wfs_obj.execute_sql(
                    sql=add_job_sql,
                    params=(
                        row['pid'],
                        row['task_name'],
                        row['scheduling_stat'],
                        None,
                        None,
                        None,
                        None,
                        0,
                    )
                )
            logging.getLogger(__name__).info("add_job: %s", row['pid'])

        existing_job_df = current_job_df[current_job_df["pid"].isin(current_job_in_database_df["pid"])]
        for _, row in existing_job_df.iterrows():
            try:
                wfs_obj.execute_sql(
                    sql="update wfs_job_stats set group_name = ?, folder_name = ?, task_name = ?, scheduling_stat = ? where pid = ?",
                    params=(
                        row['group_name'],
                        row['folder_name'],
                        row['task_name'],
                        row['scheduling_stat'],
                        row['pid'],
                    )
                )
            except Exception:
                wfs_obj.execute_sql(
                    sql="update wfs_job_stats set task_name = ?, scheduling_stat = ? where pid = ?",
                    params=(
                        row['task_name'],
                        row['scheduling_stat'],
                        row['pid'],
                    )
                )


def call_task_once(pid):
    for spec in discover_task_specs(TASK_DIR):
        if spec.get('pid') != pid:
            continue
        if spec.get('error'):
            raise ValueError('invalid task config for {}: {}'.format(pid, spec.get('error')))
        if spec.get('main_file_error'):
            raise ValueError('task entry file is invalid for {}: {}'.format(pid, spec.get('main_file_error')))
        if runnings.is_running(pid):
            raise ValueError('task is already running')
        scheduler.add_job(
            func=execute_py,
            trigger='date',
            run_date=datetime.datetime.now() + datetime.timedelta(seconds=1),
            args=[
                str(spec.get('main_file_path')),
                pid,
                spec.get('task_name'),
                spec.get('dir_name'),
                spec.get('timeout_seconds') or 0,
                spec.get('group_name') or '',
                spec.get('folder_name') or '',
                spec.get('python_executable') or '',
            ],
            id='manual_{}_{}'.format(pid, uuidhex()),
            name='Manual run: {}'.format(spec.get('task_name')),
            replace_existing=False,
            max_instances=1,
            misfire_grace_time=60,
        )
        return
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


def aps_start(task_pid=None, action='refresh'):
    """
    扫描任务目录、合并数据库配置，并把可运行任务注册到 APScheduler。
    :param task_pid: 全任务扫描为 None，否则只处理指定 PID
    :param action: refresh/start/reload 等任务控制动作
    """
    job_list = []
    matched_target = task_pid is None

    logging.getLogger(__name__).info('begin to run aps_start pid={} action={}'.format(task_pid, action))
    for spec in discover_task_specs(TASK_DIR):
        pid = spec.get('pid')

        if task_pid and pid != task_pid:
            continue
        if task_pid and pid == task_pid:
            matched_target = True
            _remove_scheduler_job(pid)

        if not pid:
            continue
        if not _should_process_in_dev(pid):
            continue

        if spec.get('error'):
            message = 'invalid task config for {}: {}'.format(pid, spec.get('error'))
            logging.getLogger(__name__).warning(message)
            _remove_scheduler_job(pid)
            if task_pid == pid:
                raise ValueError(message)
            continue

        # 读取前端持久化的调度策略，覆盖任务目录中的默认推断。
        spec = apply_persisted_schedule(spec)

        job_list.append([
            pid,
            spec.get('group_name'),
            spec.get('folder_name'),
            spec.get('task_name'),
            spec.get('raw_start', 'false'),
        ])

        if pid in ignores:
            _remove_scheduler_job(pid)
            continue

        if spec.get('main_file_error'):
            logging.getLogger(__name__).warning('invalid task entry for %s: %s', pid, spec.get('main_file_error'))
            _remove_scheduler_job(pid)
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
            continue
        if scheduler.get_job(pid):
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
                ],
                name=spec.get('task_name'),
                replace_existing=True,
                max_instances=spec.get('max_instances') or 1,
                coalesce=True,
                id=pid,
                misfire_grace_time=600,
            )
            scheduler.resume_job(pid)
        except Exception as exc:
            logging.getLogger(__name__).warning('failed to register job %s: %s', pid, exc)
            _remove_scheduler_job(pid)
            if task_pid == pid:
                raise

    if task_pid and not matched_target:
        raise ValueError('task not found: {}'.format(task_pid))

    _ensure_listener_registered()
    logging.getLogger(__name__).info("lens(job_list):" + str(len(job_list)))
    # 单任务刷新只同步当前 PID，不能用局部 job_list 删除其他任务的统计行。
    _sync_job_stats(job_list, prune_missing=(task_pid is None))
    logging.getLogger(__name__).info('end to run aps_start pid={} action={}'.format(task_pid, action))
