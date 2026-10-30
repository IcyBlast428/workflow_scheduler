"""Single scheduler process: admission smoothing plus a final process-start gate."""
import threading
import time
from app.bootstrap.operational_policy import load

_lock=threading.Lock()
_next_start=0.0
_sample_at=0.0
_high_samples=0
_low_samples=0
_blocked=False
_cpu=None
_memory=None
_error=''
_last_times=None

class LaunchExpired(RuntimeError):
    pass

class LaunchCancelled(RuntimeError):
    pass


def _measure():
    global _last_times
    from app.bootstrap.system_metrics import _read_cpu_times, _read_memory_percent
    current=_read_cpu_times();memory=_read_memory_percent()
    previous=_last_times;_last_times=current
    if not current or not previous or memory is None: raise RuntimeError('等待采样基线')
    idle,total=current;old_idle,old_total=previous
    if total<=old_total: raise RuntimeError('无有效采样增量')
    cpu=max(0.0,min(100.0,100*(1-(idle-old_idle)/(total-old_total))))
    return round(cpu,1),memory


def sample():
    """Called once a second by the dispatcher; reuse native Linux/Windows readers."""
    global _sample_at,_high_samples,_low_samples,_blocked,_cpu,_memory,_error
    policy=load('dispatch')
    try:
        cpu,memory=_measure()
        with _lock:
            _cpu,_memory,_sample_at,_error=cpu,memory,time.monotonic(),''
            high=cpu>=policy['cpu_high'] or memory>=policy['memory_high']
            low=cpu<policy['cpu_high']-10 and memory<policy['memory_high']-5
            _high_samples=_high_samples+1 if high else 0
            _low_samples=_low_samples+1 if low else 0
            if _high_samples>=3: _blocked=True
            if _low_samples>=3: _blocked=False
    except Exception:
        with _lock:
            _error='负载采样不可用或正在预热'
            _high_samples=_low_samples=0


def reason(policy=None,include_interval=True):
    policy=policy or load('dispatch')
    with _lock:
        if policy['load_protection']:
            if _error or time.monotonic()-_sample_at>5: return '等待有效的主机负载采样。'
            if _blocked: return '主机负载持续偏高，暂缓启动；恢复后继续派发。'
        if include_interval and time.monotonic()<_next_start: return '等待启动间隔。'
    return ''


def reserve_launch():
    global _next_start
    policy=load('dispatch')
    with _lock:
        if policy['load_protection'] and (_error or time.monotonic()-_sample_at>5 or _blocked): return False
        now=time.monotonic()
        if now<_next_start: return False
        _next_start=now+policy['start_interval_ms']/1000
        return True


def snapshot():
    policy=load('dispatch')
    from app.bootstrap.global_vars import runnings
    import os
    with _lock:
        value=dict(cpu_percent=_cpu,memory_percent=_memory,sample_error=_error)
    return dict(value,reason=reason(policy),active=runnings.count(),
                max_active=min(policy['max_active'],int(os.environ.get('WFS_MAX_ACTIVE_RUNS','20'))))


def wait_for_launch(reservation,deadline='',launch=lambda:None):
    """Do not hold admission lock while waiting; maintenance/cancellation remain responsive."""
    from app.bootstrap import admission
    from app.bootstrap.global_vars import runnings
    from app.bootstrap.timebase import business_now
    while True:
        admission.ensure_open()
        if runnings.is_cancelled(reservation): raise LaunchCancelled('启动前已取消。')
        if deadline and str(business_now())>=deadline: raise LaunchExpired('已超过允许启动的时间，未启动业务进程。')
        with admission.lock:
            admission.ensure_open()
            if runnings.is_cancelled(reservation): raise LaunchCancelled('启动前已取消。')
            if deadline and str(business_now())>=deadline: raise LaunchExpired('已超过允许启动的时间，未启动业务进程。')
            if reserve_launch(): return launch()
        time.sleep(0.1)
