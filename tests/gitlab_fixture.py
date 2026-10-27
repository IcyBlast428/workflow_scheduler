"""Disposable GitLab HTTP fixture shared by network and browser acceptance."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import hashlib
import io
import json
import threading
import zipfile
from urllib.parse import parse_qs, unquote, urlsplit

A, B, C = (letter * 40 for letter in 'abc')
TOKEN = 'disposable-gitlab-read-token'


def serve():
    calls = []
    repository = {'app/jobs/acceptance/slow/main.py': b'print("GITLAB_SLOW_V2")\n',
                  'app/jobs/acceptance/git_new/.wfs-task.json': b'{"task_id":"git_new","task_name":"GitLab new report","main_file":"main.py"}',
                  'app/jobs/acceptance/git_new/main.py': b'from helper import value\nprint(value,flush=True)\n',
                  'app/jobs/acceptance/git_new/helper.py': b'value="GITLAB_V1"\n'}
    def blob_id(content):
        return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
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
                value = {'name': 'main', 'commit': {'id': server.head}}
            elif suffix == '/repository/branches':
                value = [{'name': 'main', 'commit': {'id': B}}, {'name': 'feature/report', 'commit': {'id': C}}]
            elif suffix == '/repository/merge_base':
                value = {'id': A}
            elif suffix == '/repository/tree':
                files = sorted(server.repository.items())
                offset = (int(query.get('page', ['1'])[0]) - 1) * 100
                value = [{'id': blob_id(content), 'type': 'blob', 'mode': '100644', 'path': path, 'name': path.rsplit('/', 1)[-1]} for path, content in files[offset:offset+100]]
            elif suffix.startswith('/repository/blobs/'):
                content = next((content for content in server.repository.values() if blob_id(content) == suffix.rsplit('/', 1)[-1]), None)
                if content is None:
                    status, value = 404, {}
                else:
                    value = {'encoding': 'base64', 'content': base64.b64encode(content).decode(), 'size': len(content)}
            elif suffix == '/repository/archive.zip':
                result = io.BytesIO()
                with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for path, content in server.repository.items():
                        if path.startswith(query['path'][0] + '/'):
                            archive.writestr('project-' + server.head + '/' + path, content)
                body = result.getvalue()
                self.send_response(200); self.send_header('Content-Type', 'application/zip'); self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            elif suffix == '/repository/compare':
                def file(path, label):
                    return {'old_path': path, 'new_path': path, 'diff': '@@ -1 +1 @@\n-old-' + label + '\n+new-' + label + '\n'}
                value = {'diffs': [file('frontend/src/dashboard.vue', 'platform'),
                                   file('app/jobs/acceptance/slow/main.py', 'task'),
                                   file('app/common/report.py', 'shared')],
                         'commits': [{'id': query['to'][0], 'title': '报表更新', 'author_name': 'Fixture Developer', 'committed_date': '2026-10-27T10:00:00Z'}]}
                if server.compare_diffs is not None:
                    value['diffs'] = server.compare_diffs
            else:
                status, value = 404, {}
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.repository = repository
    server.head = B
    server.compare_diffs = None
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, 'http://127.0.0.1:' + str(server.server_address[1]), calls
