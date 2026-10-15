import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.bootstrap import snapshot_cache as cache


class SnapshotCacheTests(unittest.TestCase):
    def test_unrelated_keys_progress_while_one_refresh_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test did not release factory')
            return {'value': 1}
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(cache.cached, uuid.uuid4().hex, 30, slow)
            try:
                self.assertTrue(entered.wait(2))
                fast = pool.submit(cache.cached, uuid.uuid4().hex, 30, lambda: 'ready')
                self.assertEqual(fast.result(timeout=2), 'ready')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), {'value': 1})

    def test_same_key_coalesces_and_returns_independent_results(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def factory():
            calls.append(1)
            entered.set()
            release.wait(5)
            return {'values': [1]}
        key = uuid.uuid4().hex
        with ThreadPoolExecutor(4) as pool:
            first = pool.submit(cache.cached, key, 30, factory)
            self.assertTrue(entered.wait(2))
            others = [pool.submit(cache.cached, key, 30, factory) for _ in range(3)]
            release.set()
            result = first.result(timeout=2)
            result['values'].append(2)
            self.assertTrue(all(item.result(timeout=2) == {'values': [1]} for item in others))
        self.assertEqual(len(calls), 1)

    def test_invalidation_during_refresh_and_factory_failure_allow_retry(self):
        key = uuid.uuid4().hex
        def invalidated():
            cache.invalidate()
            return 'old'
        self.assertEqual(cache.cached(key, 30, invalidated), 'old')
        self.assertEqual(cache.cached(key, 30, lambda: 'new'), 'new')
        key = uuid.uuid4().hex
        def failing():
            raise ValueError('query failed')
        with self.assertRaises(ValueError):
            cache.cached(key, 30, failing)
        self.assertEqual(cache.cached(key, 30, lambda: 'recovered'), 'recovered')
