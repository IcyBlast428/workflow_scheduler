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
    reservation = reservation if reservation is not None else runnings.claim(PID, max(1, int(max_instances or 1)))
    try:
        run_id = run_id or create_run(PID, task_name, dir_name=dir_name, group_name=group_name, folder_name=folder_name,scheduled_time=scheduled_time)
    except Exception:
        if reservation is not None:
            runnings.remove(reservation)
        raise
    if reservation is None:
        record = update_run(run_id, status='skipped', state=SKIPPED, end_time=now(), reason=runnings.capacity_reason(PID, max_instances))
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
        record_task_start(PID, task_name, group_name, folder_name, start)
        if runnings.is_cancelled(reservation):
            state, output = -15, 'Task stopped before execution.'
        else:
            entry = Path(path).resolve()
            child_env = os.environ.copy()
            child_env['PYTHONIOENCODING'] = 'utf-8'
            if provenance.get('task_release'):
                child_env['PYTHONDONTWRITEBYTECODE'] = '1'
            # Business output has a stable home across code updates/rollbacks.
            from app.bootstrap.global_vars import DATA_DIR
            import re
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', str(PID)):
                data_dir = Path(DATA_DIR) / 'task-data' / PID
                data_dir.mkdir(parents=True, exist_ok=True)
                child_env['WFS_TASK_DATA_DIR'] = str(data_dir.resolve())
                child_env['WFS_TASK_ID'] = PID
            for key in ('WFS_SECRET_KEY', 'WFS_ADMIN_PASSWORD_HASH', 'WFS_USERS_JSON'):
                child_env.pop(key, None)
            child_env['PYTHONPATH'] = os.pathsep.join(filter(None, (str(BASE_DIR.parent), child_env.get('PYTHONPATH'))))
            command = [python_executable or sys.executable, '-u', str(Path(__file__).with_name('worker.py')),
                       '--memory-mb', str(_resource_limit(limits, 'memory_mb', 'WFS_TASK_MEMORY_MB', 0)),
                       '--cpu-seconds', str(_resource_limit(limits, 'cpu_seconds', 'WFS_TASK_CPU_SECONDS', 0)),
                       '--file-mb', str(_resource_limit(limits, 'file_mb', 'WFS_TASK_FILE_MB', 100)), str(entry)]
            kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen(command, cwd=str(entry.parent), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, shell=False, env=child_env, **kwargs)
            runnings.set_process(reservation, PID, process.pid)
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
            record_task_end(PID, start, end)
        except Exception:
            logger.exception('timeline completion failed')
        status = {0: 'success', -9: 'timed_out', -15: 'cancelled'}.get(state, 'failed')
        if not output and state:
            output = f'Process exited with code {state}.'
        try:
            record = update_run(run_id, status=status, state=state, start_time=str(start), end_time=str(end), reason=output,
                                log_truncated=flags['truncated'], log_error=flags['error'])
            save_history(record)
        except Exception:
            logger.exception('execution completion journal failed: %s', run_id)
    return state
