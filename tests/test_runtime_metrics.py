import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.bootstrap.runtime_metrics import Collector, MAX_SAMPLES, WINDOW_SECONDS, record_delay, measure
from app.bootstrap.execution_health import completion_summary


class RuntimeMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = __import__("time").time()
        self.directory = Path(self.temporary.name)
        self.collector = Collector(self.directory, clock=lambda: self.now)

    def test_merge_samples_before_calculating_percentiles(self):
        other = Collector(self.directory, clock=lambda: self.now)
        for value in range(1, 101):
            self.collector.record('database:connect', value)
        other.record('database:connect', 1000)
        other.flush()
        metric = self.collector.collect()['metrics']['database:connect']
        self.assertEqual(metric['samples'], 101)
        self.assertEqual(metric['p95_ms'], 96)
        self.assertEqual(metric['max_ms'], 1000)
        self.assertEqual(len(self.collector.collect()['sources']), 2)

    def test_independent_worker_exports_visible_samples(self):
        import subprocess
        import sys
        subprocess.run([sys.executable, '-c',
                        'from app.bootstrap.runtime_metrics import Collector;import sys;'
                        'c=Collector(sys.argv[1]);c.record("database:connect",123);c.flush()',
                        str(self.directory)], check=True, timeout=20)
        # Real process time can be slightly later than the test's initial clock.
        self.now = __import__('time').time()
        result = self.collector.collect()
        self.assertEqual(result['metrics']['database:connect']['p95_ms'], 123)
        self.assertNotEqual(result['sources'][0]['pid'], self.collector.pid)

    def test_sampling_is_bounded_and_expires(self):
        for value in range(1000):
            self.collector.record('task:start_delay', value)
        self.collector.flush()
        self.assertEqual(self.collector.collect()['metrics']['task:start_delay']['samples'], MAX_SAMPLES)
        self.now += WINDOW_SECONDS+1
        self.assertEqual(self.collector.collect()['metrics'], {})

    def test_corrupt_and_foreign_files_do_not_break_diagnostics(self):
        for index, content in enumerate(['[1]', '{', '{"version":1,"samples":{},"pid":1,"at":"bad"}']):
            (self.directory/f'process-1-{index:012x}.json').write_text(content, encoding='utf-8')
        (self.directory/'unrelated.json').write_text('private', encoding='utf-8')
        self.collector.record('database:query', 2)
        result = self.collector.collect()
        self.assertEqual(result['invalid_snapshots'], 3)
        self.assertEqual(result['metrics']['database:query']['p95_ms'], 2)

    def test_bad_samples_and_expired_process_are_excluded(self):
        item = {'version':1,'pid':123,'at':self.now,'samples':{'lock:admission':[[self.now,5], [self.now,float('nan')], ['bad',10], None]}}
        path = self.directory/'process-123-000000000001.json'
        path.write_text(json.dumps(item), encoding='utf-8')
        result = self.collector.collect()
        self.assertEqual(result['metrics']['lock:admission']['samples'], 1)
        self.assertEqual(result['invalid_snapshots'], 3)
        self.now += WINDOW_SECONDS+1
        self.assertEqual(self.collector.collect()['metrics'], {})

    def test_export_failure_is_reported_and_can_recover(self):
        self.collector.record('database:query', 2)
        with patch('app.bootstrap.runtime_metrics.os.replace', side_effect=PermissionError):
            self.collector.flush()
        self.assertTrue(self.collector.collect()['write_error'])
        self.assertTrue(self.collector.dirty)
        self.collector.flush()
        self.assertFalse(self.collector.collect()['write_error'])
        self.assertTrue((self.directory/self.collector.identifier).exists())

    def test_invalid_values_and_cardinality_are_bounded(self):
        for value in [-1, float('inf'), float('nan'), 'not-a-number']:
            self.collector.record('database:query', value)
        self.assertFalse(self.collector.collect()['metrics'])
        for index in range(200):
            self.collector.record(f'api:/route{index}', 1)
        self.assertEqual(len(self.collector.collect()['metrics']), 128)
        self.assertEqual(self.collector.collect()['dropped_metrics'], 72)

    def test_measure_preserves_operation_exception_and_records_wait(self):
        with patch('app.bootstrap.runtime_metrics.record') as record:
            with self.assertRaisesRegex(ValueError, 'original'):
                with measure('lock:admission'):
                    raise ValueError('original')
            self.assertEqual([call.args[0] for call in record.call_args_list], ['lock:admission','lock:all'])

    def test_bad_delay_timestamp_is_ignored(self):
        import datetime
        with patch('app.bootstrap.runtime_metrics.record') as record:
            record_delay('queue:dispatch_wait', 'legacy bad timestamp', datetime.datetime.now())
            record.assert_not_called()

    def test_failure_rate_excludes_cancellation_and_interruption(self):
        summary = completion_summary([(0,8), (1,1), (-9,1), (-15,5), (-1,4), (-10001,3), (-10002,2), (None,1)])
        self.assertEqual(summary['attempts'], 10)
        self.assertEqual(summary['failure_rate'], 20)
        self.assertEqual(summary['completed'], 25)
        self.assertIsNone(completion_summary([(-15,10)])['failure_rate'])


if __name__ == '__main__':
    unittest.main()
