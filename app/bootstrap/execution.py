"""Task process lifecycle, bounded live logs and durable completion."""
from app.bootstrap.timebase import business_now

import datetime
import html
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import queue

from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import SKIPPED
from app.bootstrap.code_version import execution_version
from app.bootstrap.global_vars import BASE_DIR, runnings
from app.bootstrap.system_metrics import record_task_end, record_task_start
from app.bootstrap.helpers import get_runtime_env
from app.bootstrap.operations import create_run, update_run, run_path, read_run, save_history, now

logger = logging.getLogger(__name__)
OUTPUT_LIMIT = 63 * 1024

def _resource_limit(limits, key, environment, default):
    ceiling = max(0, int(os.environ.get(environment, str(default))))
    requested = max(0, int(limits.get(key, ceiling)))
    return min(requested, ceiling) if requested and ceiling else requested or ceiling


def kill_process(pid, force=False):
    from app.bootstrap.task_isolation import stop_process
    stop_process(pid,force)
    if not pid:
        return
    try:
        if os.name == 'nt':
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        pass


def stop_all_tasks():
    for pid in runnings.cancel_all():
        try:
            kill_process(pid, force=True)
        except Exception:
            logger.exception('failed to stop child process %s', pid)


def _drain_output(pipe, chunks, run_id, flags):
    kept = total = 0
    limit = int(os.environ.get('WFS_RUN_LOG_MAX_BYTES', str(5 * 1024 * 1024)))
    try:
        with run_path(run_id, 'log').open('wb') as log:
            while True:
                part = pipe.read(8192)
                if not part:
                    break
                clipped = part[:max(0, OUTPUT_LIMIT - kept)]
                if clipped:
                    chunks.append(clipped)
                    kept += len(clipped)
                full = part[:max(0, limit - total)]
                log.write(full)
                log.flush()
                total += len(full)
                flags['truncated'] |= len(full) < len(part)
    except (OSError, ValueError):
        flags['error'] = True
        logger.exception('live log write unavailable: %s', run_id)
        # Keep draining so a full pipe cannot deadlock the task.
        try:
            while pipe.read(8192):
                pass
        except (OSError, ValueError):
            pass
    finally:
        pipe.close()


def execute_py(path, PID, task_name='', dir_name='', timeout_seconds=0, group_name='', folder_name='', python_executable='', max_instances=1, reservation=None, run_id=None, limits=None, scheduled_time=None):
    from app.bootstrap import admission
    with admission.lock:
        draining = admission.maintenance()['enabled']
        reservation = reservation if reservation is not None else (None if draining else runnings.claim(PID, max(1, int(max_instances or 1)), group_name))
    try:
        run_id = run_id or create_run(PID, task_name, dir_name=dir_name, group_name=group_name, folder_name=folder_name,scheduled_time=scheduled_time)
    except Exception:
        if reservation is not None:
            runnings.remove(reservation)
        raise
    if draining or reservation is None:
        if reservation is not None: runnings.remove(reservation)
        record = update_run(run_id, status='skipped', state=SKIPPED, end_time=now(), reason='维护模式：本次计划未启动，恢复后不会自动补跑。' if draining else runnings.capacity_reason(PID, max_instances, group_name))
        save_history(record)
        return
    start = business_now()
    output = ''
    state = 1
    process = reader = None
    chunks = []
    flags = {'truncated': False, 'error': False}
    limits = limits or {}
    try:
        current = read_run(run_id)
        provenance = execution_version(path, python_executable)
        update_run(run_id, code_version=provenance, start_delay_seconds=max(0,(start-datetime.datetime.fromisoformat(current.get('scheduled_time') or current['created_at'])).total_seconds()))
        if current.get('source') != 'trial':
            record_task_start(PID, task_name, group_name, folder_name, start)
        if runnings.is_cancelled(reservation):
            state, output = -15, 'Task stopped before execution.'
        else:
            entry = Path(path).resolve()
            task_root = entry.parent
            if provenance.get('task_release'):
                from app.bootstrap.task_packages import storage_root
                relative_entry = entry.relative_to(storage_root().resolve())
                task_root = storage_root().resolve().joinpath(*relative_entry.parts[:4])
            child_env = os.environ.copy()
            from app.bootstrap.operational_policy import load as operational_policy
            runtime_policy=operational_policy('task',PID)
            import json
            run_context=read_run(run_id)
            child_env['WFS_PARAMETERS_JSON']=json.dumps(run_context.get('parameters',runtime_policy['parameters']),ensure_ascii=True)
            child_env['WFS_BUSINESS_DATE']=run_context.get('business_date','')
            child_env['WFS_EXECUTION_SOURCE']=run_context.get('source','scheduled')
            child_env['PYTHONIOENCODING'] = 'utf-8'
            if provenance.get('task_release'):
                child_env['PYTHONDONTWRITEBYTECODE'] = '1'
            # Business output has a stable home across code updates/rollbacks.
            from app.bootstrap.global_vars import DATA_DIR
            import re
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', str(PID)):
                data_dir = Path(DATA_DIR) / ('trial-data' if current.get('source')=='trial' else 'task-data') / PID
                data_dir.mkdir(parents=True, exist_ok=True)
                child_env['WFS_TASK_DATA_DIR'] = str(data_dir.resolve())
                child_env['WFS_TASK_ID'] = PID
                from app.bootstrap.task_artifacts import output_directory
                _, _, output_dir = output_directory(PID, run_id, create=True,trial=current.get('source')=='trial')
                child_env['WFS_OUTPUT_DIR'] = str(output_dir.resolve())
                child_env['WFS_RUN_ID'] = run_id
                child_env['WFS_TASK_ROOT'] = str(task_root)
                update_run(run_id, output_layout='per-run-v1')
            from app.bootstrap.connection_settings import task_database_key
            database_key = task_database_key()
            for key in ('WFS_SECRET_KEY', 'WFS_CONNECTIONS_KEY', 'WFS_TASK_DATABASE_KEY', 'WFS_ADMIN_PASSWORD_HASH', 'WFS_USERS_JSON','WFS_GITLAB_WEBHOOK_TOKEN'):
                child_env.pop(key, None)
            restricted = admission.connection_environment(PID)
            if run_context.get('source')=='trial':
                from app.bootstrap.connection_settings import business_profile
                selected={}
                for original,test in runtime_policy['test_connections'].items():
                    profile=business_profile(test)
                    if not profile or not profile.get('enabled',True): raise ValueError('测试连接不可用：'+test)
                    selected[original]={**profile,'id':original}
                restricted=json.dumps(selected,ensure_ascii=True)
            child_env.pop('WFS_TASK_CONNECTIONS_JSON', None)
            if restricted is not None:
                allowed_env = {'PATH','HOME','USER','LOGNAME','LANG','LC_ALL','LC_CTYPE','TZ',
                    'TMPDIR','TMP','TEMP','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','USERPROFILE',
                    'APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH','PYTHONPATH','PYTHONIOENCODING',
                    'PYTHONDONTWRITEBYTECODE','WFS_ENV','WFS_DATA_DIR','WFS_TASK_ID',
                    'WFS_TASK_ROOT','WFS_TASK_DATA_DIR','WFS_OUTPUT_DIR','WFS_RUN_ID',
                    'WFS_PARAMETERS_JSON','WFS_BUSINESS_DATE','WFS_EXECUTION_SOURCE'}
                child_env = {key:value for key,value in child_env.items() if key.upper() in allowed_env}
                child_env['WFS_TASK_CONNECTIONS_JSON'] = restricted
            elif database_key:
                child_env['WFS_TASK_DATABASE_KEY'] = database_key
            sdk_root=None
            if provenance.get('shared_sdk_package'):
                sdk_root=Path(python_executable).parent.parent
            elif provenance.get('shared_sdk_sha256'):
                from app.bootstrap.shared_sdk import verify
                sdk_root=task_root.parent/'shared-sdk'
                if not verify(task_root.parent,provenance['shared_sdk_sha256']): raise ValueError('公共 SDK 快照校验失败。')
            if restricted is None:
                from app.bootstrap.global_vars import CONFIG_DIR
                child_env['WFS_TASK_CONFIG_DIR']=str(CONFIG_DIR)
            else: child_env.pop('WFS_TASK_CONFIG_DIR',None)
            child_env['PYTHONPATH'] = '' if provenance.get('shared_sdk_package') else str(sdk_root) if sdk_root else os.pathsep.join(filter(None,(str(BASE_DIR.parent),child_env.get('PYTHONPATH'))))
            command = [python_executable or sys.executable, '-u', str(Path(__file__).with_name('worker.py')),
                       '--memory-mb', str(_resource_limit(limits, 'memory_mb', 'WFS_TASK_MEMORY_MB', 0)),
                       '--cpu-seconds', str(_resource_limit(limits, 'cpu_seconds', 'WFS_TASK_CPU_SECONDS', 0)),
                       '--file-mb', str(_resource_limit(limits, 'file_mb', 'WFS_TASK_FILE_MB', 100)),
                       '--task-root', str(task_root), str(entry)]
            kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP, 'executable': command[0]} if os.name == 'nt' else {'start_new_session': True}
            isolated_unit=None
            if runtime_policy['isolation']=='systemd':
                from app.bootstrap.task_isolation import wrapper
                command,child_env,isolated_unit=wrapper(command,child_env,task_root,sdk_root,data_dir,output_dir,run_id,runtime_policy['resources'])
                update_run(run_id,systemd_unit=isolated_unit)
            # Final admission and process creation share the maintenance lock.
            with admission.lock:
                admission.ensure_open()
                process = subprocess.Popen(command, cwd=str(task_root), stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, shell=False, env=child_env, **kwargs)
                runnings.set_process(reservation, PID, process.pid)
                if isolated_unit:
                    from app.bootstrap.task_isolation import register
                    register(process.pid,isolated_unit)
            identity = Path(f'/proc/{process.pid}/stat').read_text().split()[21] if os.name != 'nt' else ''
            update_run(run_id, status='running', start_time=str(start), process_id=process.pid, process_identity=identity)
            reader = threading.Thread(target=_drain_output, args=(process.stdout, chunks, run_id, flags), daemon=True)
            reader.start()
            deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
            heartbeat = time.monotonic()
            while True:
                cancelled = runnings.is_cancelled(reservation)
                timed_out = deadline is not None and time.monotonic() >= deadline
                if cancelled or timed_out:
                    state = -15 if cancelled else -9
                    output = 'Task stopped by administrator.' if cancelled else f'Task exceeded TIMEOUT_SECONDS={timeout_seconds}.'
                    kill_process(process.pid)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        kill_process(process.pid, force=True)
                        process.wait(timeout=5)
                    break
                if time.monotonic() - heartbeat >= 5:
                    update_run(run_id, persist=False)
                    heartbeat = time.monotonic()
                try:
                    state = process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
    except admission.MaintenanceClosed:
        state, output = SKIPPED, '维护模式：本次计划未启动，恢复后不会自动补跑。'
    except Exception as exc:
        state = 1
        output += str(exc)
        logger.exception('task execution failed: %s', PID)
    finally:
        if process is not None:
            try:
                if process.poll() is None or os.name != 'nt':
                    kill_process(process.pid, force=True)
                process.wait(timeout=5)
            except Exception:
                logger.exception('process cleanup failed: %s', PID)
            if reader:
                reader.join(timeout=5)
        end = business_now()
        runnings.remove(reservation)
        try:
            if current.get('source') != 'trial':
                record_task_end(PID, start, end)
        except Exception:
            logger.exception('timeline completion failed')
        status = {0: 'success', -9: 'timed_out', -15: 'cancelled', SKIPPED:'skipped'}.get(state, 'failed')
        if not output and state:
            output = f'Process exited with code {state}.'
        try:
            record = update_run(run_id, status=status, state=state, start_time=str(start), end_time=str(end), reason=output,
                                log_truncated=flags['truncated'], log_error=flags['error'])
            from app.bootstrap.execution_requests import retry_result
            retry_result(record)
            save_history(record)
        except Exception:
            logger.exception('execution completion journal failed: %s', run_id)
    return state
