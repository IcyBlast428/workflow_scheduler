"""Bounded, coalesced cache for scheduler snapshots."""
import copy
import threading
import time

_lock = threading.RLock()
_entries = {}
_inflight = {}
_generation = 0


def invalidate():
    global _generation
    with _lock:
        _generation += 1


def cached(key, seconds, factory, mutable=True):
    while True:
        with _lock:
            entry = _entries.get(key)
            hit = entry and entry[0] > time.monotonic() and (not mutable or entry[1] == _generation)
            if hit:
                value = entry[2]
                break
            pending = _inflight.get(key)
            if pending is None:
                pending = _inflight[key] = (threading.Event(), threading.get_ident())
                generation = _generation
                break
            if pending[1] == threading.get_ident():
                raise RuntimeError('recursive snapshot cache refresh for the same key')
        # Only readers of this key wait. Database work never holds the map lock.
        pending[0].wait()
    if hit:
        return copy.deepcopy(value)
    try:
        value = factory()
        stored = copy.deepcopy(value)
        with _lock:
            # An invalidation during the query must not publish stale data as fresh.
            if not mutable or generation == _generation:
                if key not in _entries and len(_entries) >= 100:
                    _entries.pop(next(iter(_entries)))
                _entries[key] = (time.monotonic()+seconds, generation, stored)
        return copy.deepcopy(value)
    finally:
        with _lock:
            _inflight.pop(key, None)
            pending[0].set()
