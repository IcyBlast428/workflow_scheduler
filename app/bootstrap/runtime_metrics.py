"""Bounded, non-blocking samples shared by Web and Scheduler via WFS_DATA_DIR.

No SQL, parameters, credentials or task identifiers are stored. Sampling failures
must never change a database operation or execution outcome.
"""
from collections import defaultdict, deque
from contextlib import contextmanager
import atexit
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

WINDOW_SECONDS = 900
MAX_SAMPLES = 512
MAX_METRICS = 128
MAX_PROCESSES = 64
FLUSH_SECONDS = 5
_FILE = re.compile(r'^process-[0-9]+-[a-f0-9]{12}\.json$')


def summarize(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {'samples': len(ordered), 'p50_ms': round(ordered[math.ceil(len(ordered)*.5)-1], 2),
            'p95_ms': round(ordered[math.ceil(len(ordered)*.95)-1], 2),
            'max_ms': round(ordered[-1], 2), 'mean_ms': round(sum(ordered)/len(ordered), 2)}


class Collector:
    def __init__(self, directory, clock=time.time):
        self.directory = Path(directory)
        self.clock = clock
        self.pid = os.getpid()
        self.identifier = f'process-{self.pid}-{uuid.uuid4().hex[:12]}.json'
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.samples = {}
        self.dirty = False
        self.write_error = False
        self.dropped = 0

    def record(self, name, milliseconds):
        try:
            value = float(milliseconds)
            if not isinstance(name, str) or len(name) > 180 or not name.startswith(
                    ('api:', 'database:', 'nacos:', 'lock:', 'queue:', 'task:')):
                return
            if not math.isfinite(value) or value < 0:
                return
            with self.lock:
                if name not in self.samples and len(self.samples) >= MAX_METRICS:
                    self.dropped += 1
                    return
                self.samples.setdefault(name, deque(maxlen=MAX_SAMPLES)).append((self.clock(), round(value, 2)))
                self.dirty = True
        except (TypeError, ValueError, OverflowError):
            return

    def payload(self):
        cutoff = self.clock() - WINDOW_SECONDS
        with self.lock:
            samples = {}
            for name, values in self.samples.items():
                while values and values[0][0] < cutoff:
                    values.popleft()
                if values:
                    samples[name] = list(values)
            return {'version': 1, 'pid': self.pid, 'at': self.clock(),
                    'role': 'scheduler' if os.environ.get('WFS_ENABLE_SCHEDULER') == 'true' else 'web',
                    'samples': samples, 'dropped': self.dropped}

    def flush(self):
        if os.getpid() != self.pid or not self.write_lock.acquire(blocking=False):
            return
        target = self.directory / self.identifier
        temporary = target.with_suffix('.tmp')
        try:
            with self.lock:
                if not self.dirty:
                    return
                self.dirty = False
            payload = self.payload()
            self.directory.mkdir(parents=True, exist_ok=True)
            with open(temporary, 'w', encoding='utf-8') as stream:
                if os.name != 'nt':
                    os.chmod(temporary, 0o600)
                json.dump(payload, stream, separators=(',', ':'))
            os.replace(temporary, target)
            self.write_error = False
            # Only our own expired snapshot names are eligible for collection.
            cutoff = self.clock() - WINDOW_SECONDS * 2
            for path in self.directory.iterdir():
                if _FILE.fullmatch(path.name) and not path.is_symlink() and path.stat().st_mtime < cutoff:
                    try:
                        path.unlink()
                    except OSError:
                        pass
        except (OSError, ValueError):
            self.write_error = True
            with self.lock:
                self.dirty = True
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        finally:
            self.write_lock.release()

    def collect(self):
        now = self.clock()
        payloads = [self.payload()]
        invalid = 0
        truncated = False
        try:
            candidates = sorted((p for p in self.directory.iterdir()
                                 if _FILE.fullmatch(p.name) and p.name != self.identifier and not p.is_symlink()),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            truncated = len(candidates) > MAX_PROCESSES - 1
            for path in candidates[:MAX_PROCESSES-1]:
                try:
                    if path.stat().st_size > 8*1024*1024:
                        raise ValueError('oversized snapshot')
                    item = json.loads(path.read_text(encoding='utf-8'))
                    if (not isinstance(item, dict) or item.get('version') != 1 or not isinstance(item.get('samples'), dict)
                            or not isinstance(item.get('pid'), int) or not isinstance(item.get('at'), (int,float))
                            or not math.isfinite(item['at']) or not isinstance(item.get('dropped',0), int)):
                        raise ValueError('invalid snapshot')
                    if not 0 <= now - float(item['at']) <= WINDOW_SECONDS:
                        continue
                    payloads.append(item)
                except (OSError, ValueError, TypeError, KeyError):
                    invalid += 1
        except FileNotFoundError:
            pass
        except OSError:
            invalid += 1
        values = defaultdict(list)
        sources = []
        for payload in payloads:
            used = False
            for name, samples in list(payload['samples'].items())[:MAX_METRICS]:
                if not isinstance(name, str) or len(name)>180 or not isinstance(samples, list):
                    invalid += 1
                    continue
                for sample in samples[-MAX_SAMPLES:]:
                    try:
                        at, value = sample
                        if not all(isinstance(n, (int, float)) and math.isfinite(n) for n in (at, value)):
                            raise ValueError('invalid value')
                        if 0 <= now-at <= WINDOW_SECONDS and value >= 0:
                            values[name].append(value)
                            used = True
                    except (TypeError, ValueError):
                        invalid += 1
            if used:
                sources.append({'id': str(payload['pid']) + ':' + str(payload['at']), 'pid': payload['pid'], 'role': payload.get('role', 'unknown'),
                                'age_seconds': max(0, round(now-payload['at'], 1))})
        return {'metrics': {name: summarize(items) for name, items in sorted(values.items())},
                'window_seconds': WINDOW_SECONDS, 'per_process_limit': MAX_SAMPLES,
                'sources': sources, 'invalid_snapshots': invalid, 'truncated': truncated,
                'write_error': self.write_error, 'dropped_metrics': sum(p.get('dropped', 0) for p in payloads),
                'flush_seconds': FLUSH_SECONDS}


_collector = None
_guard = threading.Lock()


def _reset_after_fork():
    global _collector, _guard
    _collector = None
    _guard = threading.Lock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_after_fork)


def _current():
    global _collector
    with _guard:
        if _collector is None:
            from app.bootstrap.global_vars import DATA_DIR
            collector = Collector(Path(DATA_DIR) / 'runtime-metrics')
            _collector = collector
            def export():
                while True:
                    time.sleep(FLUSH_SECONDS)
                    collector.flush()
            threading.Thread(target=export, name='wfs-metrics', daemon=True).start()
            atexit.register(collector.flush)
        return _collector


def record(name, milliseconds):
    try:
        _current().record(name, milliseconds)
    except Exception:
        # Telemetry is optional and cannot fail a user operation.
        pass


@contextmanager
def measure(name):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = 1000 * (time.perf_counter() - started)
        record(name, elapsed)
        if name.startswith('lock:'):
            record('lock:all', elapsed)


def diagnostics():
    return _current().collect()


def snapshot():
    """Preserve the existing metrics API while aggregating shared process samples."""
    return diagnostics()['metrics']


def record_delay(name, started, ended):
    """Invalid legacy timestamps must never change dispatch or execution outcomes."""
    try:
        from datetime import datetime
        record(name, max(0, (ended-datetime.fromisoformat(str(started))).total_seconds()*1000))
    except (TypeError, ValueError, OverflowError):
        pass
