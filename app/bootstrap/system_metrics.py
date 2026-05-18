import ctypes
import datetime
import os
import threading
import time


CPU_SAMPLE_INTERVAL_SECONDS = 5
CPU_RETENTION_SECONDS = 6 * 60 * 60
TASK_EVENT_RETENTION_SECONDS = 6 * 60 * 60


class _CpuMonitor:
    def __init__(self, interval=CPU_SAMPLE_INTERVAL_SECONDS, retention=CPU_RETENTION_SECONDS):
        self.interval = interval
        self.retention = retention
        self._samples = []
        self._lock = threading.Lock()
        self._started = False
        self._last_times = None
        self._warning = ''

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        thread = threading.Thread(target=self._run, name='wfs-cpu-monitor', daemon=True)
        thread.start()

    def snapshot(self, hours=6):
        self.start()
        since = datetime.datetime.now() - datetime.timedelta(hours=hours)
        with self._lock:
            samples = [
                dict(item)
                for item in self._samples
                if item['time_obj'] >= since
            ]
            warning = self._warning
        for item in samples:
            item.pop('time_obj', None)
        return {
            'samples': samples,
            'current': samples[-1]['cpu'] if samples else None,
            'sample_interval_seconds': self.interval,
            'retention_hours': hours,
            'warning': warning,
        }

    def _run(self):
        while True:
            try:
                self._append_sample()
            except Exception as exc:
                with self._lock:
                    self._warning = str(exc)
            time.sleep(self.interval)

    def _append_sample(self):
        current = _read_cpu_times()
        if not current:
            with self._lock:
                self._warning = 'CPU metrics are unavailable on this host'
            return

        percent = None
        with self._lock:
            if self._last_times:
                last_idle, last_total = self._last_times
                idle, total = current
                total_delta = total - last_total
                idle_delta = idle - last_idle
                if total_delta > 0:
                    percent = max(0.0, min(100.0, (1.0 - (idle_delta / total_delta)) * 100.0))
            self._last_times = current

        if percent is None:
            return

        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(seconds=self.retention)
        sample = {
            'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'time_obj': now,
            'cpu': round(percent, 1),
        }
        with self._lock:
            self._samples.append(sample)
            self._samples = [item for item in self._samples if item['time_obj'] >= cutoff]
            self._warning = ''


def _read_cpu_times():
    if os.name == 'nt':
        return _read_windows_cpu_times()
    return _read_proc_stat_cpu_times()


def _read_proc_stat_cpu_times():
    try:
        with open('/proc/stat', 'r', encoding='utf-8') as handle:
            fields = handle.readline().split()
    except OSError:
        return None
    if not fields or fields[0] != 'cpu':
        return None
    values = [int(value) for value in fields[1:]]
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def _filetime_to_int(filetime):
    return (filetime.dwHighDateTime << 32) + filetime.dwLowDateTime


def _read_windows_cpu_times():
    class FILETIME(ctypes.Structure):
        _fields_ = [
            ('dwLowDateTime', ctypes.c_ulong),
            ('dwHighDateTime', ctypes.c_ulong),
        ]

    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
    except Exception:
        return None
    if not ok:
        return None
    idle_time = _filetime_to_int(idle)
    total_time = _filetime_to_int(kernel) + _filetime_to_int(user)
    return idle_time, total_time


class _TaskStartEvents:
    def __init__(self, retention=TASK_EVENT_RETENTION_SECONDS):
        self.retention = retention
        self._events = []
        self._lock = threading.Lock()

    def record(self, pid, task_name='', group_name='', folder_name='', start_time=None):
        start_time = start_time or datetime.datetime.now()
        event = {
            'id': pid,
            'name': task_name or pid,
            'group_name': group_name or '',
            'folder_name': folder_name or '',
            'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': '',
            'start_time_obj': start_time,
            'source': 'running',
        }
        cutoff = datetime.datetime.now() - datetime.timedelta(seconds=self.retention)
        with self._lock:
            self._events.append(event)
            self._events = [item for item in self._events if item['start_time_obj'] >= cutoff]

    def complete(self, pid, start_time, end_time=None):
        end_time = end_time or datetime.datetime.now()
        start_key = start_time.strftime('%Y-%m-%d %H:%M:%S') if hasattr(start_time, 'strftime') else str(start_time or '')[:19]
        with self._lock:
            for item in reversed(self._events):
                if item.get('id') == pid and item.get('start_time') == start_key:
                    item['end_time'] = end_time.strftime('%Y-%m-%d %H:%M:%S')
                    item['end_time_obj'] = end_time
                    item['source'] = 'memory'
                    return

    def recent(self, since):
        with self._lock:
            events = [
                dict(item)
                for item in self._events
                if item['start_time_obj'] >= since
            ]
        for item in events:
            item.pop('start_time_obj', None)
            item.pop('end_time_obj', None)
        return events


_cpu_monitor = _CpuMonitor()
_task_starts = _TaskStartEvents()


def cpu_monitor_snapshot(hours=6):
    return _cpu_monitor.snapshot(hours=hours)


def record_task_start(pid, task_name='', group_name='', folder_name='', start_time=None):
    _task_starts.record(
        pid=pid,
        task_name=task_name,
        group_name=group_name,
        folder_name=folder_name,
        start_time=start_time,
    )


def record_task_end(pid, start_time, end_time=None):
    _task_starts.complete(pid, start_time, end_time=end_time)


def recent_task_starts(since):
    return _task_starts.recent(since)
