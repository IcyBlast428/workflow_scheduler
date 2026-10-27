"""Disposable GitLab HTTP fixture shared by network and browser acceptance."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, unquote, urlsplit

A, B, C = (letter * 40 for letter in 'abc')
TOKEN = 'disposable-gitlab-read-token'


def serve():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            suffix = unquote(parsed.path).removeprefix('/api/v4/projects/team/project')
            calls.append((self.command, suffix, query))
            status = 200
            if self.headers.get('PRIVATE-TOKEN') != TOKEN:
                status, value = 401, {'message': 'unauthorized'}
            elif not suffix:
                value = {'path_with_namespace': 'team/project', 'default_branch': 'main'}
            elif suffix == '/repository/branches/main':
                value = {'name': 'main', 'commit': {'id': B}}
            elif suffix == '/repository/branches':
                value = [{'name': 'main', 'commit': {'id': B}}, {'name': 'feature/report', 'commit': {'id': C}}]
            elif suffix == '/repository/merge_base':
                value = {'id': A}
            elif suffix == '/repository/compare':
                def file(path, label):
                    return {'old_path': path, 'new_path': path, 'diff': '@@ -1 +1 @@\n-old-' + label + '\n+new-' + label + '\n'}
                value = {'diffs': [file('frontend/src/dashboard.vue', 'platform'),
                                   file('app/jobs/acceptance/slow/main.py', 'task'),
                                   file('app/common/report.py', 'shared')],
                         'commits': [{'id': query['to'][0], 'title': '报表更新', 'author_name': 'Fixture Developer', 'committed_date': '2026-10-27T10:00:00Z'}]}
            else:
                status, value = 404, {}
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, 'http://127.0.0.1:' + str(server.server_address[1]), calls
