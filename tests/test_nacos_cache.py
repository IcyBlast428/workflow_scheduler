"""Exercise public Nacos handles without contacting the production service."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import unittest
from unittest.mock import patch

import requests
from app.common.nacos import Nacos


def response(status=200, value=None, text=None):
    result = requests.Response()
    result.status_code = status
    result._content = (text if text is not None else json.dumps(value)).encode()
    result.encoding = 'utf-8'
    return result


class NacosCacheTests(unittest.TestCase):
    def setUp(self):
        Nacos.clear_cache()
        self.environment = patch.dict(os.environ, {
            'WFS_NACOS_URL': 'https://nacos.invalid',
            'WFS_NACOS_USERNAME': 'test', 'WFS_NACOS_PASSWORD': 'test-secret',
            'WFS_NACOS_CONFIG_TTL_SECONDS': '60',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(Nacos.clear_cache)
        self.clock = patch('app.common.nacos.time.monotonic', return_value=100)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.post_patch = patch('app.common.nacos.requests.post', return_value=response(
            value={'accessToken': 'token-one', 'tokenTtl': 300}))
        self.post = self.post_patch.start()
        self.addCleanup(self.post_patch.stop)
        self.get_patch = patch('app.common.nacos.requests.get', return_value=response(
            value={'database': {'host': 'original'}}))
        self.get = self.get_patch.start()
        self.addCleanup(self.get_patch.stop)

    def read(self, **kwargs):
        return Nacos().get_nacos_configs(data_id='database.json', **kwargs)

    def test_handles_share_cache_and_values_are_isolated(self):
        first = self.read()
        first['database']['host'] = 'changed-by-caller'
        self.assertEqual(self.read()['database']['host'], 'original')
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.get.call_count, 1)

    def test_config_and_token_expire_independently(self):
        self.read()
        self.now.return_value = 161
        self.read()
        self.assertEqual(self.get.call_count, 2)
        self.assertEqual(self.post.call_count, 1)
        self.now.return_value = 371
        self.read()
        self.assertEqual(self.post.call_count, 2)

    def test_parallel_first_reads_are_coalesced(self):
        barrier = threading.Barrier(8)
        def reader(_):
            barrier.wait(timeout=5)
            return self.read()
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(len(list(executor.map(reader, range(8)))), 8)
        self.assertEqual(self.get.call_count, 1)
        self.assertEqual(self.post.call_count, 1)

    def test_namespace_group_and_credentials_are_isolated(self):
        for tenant, group in [('a', 'g'), ('b', 'g'), ('a', 'h')]:
            self.read(tenant=tenant, group=group)
        self.assertEqual(self.get.call_count, 3)
        self.assertEqual(self.post.call_count, 1)
        with patch.dict(os.environ, WFS_NACOS_PASSWORD='rotated'):
            self.read(tenant='a', group='g')
        self.assertEqual(self.get.call_count, 4)
        self.assertEqual(self.post.call_count, 2)

    def test_auth_rejection_refreshes_once_then_fails_closed(self):
        self.get.side_effect = [response(401), response(value={'ok': True})]
        self.assertTrue(self.read()['ok'])
        self.assertEqual(self.post.call_count, 2)
        self.get.side_effect = [response(403), response(403)]
        with self.assertRaises(requests.HTTPError):
            self.read(force_refresh=True)
        self.assertFalse(Nacos().cache.token)
        self.assertEqual(self.get.call_count, 4)
        self.get.side_effect = None
        self.read()
        self.assertEqual(self.post.call_count, 4)

    def test_expired_data_is_not_returned_on_network_failure(self):
        self.read()
        self.now.return_value = 161
        self.get.side_effect = requests.Timeout('offline')
        with self.assertRaises(requests.Timeout):
            self.read()
        self.assertFalse(Nacos().cache.configs)

    def test_force_refresh_failure_does_not_leave_old_config(self):
        self.read()
        self.get.return_value = response(text='invalid json')
        with self.assertRaises(ValueError):
            self.read(force_refresh=True)
        self.get.return_value = response(value={'fresh': True})
        self.assertTrue(self.read()['fresh'])
        self.assertEqual(self.get.call_count, 3)

    def test_zero_ttl_and_text_compatibility(self):
        self.get.return_value = response(text='plain configuration')
        with patch.dict(os.environ, WFS_NACOS_CONFIG_TTL_SECONDS='0'):
            for _ in range(2):
                self.assertEqual(Nacos().get_nacos_configs(data_id='config.text'), 'plain configuration')
        self.assertEqual(self.get.call_count, 2)
        self.assertEqual(self.post.call_count, 1)

    def test_invalidate_forces_new_login_and_config(self):
        self.read()
        Nacos().invalidate(data_id='database.json')
        self.read()
        self.assertEqual(self.get.call_count, 2)
        self.assertEqual(self.post.call_count, 2)

    def test_invalid_ttl_rejected(self):
        for value in ['nan', '-1', '3601', 'garbage']:
            with patch.dict(os.environ, WFS_NACOS_CONFIG_TTL_SECONDS=value):
                with self.assertRaises(ValueError):
                    Nacos()


if __name__ == '__main__':
    unittest.main()
