"""Nacos 管理的本地协议、加密保存、字段映射和竞态回归。"""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

import requests
from app.bootstrap import nacos_bindings, nacos_config
from app.common.nacos import Nacos, NacosConflict, NacosError, NacosPublishUncertain, NacosTimeout
from nacos_fixture import NacosFixture
from test_nacos_cache import response

BINDING = {'namespace': 'production', 'group': 'BUSINESS', 'data_id': 'orders.json'}
DOCUMENT = {'host': 'db.invalid', 'port': 5432, 'db': 'orders', 'user': 'reader',
            'password': 'db-secret', 'other': {'kept': [1, 2]}}


class NacosConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / 'nacos.enc'
        env = patch.dict(os.environ, {'WFS_NACOS_CONFIG_FILE': str(self.target),
            'WFS_SECRET_KEY': 'fixture-encryption-key', 'WFS_CONNECTIONS_KEY': '',
            'WFS_NACOS_URL': '', 'WFS_NACOS_USERNAME': '', 'WFS_NACOS_PASSWORD': '',
            'WFS_NACOS_CONFIG_TTL_SECONDS': '60'})
        env.start(); self.addCleanup(env.stop)

    def form(self):
        return {**nacos_config.defaults(), 'url': 'https://nacos.invalid/nacos',
                'username': 'operator', 'password': 'private-password'}

    def test_encryption_public_redaction_and_blank_password_retention(self):
        public = nacos_config.save(self.form())
        self.assertNotIn('password', public)
        self.assertTrue(public['password_set'])
        self.assertNotIn(b'private-password', self.target.read_bytes())
        self.assertEqual(nacos_config.saved()['password'], 'private-password')
        self.assertEqual(nacos_config.save({**public, 'password': '', 'timeout': 12})['revision'], 2)
        self.assertEqual(nacos_config.saved()['password'], 'private-password')
        if os.name != 'nt':
            self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_only_one_concurrent_revision_can_save(self):
        nacos_config.save(self.form())
        value = nacos_config.saved()
        def save(_):
            try:
                nacos_config.save(value)
                return True
            except RuntimeError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(save, range(2))), [False, True])
        self.assertEqual(nacos_config.saved()['revision'], 2)

    def test_changed_endpoint_does_not_reuse_password(self):
        public = nacos_config.save(self.form())
        with self.assertRaisesRegex(ValueError, '重新填写密码'):
            nacos_config.save({**public, 'url': 'https://different.invalid/nacos'})
        self.assertEqual(nacos_config.saved()['revision'], 1)

    def test_anonymous_endpoint_change_discards_old_password_before_reenabling_auth(self):
        public = nacos_config.save(self.form())
        changed = nacos_config.save({**public, 'url': 'https://anonymous.invalid/nacos', 'auth_enabled': False})
        self.assertFalse(changed['password_set'])
        self.assertEqual(nacos_config.saved()['password'], '')
        with self.assertRaisesRegex(ValueError, '用户名和密码'):
            nacos_config.validate({**changed, 'auth_enabled': True, 'password': ''})
        self.assertFalse(nacos_config.saved()['auth_enabled'])
        replaced = nacos_config.save({**changed, 'auth_enabled': True, 'password': 'new-endpoint-secret'})
        self.assertTrue(replaced['password_set'])
        self.assertEqual(nacos_config.saved()['password'], 'new-endpoint-secret')

    def test_corrupt_file_and_wrong_key_fail_closed(self):
        nacos_config.save(self.form())
        with patch.dict(os.environ, WFS_SECRET_KEY='wrong-key'):
            with self.assertRaises(ValueError):
                nacos_config.saved()
        self.target.write_bytes(b'not encrypted')
        with self.assertRaises(ValueError):
            nacos_config.saved()

    def test_url_credentials_redirect_inputs_and_tls_validation(self):
        for url in ['https://user:secret@example.com', 'ftp://example.com', 'https://example.com?token=secret',
                    'https://example.com/#fragment', 'https://example.com\\@evil.invalid']:
            with self.assertRaises(ValueError):
                nacos_config.validate({**self.form(), 'url': url})
        with self.assertRaises(ValueError):
            nacos_config.validate({**self.form(), 'verify_tls': False, 'ca_file': '/tmp/cert'})


class NacosBindingTests(unittest.TestCase):
    def test_custom_fields_and_password_encoding_preserve_unknown_fields(self):
        binding = {**BINDING, 'password_encoding': 'base64', 'fields': {'database': 'database', 'password': 'pwd'}}
        original = {**DOCUMENT, 'database': 'orders', 'pwd': base64.b64encode(b'old-secret').decode()}
        updated = nacos_bindings.merge(binding, original, {'host': 'new.invalid', 'password': '新密码'})
        self.assertEqual(updated['other'], original['other'])
        self.assertEqual(updated['pwd'], base64.b64encode('新密码'.encode()).decode())
        self.assertEqual(original['host'], 'db.invalid')
        self.assertEqual(updated['password'], 'db-secret')  # 未映射字段不删除。

    def test_plain_password_is_not_guessed_as_base64(self):
        client = unittest.mock.Mock()
        doc = {**DOCUMENT, 'password': 'dGVzdA=='}
        client.read_document.return_value = {'document': doc, 'md5': 'a' * 32}
        self.assertEqual(nacos_bindings.read(BINDING, client=client)['values']['password'], 'dGVzdA==')

    def test_bad_mapping_base64_and_nonobject_rejected(self):
        for fields in [{'host': 'db'}, {'host': ''}, {'bad_field': 'x'}]:
            with self.assertRaises(ValueError):
                nacos_bindings.validate({**BINDING, 'fields': fields})
        with self.assertRaises(ValueError):
            nacos_bindings.merge(BINDING, [], {})
        with self.assertRaises(ValueError):
            nacos_bindings.merge({**BINDING, 'password_encoding': 'base64'}, DOCUMENT, {})


class NacosHttpTests(unittest.TestCase):
    def setUp(self):
        Nacos.clear_cache(); self.addCleanup(Nacos.clear_cache)
        self.fixture = self.enterContext(NacosFixture())
        self.md5 = self.fixture.put(BINDING, DOCUMENT)
        self.client = Nacos(config=self.fixture.config)

    def test_read_publish_and_cache_invalidation_over_real_http(self):
        first = self.client.read_document(BINDING)
        self.assertEqual(first['md5'], self.md5)
        result = nacos_bindings.publish(BINDING, {'host': 'changed.invalid'}, self.md5, client=self.client)
        current = nacos_bindings.read(BINDING, client=self.client)
        self.assertEqual(current['values']['host'], 'changed.invalid')
        self.assertEqual(current['document']['other'], DOCUMENT['other'])
        self.assertEqual(current['md5'], result['md5'])
        self.assertEqual(self.fixture.calls['publish'], 1)

    def test_cas_conflict_after_pre_read_is_never_overwritten(self):
        self.fixture.before_publish = lambda: self.fixture.put(BINDING, {**DOCUMENT, 'user': 'other-writer'})
        with self.assertRaises(NacosConflict):
            self.client.publish_document(BINDING, {**DOCUMENT, 'user': 'my-edit'}, self.md5)
        self.assertEqual(self.client.read_document(BINDING, True)['document']['user'], 'other-writer')
        self.assertEqual(self.fixture.calls['publish'], 1)

    def test_no_blind_write_or_overwrite_with_stale_md5(self):
        for checksum in ['', 'bad']:
            with self.assertRaises(ValueError):
                self.client.publish_document(BINDING, DOCUMENT, checksum)
        with self.assertRaises(NacosConflict):
            self.client.publish_document(BINDING, DOCUMENT, '0' * 32)
        self.assertEqual(self.fixture.calls['publish'], 0)

    def test_publish_waits_briefly_for_nacos_read_cache_to_catch_up(self):
        self.fixture.delayed_reads = 2
        result = self.client.publish_document(BINDING, {**DOCUMENT, 'host': 'eventual.invalid'}, self.md5)
        self.assertEqual(result['md5'], self.client.read_document(BINDING)['md5'])
        self.assertEqual(self.fixture.calls['publish'], 1)
        self.assertEqual(self.fixture.delayed_reads, 0)

    def test_network_drop_after_commit_is_confirmed_without_retry(self):
        self.fixture.publish_mode = 'drop_after_write'
        result = self.client.publish_document(BINDING, {**DOCUMENT, 'host': 'committed.invalid'}, self.md5)
        self.assertEqual(result['md5'], self.client.read_document(BINDING)['md5'])
        self.assertEqual(self.fixture.calls['publish'], 1)

    def test_unknown_write_result_is_explicit_and_not_retried(self):
        self.fixture.publish_mode = 'drop_before_write'
        with self.assertRaises(NacosPublishUncertain):
            self.client.publish_document(BINDING, {**DOCUMENT, 'host': 'not-committed.invalid'}, self.md5)
        self.assertEqual(self.fixture.calls['publish'], 1)
        self.assertFalse(self.client.cache.configs)

    def test_probe_is_readonly_and_anonymous_probe_requires_config(self):
        self.assertEqual(self.client.test_connection()['verified'], 'authentication')
        self.assertEqual(self.client.test_connection(BINDING)['verified'], 'config_read')
        self.assertEqual(self.fixture.calls['publish'], 0)
        self.fixture.auth_enabled = False
        client = Nacos(config={**self.fixture.config, 'auth_enabled': False})
        with self.assertRaises(ValueError):
            client.test_connection()
        self.assertEqual(client.test_connection(BINDING)['verified'], 'config_read')

    def test_expired_read_does_not_return_stale_content(self):
        self.client.read_document(BINDING)
        self.fixture.get_status = 503
        with self.assertRaises(NacosError):
            self.client.read_document(BINDING, force_refresh=True)
        self.assertFalse(self.client.cache.configs)

    def test_tls_settings_are_part_of_cache_identity(self):
        other = Nacos(config={**self.fixture.config, 'verify_tls': False})
        self.assertIsNot(other.cache, self.client.cache)

    def test_errors_never_echo_secrets_or_response_body(self):
        with patch('app.common.nacos.requests.get', side_effect=requests.Timeout('token=private-token password=private-pass')):
            with self.assertRaises(NacosError) as raised:
                self.client.read_document(BINDING)
        self.assertNotIn('private-', str(raised.exception))
        self.assertIsNone(raised.exception.request)
        self.assertIsNone(raised.exception.response)

    def test_redirect_is_not_followed_and_large_response_is_rejected(self):
        redirected = response(status=302, text='private-secret')
        redirected.headers['Location'] = 'https://other.invalid'
        with patch('app.common.nacos.requests.get', return_value=redirected) as request:
            with self.assertRaises(NacosError):
                self.client.read_document(BINDING)
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
        with patch('app.common.nacos.requests.get', return_value=response(text='x' * (1024 * 1024 + 1))):
            with self.assertRaises(NacosError):
                self.client.read_document(BINDING)

    def test_streaming_deadline_stops_drip_and_late_silence(self):
        for mode in ('drip', 'late_silence'):
            with self.subTest(mode=mode):
                class SlowHandler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass
                    def do_GET(self):
                        if mode == 'late_silence':
                            time.sleep(.35)
                        payload = b'{"hello":"a slow response"}'
                        self.send_response(200)
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        try:
                            for byte in payload:
                                self.wfile.write(bytes([byte])); self.wfile.flush()
                                time.sleep(.1 if mode == 'drip' else 1.2)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                server = ThreadingHTTPServer(('127.0.0.1', 0), SlowHandler)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    client = Nacos(config={'url': 'http://127.0.0.1:' + str(server.server_port),
                                           'auth_enabled': False, 'timeout': 1})
                    started = time.monotonic()
                    with self.assertRaises(NacosTimeout):
                        client.read_document({'data_id': 'slow.json'})
                    self.assertLess(time.monotonic() - started, 1.3)
                    self.assertFalse(client.cache.configs)
                finally:
                    server.shutdown(); server.server_close(); worker.join(timeout=3)

    def test_json_duplicate_keys_arrays_and_nonfinite_rejected(self):
        for raw in ['{"password":"one","password":"two"}', '[]', '{"port":NaN}']:
            self.fixture.put(BINDING, raw)
            with self.assertRaises(ValueError):
                self.client.read_document(BINDING, force_refresh=True)
            self.assertFalse(self.client.cache.configs)


if __name__ == '__main__':
    unittest.main()
