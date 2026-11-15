"""Resource persistence keeps sampling precision while avoiding full-window rewrites."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.bootstrap.resource_history import ResourceHistory, COMPACT_SECONDS
from app.bootstrap import system_metrics


class ResourceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'metrics.json'
        self.now = dt.datetime(2030, 1, 1, 12)
        self.tick = 0
        self.history = ResourceHistory(self.path, 6 * 3600, clock=lambda: self.tick)

    def sample(self, seconds=0, cpu=25):
        at = self.now + dt.timedelta(seconds=seconds)
        return {'time': at.strftime('%Y-%m-%d %H:%M:%S'), 'time_obj': at, 'cpu': cpu, 'memory': 50}

    @staticmethod
    def public(item):
        return {key: value for key, value in item.items() if key != 'time_obj'}

    def test_legacy_restore_migrates_once_without_changing_original_file(self):
        retained = [self.sample(-10), self.sample(-5)]
        legacy = json.dumps([self.public(item) for item in retained])
        self.path.write_text(legacy)
        loaded, warning = self.history.load(self.now)
        self.assertEqual(loaded, retained)
        self.assertFalse(warning)
        retained.append(self.sample())
        self.history.append(retained[-1], retained)
        self.assertEqual(self.path.read_text(), legacy)
        self.assertEqual(self.history.load(self.now)[0], retained)
        self.assertEqual(len(self.history.path.read_bytes().splitlines()), 3)

    def test_each_sample_is_appended_without_rewriting_the_retained_window(self):
        retained = [self.sample(-5 * index) for index in range(4319, -1, -1)]
        self.history.append(retained[-1], retained)
        before = self.history.path.read_bytes()
        with patch.object(self.history, '_compact', wraps=self.history._compact) as compact, \
                patch('app.bootstrap.resource_history.os.fsync', wraps=__import__('os').fsync) as sync:
            for index in range(1, 11):
                self.tick += 5
                retained.append(self.sample(index * 5))
                self.history.append(retained[-1], retained)
            compact.assert_not_called()
            self.assertEqual(sync.call_count, 10)
        after = self.history.path.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertLess(len(after) - len(before), 1500)
        recovered = ResourceHistory(self.path, 6 * 3600).load(self.now + dt.timedelta(seconds=50))[0]
        self.assertEqual(recovered[-10:], retained[-10:])

    def test_compaction_removes_expired_rows_and_reader_ignores_them_before_compaction(self):
        self.history.retention = 10
        retained = [self.sample(-10), self.sample(-5), self.sample()]
        self.history.append(retained[-1], retained)
        self.assertEqual(self.history.load(self.now + dt.timedelta(seconds=6))[0], [retained[-1]])
        latest = self.sample(COMPACT_SECONDS)
        self.tick = COMPACT_SECONDS
        self.history.append(latest, [latest])
        self.assertEqual(self.history.load(latest['time_obj'])[0], [latest])
        self.assertEqual(len(self.history.path.read_bytes().splitlines()), 1)

    def test_incomplete_and_bad_lines_do_not_hide_valid_samples_and_are_repaired(self):
        first = self.sample()
        self.history.append(first, [first])
        with self.history.path.open('ab') as stream:
            stream.write(b'{bad}\n{"time":"2030-01-01 12:00:01","cpu":')
        restored = ResourceHistory(self.path, 6 * 3600)
        recovered, warning = restored.load(self.now)
        self.assertEqual(recovered, [first])
        self.assertTrue(warning)
        latest = self.sample(5)
        restored.append(latest, recovered + [latest])
        self.assertEqual(restored.load(self.now)[0], [first, latest])
        self.assertEqual(restored.load(self.now)[1], '')
        self.assertEqual(len(restored.path.read_bytes().splitlines()), 2)

    def test_failed_compaction_preserves_previous_file_and_next_write_recovers(self):
        first, latest = self.sample(), self.sample(5)
        self.history.append(first, [first])
        before = self.history.path.read_bytes()
        self.tick = COMPACT_SECONDS
        with patch('app.bootstrap.resource_history.os.replace', side_effect=OSError('simulated interrupted replace')):
            with self.assertRaises(OSError):
                self.history.append(latest, [first, latest])
        self.assertEqual(self.history.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        self.history.append(latest, [first, latest])
        self.assertEqual(self.history.load(self.now)[0], [first, latest])

    def test_partial_write_failure_recovers_all_in_memory_samples_on_retry(self):
        first, second, third = self.sample(), self.sample(5), self.sample(10)
        self.history.append(first, [first])
        with patch('app.bootstrap.resource_history.os.fsync', side_effect=OSError('simulated disk error')):
            with self.assertRaises(OSError):
                self.history.append(second, [first, second])
        self.history.append(third, [first, second, third])
        self.assertEqual(self.history.load(self.now)[0], [first, second, third])

    def test_reader_holds_one_generation_when_compaction_replaces_the_file(self):
        first, second = self.sample(), self.sample(5)
        self.history.append(first, [first])
        opened, proceed = threading.Event(), threading.Event()
        original_open = Path.open
        result, errors = [], []
        def open_file(path, mode='r', *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            if path == self.history.path and mode == 'rb' and threading.current_thread().name == 'history-reader':
                opened.set()
                if not proceed.wait(5):
                    stream.close()
                    raise TimeoutError('reader was not released')
            return stream
        def read():
            try:
                result.append(ResourceHistory(self.path, 6 * 3600).load(self.now)[0])
            except BaseException as exc:
                errors.append(exc)
        with patch.object(Path, 'open', open_file):
            thread = threading.Thread(target=read, name='history-reader')
            thread.start()
            self.assertTrue(opened.wait(5))
            try:
                self.tick = COMPACT_SECONDS
                self.history.append(second, [first, second])
            finally:
                proceed.set()
                thread.join(5)
        self.assertFalse(errors)
        self.assertEqual(result, [[first]])
        self.assertEqual(self.history.load(self.now)[0], [first, second])

    def test_web_reader_uses_appended_samples_with_unchanged_cursor_contract(self):
        first, latest = self.sample(-5), self.sample()
        self.history.append(first, [first])
        self.history.append(latest, [first, latest])
        from app import settings
        with patch.object(settings, 'WFS_ENABLE_SCHEDULER', False), \
                patch.object(settings, 'WFS_SCHEDULER_CONTROL_URL', 'http://control'), \
                patch.object(system_metrics, 'DATA_DIR', self.path.parent), \
                patch.object(system_metrics, 'business_now', return_value=self.now), \
                patch('app.bootstrap.resource_history.business_now', return_value=self.now):
            result = system_metrics.cpu_monitor_snapshot(after=first['time'])
        self.assertEqual(result['samples'], [self.public(latest)])
        self.assertEqual(result['cursor'], latest['time'])
        self.assertEqual(result['current'], 25)
        self.assertEqual(result['sample_interval_seconds'], 5)
        self.assertTrue(result['incremental'])
        self.assertFalse(result['warning'])

    def test_monitor_serializes_simultaneous_sample_and_persistence_operations(self):
        monitor = system_metrics._CpuMonitor()
        monitor._path = self.path
        monitor._last_times = (0, 0)
        counter = 0
        def cpu_times():
            nonlocal counter
            counter += 1
            return counter * 10, counter * 100
        with patch.object(system_metrics, '_read_cpu_times', side_effect=cpu_times), \
                patch.object(system_metrics, '_read_memory_percent', return_value=50), \
                patch.object(system_metrics, 'business_now', return_value=self.now):
            threads = [threading.Thread(target=monitor._append_sample) for _ in range(10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
        loaded, warning = ResourceHistory(self.path, 6 * 3600).load(self.now)
        self.assertEqual(len(loaded), 10)
        self.assertTrue(all(row['cpu'] == 90 for row in loaded))
        self.assertFalse(warning)


if __name__ == '__main__':
    unittest.main()
