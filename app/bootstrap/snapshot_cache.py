"""Bounded, coalesced cache for scheduler snapshots."""
import copy
import threading
import time

_lock = threading.RLock()
_entries = {}
_generation = 0


def invalidate():
    global _generation
    with _lock:
        _generation += 1


def cached(key, seconds, factory, mutable=True):
    # Holding the lock coalesces requests instead of multiplying database work.
    with _lock:
        entry = _entries.get(key)
        if entry and entry[0] > time.monotonic() and (not mutable or entry[1] == _generation):
            return copy.deepcopy(entry[2])
        value = factory()
        if len(_entries) >= 100:
            _entries.pop(next(iter(_entries)))
        _entries[key] = (time.monotonic()+seconds, _generation, value)
        return copy.deepcopy(value)
