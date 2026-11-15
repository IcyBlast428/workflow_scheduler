"""可复用的本地 Nacos 2.x HTTP 替身；仅监听 loopback，不连接生产配置中心。"""
from contextlib import AbstractContextManager
from hashlib import md5
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from urllib.parse import parse_qs, urlsplit


class NacosFixture(AbstractContextManager):
    def __init__(self):
        self.documents = {}
        self.lock = threading.Lock()
        self.calls = {'login': 0, 'get': 0, 'publish': 0}
        self.auth_enabled = True
        self.username, self.password = 'fixture-user', 'fixture-password'
        self.token = 'fixture-token'
        self.publish_mode = ''
        self.before_publish = None
        self.get_status = 200
        self.delayed_reads = 0
        self.previous_document = None
        self.server = None

    def put(self, binding, document):
        key = (binding.get('namespace', ''), binding['data_id'], binding.get('group', 'DEFAULT_GROUP'))
        content = document if isinstance(document, str) else json.dumps(document, ensure_ascii=False)
        with self.lock:
            self.documents[key] = content
        return md5(content.encode()).hexdigest()

    def __enter__(self):
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # 请求可能含凭据，测试也不记录请求原文。

            def send(self, status, content):
                content = content.encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def authorized(self):
                return not fixture.auth_enabled or self.headers.get('Authorization') == 'Bearer ' + fixture.token

            def do_GET(self):
                fixture.calls['get'] += 1
                if not self.authorized():
                    self.send(403, 'denied'); return
                if fixture.get_status != 200:
                    self.send(fixture.get_status, 'fixture upstream failure'); return
                args = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                key = tuple(args.get(field, [''])[0] for field in ('tenant', 'dataId', 'group'))
                with fixture.lock:
                    content = fixture.documents.get(key)
                    if fixture.delayed_reads and fixture.previous_document is not None:
                        content = fixture.previous_document
                        fixture.delayed_reads -= 1
                self.send(404 if content is None else 200, content or '')

            def do_POST(self):
                args = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', 0))).decode(), keep_blank_values=True)
                if urlsplit(self.path).path.endswith('/v1/auth/login'):
                    fixture.calls['login'] += 1
                    if args.get('username') != [fixture.username] or args.get('password') != [fixture.password]:
                        self.send(403, 'fixture auth denied'); return
                    self.send(200, json.dumps({'accessToken': fixture.token, 'tokenTtl': 300})); return
                fixture.calls['publish'] += 1
                if not self.authorized():
                    self.send(403, 'fixture permission denied'); return
                key = tuple(args.get(field, [''])[0] for field in ('tenant', 'dataId', 'group'))
                if fixture.before_publish:
                    fixture.before_publish()
                with fixture.lock:
                    old = fixture.documents.get(key)
                    if old is None or md5(old.encode()).hexdigest() != self.headers.get('casMd5'):
                        self.send(500, json.dumps({'code': 500, 'errorCode': 20005})); return
                    fixture.previous_document = old
                    if fixture.publish_mode != 'drop_before_write':
                        fixture.documents[key] = args['content'][0]
                if fixture.publish_mode in ('drop_after_write', 'drop_before_write'):
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send(200, 'true')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port) + '/nacos'
        self.config = dict(url=self.url, username=self.username, password=self.password, timeout=1)
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
