"""Versioned task DDL drafts. SQL is documentation; never executed."""
import base64
import difflib
import hashlib
import json
import uuid
from urllib.parse import quote, urlencode
from app.bootstrap import admission, gitlab_updates as git, gitlab_tasks
from app.bootstrap.timebase import business_now
FILE = 'ddl/schema.sql'

def spec(pid):
    from app.bootstrap.task_loader import discover_task_specs
    item = next((s for s in discover_task_specs() if s['pid'] == pid), None)
    if not item:
        raise ValueError('任务不存在或已删除。')
    return item

def tags_all():
    with admission.store() as db:
        return {k[5:]: json.loads(v) for k, v in db.execute("SELECT key,payload FROM settings WHERE key LIKE 'tags:%'")}

def tags(pid):
    return admission.policy('tags:' + pid, {'revision': 0, 'tags': []})

def validate_tags(values):
    if not isinstance(values, list) or len(values) > 20 or any((not isinstance(v, str) or not v.strip() or len(v.strip()) > 40 or any((ord(c) < 32 for c in v)) for v in values)):
        raise ValueError('最多 20 个标签，每个标签 1–40 个字符。')
    return list(dict.fromkeys((v.strip() for v in values)))

def _put(key, revision, value, actor):
    with admission.store() as db:
        db.execute('BEGIN')
        row = db.execute('SELECT payload FROM settings WHERE key=?', (key,)).fetchone()
        old = json.loads(row[0]) if row else {'revision': 0}
        if type(revision) is not int or revision != old['revision']:
            raise RuntimeError('内容已被修改，请刷新后重试。')
        value = dict(value, revision=revision + 1, actor=actor, at=str(business_now()))
        db.replace('settings', ('key', 'payload'), (key, json.dumps(value, ensure_ascii=False)))
        if key.startswith('ddl:'):
            db.execute('INSERT INTO ddl_history VALUES(?,?,?)', (key[4:], value['revision'], json.dumps(value, ensure_ascii=False)))
    return value

def save_tags(pid, form, actor):
    spec(pid)
    return _put('tags:' + pid, form.get('revision'), {'tags': validate_tags(form.get('tags'))}, actor)

def published(pid):
    from app.bootstrap.task_source import read_source, SourceError
    try:
        result = read_source(spec(pid), FILE)
        if result.get('kind') != 'text':
            raise ValueError('已发布 DDL 无法作为文本读取。')
        return result['content']
    except SourceError as exc:
        if exc.status == 404:
            return ''
        raise

def current(pid):
    value = admission.policy('ddl:' + pid, None)
    if value is not None:
        return value
    content = published(pid)
    return dict(revision=0, content=content, base=content, actor='', at='', note='')

def history(pid):
    with admission.store() as db:
        rows = db.execute('SELECT payload FROM ddl_history WHERE pid=? ORDER BY revision DESC LIMIT 100', (pid,)).fetchall()
    return [json.loads(r[0]) for r in rows]

def diff(before, after):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/' + FILE, tofile='b/' + FILE))

def save(pid, form, actor, remote_base=None):
    content = form.get('content')
    note = form.get('note', '')
    if not isinstance(content, str) or len(content.encode('utf-8')) > 65536 or '\x00' in content:
        raise ValueError('DDL 最多 64 KiB，不能包含空字符。')
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
        raise ValueError('请填写 1–500 字的修改说明。')
    old = current(pid)
    return _put('ddl:' + pid, form.get('revision'), dict(content=content, base=old['base'] if remote_base is None else remote_base, note=note.strip()), actor)

def remote(pid):
    from app.bootstrap.task_packages import task
    record = task(pid)
    source = record.get('git_source') or {}
    config = git.configuration()
    if not config['enabled'] or source.get('project_key') != gitlab_tasks.project_key(config):
        raise ValueError('任务未关联当前 GitLab 项目，请先通过 GitLab 发布任务。')
    path = git._path(source.get('path', ''))
    if not any((git._under(path, root) for root in config['task_roots'])) and (not any((t['pid'] == pid and t['path'] == path for t in config['tasks']))):
        raise ValueError('任务路径不在配置的 GitLab 范围内。')
    client = git.Client(config)
    try:
        branch, _ = client.get('/repository/branches/' + quote(config['target'], safe=''))
        sha = git._sha(branch['commit']['id'])
        inventory = gitlab_tasks.catalog(client, config, sha)
        item = next((i for i in inventory['tasks'] if i['path'] == path), None)
        if not item:
            raise ValueError('GitLab 目标分支已无此任务，请先核对代码更新。')
        file = next((f for f in item['files'] if f['path'] == FILE), None)
        content = ''
        if file:
            raw, _ = client.get('/repository/blobs/' + file['id'], maximum=200000)
            if raw.get('size', 999999) > 65536:
                raise ValueError('GitLab DDL 超过 64 KiB。')
            content = base64.b64decode(raw['content'], validate=True).decode('utf-8-sig').replace('\r\n', '\n')
        return (config, sha, path, content, bool(file))
    finally:
        client.close()

def preview(pid, revision):
    value = current(pid)
    if value['revision'] != revision:
        raise RuntimeError('草稿版本已改变，请刷新。')
    config, sha, path, content, exists = remote(pid)
    if content != value['base']:
        raise RuntimeError('GitLab DDL 已改变。请先载入 GitLab 最新版本，再合并你的修改。')
    if content == value['content']:
        raise ValueError('没有需要提交的 DDL 修改。')
    token = uuid.uuid4().hex
    data = dict(pid=pid, revision=revision, sha=sha, path=path, exists=exists, config_revision=config['revision'], content=value['content'], created=str(business_now()), branch='wfs/ddl/' + token)
    with admission.store() as db:
        db.execute('INSERT INTO settings VALUES(?,?)', ('ddl-preview:' + token, json.dumps(data)))
    return dict(token=token, diff=diff(content, value['content']), branch=data['branch'], target=config['target'])

def submit(pid, token, actor):
    data = admission.policy('ddl-preview:' + str(token), None)
    if not data or data['pid'] != pid:
        raise ValueError('请重新预览 GitLab 差异。')
    import datetime as dt
    if (business_now() - dt.datetime.fromisoformat(data['created'])).total_seconds() > 600:
        raise RuntimeError('预览已超过 10 分钟，请重新预览。')
    config, sha, path, _, _ = remote(pid)
    if current(pid)['revision'] != data['revision'] or sha != data['sha'] or config['revision'] != data['config_revision'] or (path != data['path']):
        raise RuntimeError('草稿或 GitLab 已变化，请重新预览。')
    key = 'ddl-submit:' + token
    with admission.store() as db:
        db.execute('BEGIN')
        if db.execute('SELECT 1 FROM settings WHERE key=?', (key,)).fetchone():
            raise RuntimeError('此提交已尝试，请到 GitLab 核对分支，不会重复发送。')
        db.execute('INSERT INTO settings VALUES(?,?)', (key, json.dumps(dict(status='unknown', actor=actor, branch=data['branch']))))
    client = git.Client(config)
    try:
        with client.session.post(config['url'] + '/api/v4/projects/' + client.project + '/repository/commits', headers={'PRIVATE-TOKEN': config['token']}, json=dict(branch=data['branch'], start_sha=sha, commit_message='Task DDL ' + pid + ' · ' + actor, actions=[dict(action='update' if data['exists'] else 'create', file_path=path + '/' + FILE, content=data['content'])]), timeout=(5, 30), allow_redirects=False, verify=config['ca_bundle'] or True) as response:
            if response.status_code != 201:
                raise RuntimeError('GitLab 未确认提交成功。请检查分支、令牌写入权限及 GitLab 记录，再重新预览；平台不会自动重发。')
            result = response.json()
            commit = git._sha(result['id'])
    finally:
        client.close()
    project = config['url'] + '/' + config['project']
    receipt = dict(status='submitted', commit=commit, branch=data['branch'], actor=actor, at=str(business_now()), url=project + '/-/merge_requests/new?' + urlencode({'merge_request[source_branch]': data['branch'], 'merge_request[target_branch]': config['target']}))
    with admission.store() as db:
        db.execute('UPDATE settings SET payload=? WHERE key=?', (json.dumps(receipt), key))
    return receipt
