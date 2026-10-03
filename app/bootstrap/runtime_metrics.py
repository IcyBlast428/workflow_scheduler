"""Bounded latency samples, without SQL arguments or credentials."""
from collections import deque
import threading

_lock = threading.Lock()
_samples = {}


def record(name, milliseconds):
    with _lock:
        _samples.setdefault(name,deque(maxlen=512)).append(round(milliseconds,2))


def snapshot():
    with _lock:
        result = {}
        for name,samples in _samples.items():
            ordered = sorted(samples)
            result[name] = {'samples':len(ordered),'p95_ms':ordered[min(len(ordered)-1,int(len(ordered)*.95))], 'max_ms':ordered[-1]}
        return result
