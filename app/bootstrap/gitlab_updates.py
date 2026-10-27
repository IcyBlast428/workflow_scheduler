"""Read-only GitLab discovery. Scans never merge, deploy or execute source code."""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import threading
import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
import uuid

import requests
from app.bootstrap.global_vars import DATA_DIR

SHA = re.compile(r'(?:[a-f0-9]{40}|[a-f0-9]{64})\Z')
DEFAULTS = dict(enabled=False, url='', project='', target='main', token='', ca_bundle='',
                allow_http=False, interval=300, task_roots=['app/jobs'],
                shared_paths=['app/common', 'requirements.txt', 'requirements-databases.txt'],
                platform_commit='', tasks=[], revision=0)
_start_lock = threading.Lock()
_started = False


class GitLabError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@contextmanager
def store():
    path = Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'gitlab-updates.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        if os.name != 'nt':
            path.chmod(0o600)
        db.executescript('''
            CREATE TABLE IF NOT EXISTS configuration(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scan_lease(id INTEGER PRIMARY KEY, token TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS acknowledgements(username TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
        ''')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _cipher():
    from app.bootstrap.connection_settings import _cipher as derived_cipher
    return derived_cipher('gitlab-updates')


def _config(db):
    row = db.execute('SELECT revision,payload FROM configuration WHERE id=1').fetchone()
    if not row:
        return copy.deepcopy(DEFAULTS)
    try:
        value = json.loads(_cipher().decrypt(row[1]))
    except Exception:
        raise GitLabError('GitLab 配置无法解密，请恢复原配置密钥。', 503) from None
    return {**value, 'revision': row[0]}


def configuration():
    with store() as db:
        return _config(db)


def public_configuration():
    value = configuration()
    from app.bootstrap.code_version import _release
    revision = _release()
    return {**{key: val for key, val in value.items() if key != 'token'},
            'token_set': bool(value['token']), 'running_commit': revision if SHA.fullmatch(revision) else ''}


def _text(value, label, maximum=200):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise GitLabError(label + '格式或长度无效。')
    return value.strip()


def _path(value):
    value = _text(value, '目录', 500)
    if value.startswith('/'):
        raise GitLabError('目录必须是仓库内的相对路径。')
    value = value.rstrip('/')
    parts = PurePosixPath(value).parts
    if not value or '\\' in value or any(p in ('.', '..', '.git') for p in value.split('/')) or ':' in value:
        raise GitLabError('目录必须是仓库内的相对路径，不能包含上级目录或 .git。')
    return '/'.join(parts)


def _paths(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise GitLabError('目录规则需要 1 至 20 项。')
    return list(dict.fromkeys(_path(path) for path in value))


def save_configuration(form):
    with store() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = _config(db)
        if type(form.get('revision')) is not int or form['revision'] != previous['revision']:
            raise GitLabError('设置已被修改，请刷新后重试。', 409)
        value = {**previous, **{key: form[key] for key in DEFAULTS if key in form and key not in ('token', 'revision')}}
        if type(value['enabled']) is not bool or type(value['allow_http']) is not bool:
            raise GitLabError('启用开关格式无效。')
        raw_url = _text(value['url'], 'GitLab 地址', 1000)
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError:
            raise GitLabError('GitLab 地址端口无效。') from None
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or '\\' in raw_url
                or any(p in ('.', '..') for p in parsed.path.split('/')) or '%' in parsed.path
                or (port is not None and not 1 <= port <= 65535)):
            raise GitLabError('请填写 GitLab HTTP/HTTPS 根地址，不包含账号、密码或参数。')
        if parsed.scheme == 'http' and not value['allow_http']:
            raise GitLabError('请使用 HTTPS；内网 HTTP 连接需要明确启用对应选项。')
        value['url'] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))
        value['project'] = _text(value['project'], '项目', 300).strip('/')
        if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_./-]*', value['project']) or any(p in ('', '.', '..') for p in value['project'].split('/')):
            raise GitLabError('项目请填写数字 ID 或 group/project。')
        value['target'] = _text(value['target'], '目标分支')
        if not value['target'] or any(char.isspace() for char in value['target']):
            raise GitLabError('请填写有效的目标分支。')
        if type(value['interval']) is not int or not 60 <= value['interval'] <= 3600:
            raise GitLabError('自动检查间隔应为 60 至 3600 秒。')
        token = form.get('token', '')
        if not isinstance(token, str) or len(token) > 2048 or any(ord(c) <= 32 for c in token):
            raise GitLabError('访问令牌格式无效。')
        value['token'] = '' if form.get('clear_token') is True else token or previous['token']
        value['ca_bundle'] = _text(value['ca_bundle'], 'CA 路径', 1024)
        if value['ca_bundle'] and (parsed.scheme != 'https' or not Path(value['ca_bundle']).is_file()):
            raise GitLabError('CA 文件需为服务可读的文件，并用于 HTTPS。')
        value['task_roots'] = _paths(value['task_roots'])
        value['shared_paths'] = _paths(value['shared_paths'])
        value['platform_commit'] = _text(value['platform_commit'], '平台已部署提交', 64)
        if value['platform_commit'] and not SHA.fullmatch(value['platform_commit']):
            raise GitLabError('平台基线需要完整 Git 提交 SHA。')
        if not isinstance(value['tasks'], list) or len(value['tasks']) > 100:
            raise GitLabError('最多绑定 100 个任务。')
        tasks = []
        for item in value['tasks']:
            if not isinstance(item, dict):
                raise GitLabError('任务绑定格式无效。')
            pid = _text(item.get('pid', ''), '任务编号')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', pid):
                raise GitLabError('请为目录选择有效任务编号。')
            commit = _text(item.get('commit', ''), '任务已发布提交', 64)
            if commit and not SHA.fullmatch(commit):
                raise GitLabError('任务基线需要完整 Git 提交 SHA。')
            path = _path(item.get('path', ''))
            if any(t['pid'] == pid or _under(path, t['path']) or _under(t['path'], path) for t in tasks):
                raise GitLabError('任务编号和绑定目录不能重复或互相包含。')
            tasks.append(dict(pid=pid, path=path, commit=commit))
        value['tasks'] = tasks
        revision = previous['revision'] + 1
        value['revision'] = revision
        db.execute('INSERT OR REPLACE INTO configuration VALUES(1,?,?)', (revision, _cipher().encrypt(json.dumps(value).encode())))
        db.execute('DELETE FROM snapshot')
        db.execute('DELETE FROM scan_lease')
    return public_configuration()


def _under(path, prefix):
    return path == prefix or path.startswith(prefix + '/')


def _category(path, config):
    for item in config['tasks']:
        if _under(path, item['path']):
            return 'task', item['pid']
    for root in config['task_roots']:
        if _under(path, root):
            suffix = path[len(root):].strip('/').split('/')
            return 'task', root + '/' + '/'.join(suffix[:2])
    if any(_under(path, root) for root in config['shared_paths']):
        return 'shared', ''
    return 'platform', ''


class Client:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.trust_env = False
        self.project = quote(config['project'], safe='')

    def get(self, suffix='', params=None):
        url = self.config['url'] + '/api/v4/projects/' + self.project + suffix
        headers = {'PRIVATE-TOKEN': self.config['token']} if self.config['token'] else {}
        try:
            with self.session.get(url, params=params, headers=headers, timeout=(5, 10), stream=True,
                                  allow_redirects=False, verify=self.config['ca_bundle'] or True) as response:
                messages = {401: 'GitLab 认证失败，请检查只读令牌。', 403: 'GitLab 访问被拒绝，请检查项目权限。',
                            404: 'GitLab 项目、分支或提交不存在，或当前凭据没有访问权限。', 429: 'GitLab 请求限流，将在下次检查重试。'}
                if response.status_code != 200:
                    raise GitLabError(messages.get(response.status_code, 'GitLab 返回异常状态，请检查地址与服务。'), 502)
                chunks, size = [], 0
                for block in response.iter_content(65536):
                    size += len(block)
                    if size > 4 * 1024**2:
                        raise GitLabError('GitLab 比对结果过大，请在 GitLab 中查看完整差异。', 502)
                    chunks.append(block)
                return json.loads(b''.join(chunks)), response.headers
        except GitLabError:
            raise
        except requests.RequestException:
            raise GitLabError('无法连接 GitLab，请检查网络、地址和 CA 证书。', 502) from None
        except (ValueError, TypeError):
            raise GitLabError('GitLab 返回了无效数据。', 502) from None

    def close(self):
        self.session.close()


def _sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise GitLabError('GitLab 返回的提交编号无效。', 502)
    return value


def _safe_text(value, maximum=500):
    return ''.join(c for c in str(value or '') if ord(c) >= 32)[:maximum]


def comparison(client, base, head, straight, warnings):
    raw, _ = client.get('/repository/compare', {'from': base, 'to': head, 'straight': str(straight).lower()})
    if not isinstance(raw, dict) or not isinstance(raw.get('diffs'), list):
        raise GitLabError('GitLab 返回的差异格式无效。', 502)
    incomplete = bool(raw.get('compare_timeout') or raw.get('overflow') or len(raw['diffs']) > 200)
    files, remaining = [], 250000
    for value in raw['diffs'][:200]:
        if not isinstance(value, dict):
            raise GitLabError('GitLab 文件差异格式无效。', 502)
        old = _safe_text(value.get('old_path'), 1000)
        new = _safe_text(value.get('new_path'), 1000)
        text = value.get('diff') or ''
        if not isinstance(text, str):
            raise GitLabError('GitLab 文件差异内容无效。', 502)
        truncated = bool(value.get('too_large') or value.get('collapsed') or len(text) > min(80000, remaining))
        text = text[:max(0, min(80000, remaining))]
        remaining -= len(text)
        files.append(dict(old_path=old, path=new or old, diff=text, truncated=truncated,
                          kind='deleted' if value.get('deleted_file') else 'added' if value.get('new_file') else 'renamed' if value.get('renamed_file') else 'modified'))
    if incomplete:
        warnings.append('部分比对达到 GitLab 或平台显示上限，请到 GitLab 核对完整差异；分类可能不完整。')
    commits = raw.get('commits') if isinstance(raw.get('commits'), list) else []
    return dict(files=files, incomplete=incomplete, fetched_at=time.time(), commits=[dict(sha=_sha(c['id']), title=_safe_text(c.get('title')),
                author=_safe_text(c.get('author_name')), date=_safe_text(c.get('committed_date'))) for c in commits[-20:] if isinstance(c, dict) and SHA.fullmatch(str(c.get('id', '')))])


def _item(config, web, kind, branch, base, head, compared, select=None, pid=''):
    files = []
    for source in compared['files']:
        if select and not select(source):
            continue
        categories, tasks = set(), set()
        # Renames/deletions classify both ends so movement cannot hide its impact.
        for path in (source['path'], source['old_path']):
            if not path:
                continue
            category, task_id = _category(path, config)
            categories.add(category)
            if task_id:
                tasks.add(task_id)
        files.append({**source, 'categories': sorted(categories), 'tasks': sorted(tasks)})
    if not files and not compared['incomplete']:
        return None
    identifier = hashlib.sha256(json.dumps([kind, branch, base, head, pid]).encode()).hexdigest()[:32]
    return dict(id=identifier, kind=kind, branch=branch, target=config['target'], base=base, head=head, pid=pid,
                categories=sorted({c for f in files for c in f['categories']}),
                tasks=sorted({t for f in files for t in f['tasks']}), files=files,
                incomplete=compared['incomplete'], commits=compared['commits'],
                compare_url=web + '/-/compare/' + base + '...' + head + '?straight=' + ('false' if kind == 'branch' else 'true'),
                merge_url=web + '/-/merge_requests?' + urlencode({'state': 'opened', 'source_branch': branch, 'target_branch': config['target']}) if kind == 'branch' else '')


def scan(config, previous=None):
    """Bounded, incremental comparisons pinned to full source and target SHAs."""
    client, warnings, items = Client(config), [], []
    cache = (previous or {}).get('comparisons', {})
    ancestry = dict((previous or {}).get('ancestry', {}))
    used = {}
    deadline = time.monotonic() + 45
    count = 0
    try:
        project, _ = client.get()
        namespace = project.get('path_with_namespace', config['project']) if isinstance(project, dict) else ''
        if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_./-]*', str(namespace)) or any(p in ('', '.', '..') for p in str(namespace).split('/')):
            raise GitLabError('GitLab 返回的项目路径无效。', 502)
        web = config['url'] + '/' + quote(namespace, safe='/')
        target, _ = client.get('/repository/branches/' + quote(config['target'], safe=''))
        target_sha = _sha(target['commit']['id'])
        branches = []
        for page in (1, 2):
            values, headers = client.get('/repository/branches', {'per_page': 50, 'page': page})
            if not isinstance(values, list):
                raise GitLabError('GitLab 分支列表格式无效。', 502)
            branches.extend(values[:50])
            if len(values) < 50 and not headers.get('X-Next-Page'):
                break
        if len(branches) >= 100:
            warnings.append('本项目分支较多，仅检查 API 排序中的前 100 个分支，请清理旧分支或到 GitLab 核对。')

        def compare(base, head, straight):
            nonlocal count
            key = '|'.join([base, head, str(straight)])
            if key in cache and (not cache[key].get('incomplete') or time.time() - cache[key].get('fetched_at', 0) < 60):
                result = cache[key]
                if result.get('incomplete'):
                    warnings.append('部分比对显示不完整，请到 GitLab 查看完整差异。')
            else:
                if count >= 25 or time.monotonic() > deadline:
                    warnings.append('本轮比对达到数量或时间上限，结果可能不完整；后续检查将复用缓存继续比对。')
                    return None
                result = comparison(client, base, head, straight, warnings)
                count += 1
            used[key] = result
            return result

        unique_branches = {branch.get('name'): branch for branch in branches if isinstance(branch, dict) and isinstance(branch.get('name'), str)}
        for branch in unique_branches.values():
            name = branch.get('name')
            if not isinstance(name, str) or name == config['target']:
                continue
            head = _sha(branch['commit']['id'])
            if head == target_sha:
                continue
            result = compare(target_sha, head, False)
            if result is not None:
                item = _item(config, web, 'branch', _safe_text(name, 300), target_sha, head, result)
                if item:
                    items.append(item)
        baselines = [('platform', config['platform_commit'], None)] + [('task', item['commit'], item) for item in config['tasks']]
        for kind, base, task in baselines:
            if not base:
                warnings.append('尚未确认平台已部署提交，仅检查平台待合并分支。' if kind == 'platform' else '任务 ' + task['pid'] + ' 尚未确认已发布提交。')
                continue
            if base == target_sha:
                continue
            try:
                ancestry_key = base + '|' + target_sha
                if ancestry_key not in ancestry:
                    if count >= 25 or time.monotonic() > deadline:
                        warnings.append('部署基线检查达到本轮上限，请稍后再次检查。')
                        continue
                    ancestor, _ = client.get('/repository/merge_base', {'refs[]': [base, target_sha]})
                    ancestry[ancestry_key] = _sha(ancestor['id']) == base
                    count += 1
                if not ancestry[ancestry_key]:
                    warnings.append(('平台' if task is None else '任务 ' + task['pid']) + '目标分支未包含确认的已部署提交，请核对基线与分支历史。')
                    continue
                result = compare(base, target_sha, True)
                if result is None:
                    continue
                def select(file):
                    paths = (file['path'], file['old_path'])
                    return any(_under(path, task['path']) for path in paths if path) if task else any(_category(path, config)[0] in ('platform', 'shared') for path in paths if path)
                item = _item(config, web, kind, config['target'], base, target_sha, result, select, task['pid'] if task else '')
                if item:
                    items.append(item)
            except GitLabError as exc:
                warnings.append(('平台' if task is None else '任务 ' + task['pid']) + '已部署基线比对失败：' + str(exc))
        if not config['tasks']:
            warnings.append('尚未绑定任务已发布提交；任务只展示待合并差异，已合并的待发布更新需要配置基线。')
        active_baselines = {base + '|' + target_sha for _, base, _ in baselines if base}
        return dict(items=items, comparisons=used, ancestry={key: val for key, val in ancestry.items() if key in active_baselines}, warnings=list(dict.fromkeys(warnings)), error='',
                    checked_at=time.time(), revision=config['revision'], project_url=web, target_sha=target_sha)
    except (KeyError, TypeError, AttributeError):
        raise GitLabError('GitLab 返回的数据缺少必要字段。', 502) from None
    finally:
        client.close()


def _snapshot(db):
    row = db.execute('SELECT payload FROM snapshot WHERE id=1').fetchone()
    return json.loads(row[0]) if row else dict(items=[], warnings=[], error='', checked_at=None, comparisons={})


def state(username, brief=False):
    with store() as db:
        config, data = _config(db), _snapshot(db)
        lease = db.execute('SELECT expires FROM scan_lease WHERE id=1').fetchone()
        acknowledged = db.execute('SELECT fingerprint FROM acknowledgements WHERE username=?', (username,)).fetchone()
    fingerprint = hashlib.sha256(json.dumps([config['revision'], sorted(item['id'] for item in data['items'])]).encode()).hexdigest()
    result = dict(enabled=config['enabled'], checked_at=data['checked_at'], error=data['error'], warnings=data['warnings'],
                  scanning=bool(lease and lease[0] > time.time()), fingerprint=fingerprint,
                  unread=bool(data['items'] and (not acknowledged or acknowledged[0] != fingerprint)),
                  count=len(data['items']), pending_merge=sum(i['kind'] == 'branch' for i in data['items']),
                  pending_release=sum(i['kind'] != 'branch' for i in data['items']))
    if not brief:
        result['items'] = [{**{key: value for key, value in item.items() if key != 'files'},
                            'files': [{key: value for key, value in file.items() if key != 'diff'} for file in item['files']]} for item in data['items']]
    return result


def acknowledge(username, fingerprint):
    if fingerprint != state(username, True)['fingerprint']:
        raise GitLabError('更新列表发生变化，请重新查看后标记已读。', 409)
    with store() as db:
        db.execute('INSERT OR REPLACE INTO acknowledgements VALUES(?,?)', (username, fingerprint))


def diff(identifier, index):
    with store() as db:
        data = _snapshot(db)
    item = next((item for item in data['items'] if item['id'] == identifier), None)
    if not item:
        raise GitLabError('更新已变化，请刷新列表后重试。', 409)
    if type(index) is not int or not 0 <= index < len(item['files']):
        raise GitLabError('文件不存在。', 404)
    return {**item['files'][index], 'base': item['base'], 'head': item['head']}


def _worker(token, config):
    previous = dict(items=[], warnings=[], error='', checked_at=None, comparisons={})
    try:
        with store() as db:
            previous = _snapshot(db)
        result = scan(config, previous)
    except Exception as exc:
        result = {**previous, 'error': str(exc) if isinstance(exc, GitLabError) else 'GitLab 检查失败，请重试或检查连接设置。', 'checked_at': time.time()}
    with store() as db:
        db.execute('BEGIN IMMEDIATE')
        lease = db.execute('SELECT token FROM scan_lease WHERE id=1').fetchone()
        if not lease or lease[0] != token or _config(db)['revision'] != config['revision']:
            return
        db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(result),))
        db.execute('DELETE FROM scan_lease')


def request_scan(force=False):
    with store() as db:
        db.execute('BEGIN IMMEDIATE')
        config, previous = _config(db), _snapshot(db)
        if not config['enabled']:
            raise GitLabError('请先保存并启用 GitLab 连接。')
        now = time.time()
        lease = db.execute('SELECT expires FROM scan_lease WHERE id=1').fetchone()
        if lease and lease[0] > now:
            return False
        if previous['checked_at'] and now - previous['checked_at'] < (10 if force else config['interval']):
            return False
        token = uuid.uuid4().hex
        db.execute('INSERT OR REPLACE INTO scan_lease VALUES(1,?,?)', (token, now + 180))
    threading.Thread(target=_worker, args=(token, config), daemon=True, name='wfs-gitlab-scan').start()
    return True


def start():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    def loop():
        while True:
            try:
                if configuration()['enabled']:
                    request_scan()
            except Exception:
                # External GitLab availability must never affect scheduler readiness.
                pass
            time.sleep(5)
    threading.Thread(target=loop, daemon=True, name='wfs-gitlab-monitor').start()
