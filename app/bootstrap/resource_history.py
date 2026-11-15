"""Append-only resource samples, with atomic bounded compaction and legacy reads.

The Scheduler is the sole writer; Web workers only read complete JSONL records.
A reader holds one file handle so replacement cannot mix checkpoint generations.
"""
import datetime as dt
import json
import math
import os
from pathlib import Path
import tempfile
import time

from app.bootstrap.timebase import business_now, business_time

COMPACT_SECONDS = 300


def _sample(item):
    if not isinstance(item, dict) or not isinstance(item.get('time'), str):
        raise ValueError('invalid sample')
    at = business_time(item['time'])
    for key in ('cpu', 'memory'):
        value = item.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError('invalid resource percentage')
    return {'time': item['time'], 'cpu': item.get('cpu'), 'memory': item.get('memory'), 'time_obj': at}


def _line(item):
    return (json.dumps({key: item.get(key) for key in ('time', 'cpu', 'memory')},
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


class ResourceHistory:
    def __init__(self, legacy_path, retention, clock=time.monotonic):
        self.legacy_path = Path(legacy_path)
        self.path = self.legacy_path.with_suffix('.jsonl')
        self.retention = retention
        self.clock = clock
        self._compact_at = self.clock() + COMPACT_SECONDS
        self._repair = False

    def load(self, now=None):
        """Recover valid samples; an interrupted last append never hides earlier rows."""
        cutoff = (now or business_now()) - dt.timedelta(seconds=self.retention)
        samples, damaged = [], False
        try:
            # One open descriptor sees either the complete old or new compacted file.
            try:
                stream = self.path.open('rb')
            except FileNotFoundError:
                stream = None
            if stream is not None:
                with stream:
                    for line in stream:
                        if not line.endswith(b'\n'):
                            damaged = True
                            continue
                        try:
                            item = _sample(json.loads(line))
                        except (ValueError, TypeError, KeyError, OverflowError):
                            damaged = True
                            continue
                        if item['time_obj'] >= cutoff:
                            samples.append(item)
            else:
                try:
                    legacy = json.loads(self.legacy_path.read_text(encoding='utf-8'))
                except FileNotFoundError:
                    legacy = []
                if not isinstance(legacy, list):
                    raise ValueError('invalid legacy resource history')
                for raw in legacy:
                    try:
                        item = _sample(raw)
                    except (ValueError, TypeError, KeyError, OverflowError):
                        damaged = True
                        continue
                    if item['time_obj'] >= cutoff:
                        samples.append(item)
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            damaged = True
        self._repair = damaged
        return samples, 'Some historical resource metrics could not be loaded' if damaged else ''

    def append(self, sample, retained):
        """Persist every sample; only compaction rewrites the retained window."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._repair or not self.path.exists() or self.clock() >= self._compact_at:
            self._compact(retained)
            return
        try:
            with self.path.open('ab') as stream:
                stream.write(_line(sample))
                stream.flush()
                os.fsync(stream.fileno())
        except (OSError, ValueError):
            # The next successful write repairs a partial append from the in-memory window.
            self._repair = True
            raise

    def _compact(self, retained):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=self.path.name + '.', suffix='.tmp',
                                             dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                for item in retained:
                    stream.write(_line(item))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self._repair = False
            self._compact_at = self.clock() + COMPACT_SECONDS
        except (OSError, ValueError):
            self._repair = True
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
