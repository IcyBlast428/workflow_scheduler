"""IE is rejected before login, APIs and SPA resources are served."""
import unittest
import test_local_integration
from app import create_app


class BrowserSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_app().test_client()

    def test_ie_and_compatibility_mode_receive_static_notice(self):
        agents = ['Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1)',
                  'Mozilla/5.0 (compatible; MSIE 10.0; Trident/6.0)',
                  'Mozilla/5.0 (Windows NT 10.0; Trident/7.0; rv:11.0) like Gecko']
        for agent in agents:
            for path in ('/', '/admin/', '/viewer/tasks', '/admin/deep-link', '/static/example.js'):
                with self.subTest(agent=agent, path=path), self.client.get(path, headers={'User-Agent':agent}) as response:
                    self.assertEqual(response.status_code, 403)
                    self.assertIn('Chrome 内核浏览器', response.text)
                    self.assertNotIn('<script', response.text)
                    self.assertNotIn('id="app"', response.text)
                    self.assertIn('no-store', response.headers['Cache-Control'])
                    self.assertIn('User-Agent', response.headers['Vary'])

    def test_ie_cannot_login_or_execute_an_api_request(self):
        for path in ('/api/user/login', '/api/taskinfo/call_task'):
            with self.subTest(path=path), self.client.post(path, json={}, headers={'User-Agent':'Trident/7.0'}) as response:
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json['code'], 'UNSUPPORTED_BROWSER')
                self.assertIn('Chrome', response.json['message'])

    def test_modern_browsers_and_monitoring_are_unaffected(self):
        for agent in ('Chrome/141.0.0.0', 'Chrome/141.0.0.0 Edg/141.0.0.0', 'Firefox/143.0', 'Python-urllib/3.12', ''):
            with self.subTest(agent=agent), self.client.get('/', headers={'User-Agent':agent}) as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn('id="app"', response.text)


if __name__ == '__main__':
    unittest.main()
