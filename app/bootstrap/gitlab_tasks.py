"""Discover complete task trees; publish immutable, verified GitLab snapshots.

No Git checkout, reset or clean touches runtime code or business output files.
Only complete target-branch inventories can authorize a deletion.
"""
import base64
import hashlib
import io
import json
import stat
import time
from urllib.parse import quote
import zipfile

from app.bootstrap import gitlab_updates as updates, task_packages as packages


def project_key(config):
    return hashlib.sha256(json.dumps([config['url'], config['project']]).encode()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def catalog(client, config, sha, previous=None):
    if previous and previous.get('sha') == sha and previous.get('complete'):
        return previous
    deadline = time.monotonic() + 45
    entries = []
    for page in range(1, 101):
        if time.monotonic() > deadline:
            raise updates.GitLabError('仓库目录读取超时，请减少扫描范围或稍后重试。')
        values, headers = client.get('/repository/tree', {'ref': sha, 'recursive': 'true', 'per_page': 100, 'page': page})
        if not isinstance(values, list):
            raise updates.GitLabError('GitLab 目录清单无效。')
        entries.extend(values)
        if len(values) < 100 and not headers.get('X-Next-Page'):
            break
    else:
        raise updates.GitLabError('仓库目录超过 10000 项，不能确认任务删除。')
    groups = {}
    bindings = {item['path']: item['pid'] for item in config['tasks']}
    for entry in entries:
        path = updates._path(entry.get('path', ''))
        if entry.get('type') == 'tree':
            continue
        directory = next((p for p in bindings if updates._under(path, p)), None)
        if not directory:
            root = next((p for p in sorted(config['task_roots'], key=len, reverse=True) if updates._under(path, p)), None)
            suffix = path[len(root) + 1:].split('/') if root else []
            if len(suffix) < 3:
                continue
            directory = root + '/' + '/'.join(suffix[:2])
        relative = path[len(directory) + 1:]
        if not relative:
            continue
        groups.setdefault(directory, []).append(dict(path=relative, id=updates._sha(entry.get('id')), mode=entry.get('mode'), type=entry.get('type')))
    tasks = []
    identities = set()
    for directory, files in sorted(groups.items()):
        if time.monotonic() > deadline:
            raise updates.GitLabError('任务身份读取超时，请稍后重试。')
        python = sorted(f['path'] for f in files if f['path'].endswith('.py'))
        identity = next((f for f in files if f['path'] == '.wfs-task.json'), None)
        metadata = {}
        if identity:
            raw, _ = client.get('/repository/blobs/' + identity['id'])
            try:
                if raw.get('encoding') != 'base64' or raw.get('size', 999999) > 4096:
                    raise ValueError()
                metadata = json.loads(base64.b64decode(raw['content'], validate=True).decode('utf-8-sig'))
                if not isinstance(metadata, dict):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise updates.GitLabError(directory + ' 的 .wfs-task.json 无效。') from None
        group, folder = directory.split('/')[-2:]
        pid = bindings.get(directory) or metadata.get('task_id') or group + '__' + folder
        if not isinstance(pid, str) or not packages.IDENTIFIER.fullmatch(pid) or pid in identities:
            raise updates.GitLabError('任务编号无效或重复，请核对 .wfs-task.json 和目录绑定。')
        identities.add(pid)
        entry = metadata.get('main_file') or ('main.py' if 'main.py' in python else python[0] if len(python) == 1 else '')
        error = ''
        if not python:
            error = '任务目录已没有 Python 入口，请恢复入口或删除整个任务目录。'
        elif entry not in python:
            error = '存在多个入口，请在 .wfs-task.json 中指定 main_file。'
        try:
            packages._name(group, '分类')
            packages._name(folder, '目录')
            for file in files:
                if file['path'] != '.wfs-task.json':
                    packages._path(file['path'])
                if file['type'] != 'blob' or file['mode'] not in ('100644', '100755'):
                    raise packages.PackageError('不支持符号链接、子模块或特殊文件。')
        except packages.PackageError as exc:
            error = str(exc)
        name = metadata.get('task_name') or folder
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise updates.GitLabError('任务名称无效。')
        tasks.append(dict(pid=pid, path=directory, group_name=group, folder_name=folder, task_name=name,
                          main_file=entry, files=files, fingerprint=_digest(sorted(files, key=lambda f: f['path'])), error=error,
                          discoverable=bool(python or identity)))
    return dict(complete=True, error='', tasks=tasks, sha=sha)


def _context():
    with updates.store() as db:
        config, snapshot = updates._config(db), updates._snapshot(db)
    return config, snapshot


def changes():
    config, snapshot = _context()
    inventory = snapshot.get('task_catalog', {})
    error = snapshot.get('error') or inventory.get('error', '')
    complete = bool(config['enabled'] and not error and inventory.get('complete') and snapshot.get('revision') == config['revision'])
    if not config['enabled']:
        return dict(enabled=False, items=[], error='', checked_at=None, complete=False)
    if not inventory:
        error = '请先在代码更新页完成 GitLab 检查。'
    if snapshot.get('checked_at') and time.time() - snapshot['checked_at'] > max(900, config['interval'] * 3):
        complete, error = False, 'GitLab 检查结果已过期，请重新检查。'
    managed = packages.registry()
    key = project_key(config)
    items = []
    paths = {item['path'] for item in inventory.get('tasks', [])}
    remote_ids = {item['pid'] for item in inventory.get('tasks', [])}
    for remote in inventory.get('tasks', []):
        record = managed.get(remote['pid'])
        if not remote['discoverable'] and not record:
            continue
        source = (record or {}).get('git_source') or {}
        if record and record.get('deleted_at'):
            continue  # An explicit local deletion must not silently restore a task.
        if source and source.get('project_key') != key:
            continue
        if source.get('fingerprint') == remote['fingerprint'] and source.get('path') == remote['path']:
            continue
        collision = next((r for r in managed.values() if r['pid'] != remote['pid'] and
                          r['group_name'] == remote['group_name'] and r['folder_name'] == remote['folder_name']), None)
        item = {**{k: v for k, v in remote.items() if k not in ('files', 'discoverable')},
                'kind': 'update' if record and record.get('active_version') else 'new',
                'revision': (record or {}).get('revision', 0), 'active_version': (record or {}).get('active_version'),
                'sha': inventory.get('sha'), 'file_count': len(remote['files'])}
        if collision:
            item['error'] = '该目录已属于另一任务，请核对稳定任务编号或目录绑定。'
        items.append(item)
    if complete:
        for record in managed.values():
            source = record.get('git_source') or {}
            if not source:
                # Legacy deployments can establish provenance through an
                # explicitly confirmed baseline. A missing or mistyped binding
                # alone is never evidence that the repository deleted a task.
                binding = next((t for t in config['tasks'] if t['pid'] == record['pid'] and t['commit']), None)
                proof = next((i for i in snapshot.get('items', []) if binding and i['kind'] == 'task' and
                              i['pid'] == record['pid'] and i['base'] == binding['commit'] and i['head'] == inventory['sha'] and
                              not i['incomplete'] and any(f['kind'] == 'deleted' and updates._under(f['old_path'], binding['path']) for f in i['files'])), None)
                if binding and proof:
                    source = dict(project_key=key, path=binding['path'])
            path = source.get('path', '')
            covered = any(updates._under(path, p) for p in config['task_roots']) or any(t['path'] == path for t in config['tasks'])
            if source.get('project_key') == key and covered and path not in paths and record['pid'] not in remote_ids and not record.get('deleted_at'):
                items.append(dict(pid=record['pid'], task_name=record['task_name'], group_name=record['group_name'],
                                  folder_name=record['folder_name'], path=path, kind='delete', revision=record['revision'],
                                  active_version=record.get('active_version'), sha=inventory['sha'], fingerprint='', error='', file_count=0))
    for item in items:
        item['id'] = _digest([config['revision'], item])
        item['blocked'] = not complete or bool(item['error'])
    return dict(enabled=True, items=sorted(items, key=lambda i: (i['kind'] != 'new', i['path'])),
                error=error, checked_at=snapshot.get('checked_at'), complete=complete, target=config['target'])


def _candidate(identifier):
    current = changes()
    item = next((i for i in current['items'] if i['id'] == identifier), None)
    if not item or item['blocked']:
        raise packages.PackageError((item or {}).get('error') or current['error'] or '任务变更已变化，请刷新后重新确认。', 409)
    return item


def _target(config, sha, client):
    target, _ = client.get('/repository/branches/' + quote(config['target'], safe=''))
    if updates._sha(target['commit']['id']) != sha or updates.configuration()['revision'] != config['revision']:
        raise packages.PackageError('GitLab 目标分支或连接设置已变化，请重新检查并确认差异。', 409)


def _archive(client, item, remote):
    blob, _ = client.get('/repository/archive.zip', {'sha': item['sha'], 'path': item['path'], 'include_lfs_blobs': 'false'},
                         binary=True, maximum=packages.limits()['upload_bytes'])
    expected = {f['path']: f for f in remote['files']}
    result = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive, zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as normalized:
            entries = archive.infolist()
            if len(entries) > packages.limits()['files'] * 2 or sum(f.file_size for f in entries) > packages.limits()['expanded_bytes']:
                raise packages.PackageError('GitLab 任务文件数或大小超过限制。', 413)
            files = [f for f in entries if not f.is_dir()]
            if not files:
                raise packages.PackageError('GitLab 任务归档为空。')
            # GitLab versions include different wrapper paths. Accept only one
            # prefix whose entire resulting file set exactly matches the tree.
            prefixes = {files[0].filename[:-len(path)] for path in expected if files[0].filename.endswith(path)}
            prefix = next((p for p in prefixes if all(f.filename.startswith(p) for f in files) and
                           {f.filename[len(p):] for f in files} == set(expected)), None)
            if prefix is None or len(files) != len(expected):
                raise packages.PackageError('GitLab 归档与已确认的文件清单不一致。', 409)
            for member in files:
                name = member.filename[len(prefix):]
                if member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                    raise packages.PackageError('GitLab 归档包含不支持的文件。')
                content = archive.read(member)
                algorithm = hashlib.sha1 if len(expected[name]['id']) == 40 else hashlib.sha256
                if algorithm(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest() != expected[name]['id']:
                    raise packages.PackageError('GitLab 文件内容校验失败，未创建发布版本。', 409)
                if content.startswith(b'version https://git-lfs.github.com/spec/v1'):
                    raise packages.PackageError('此版本不支持 Git LFS 文件，请使用普通仓库文件。')
                if name != '.wfs-task.json':
                    packages._path(name)
                    normalized.writestr(name, content)
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
        raise packages.PackageError('GitLab 任务归档损坏。') from None
    return result.getvalue()


def stage(identifier, actor):
    item = _candidate(identifier)
    if item['kind'] == 'delete':
        raise packages.PackageError('此变更应执行删除操作。')
    config, snapshot = _context()
    client = updates.Client(config)
    try:
        _target(config, item['sha'], client)
        remote = next(r for r in snapshot['task_catalog']['tasks'] if r['pid'] == item['pid'])
        blob = _archive(client, item, remote)
        _target(config, item['sha'], client)
    finally:
        client.close()
    from app.bootstrap.core import _configuration_lock
    with _configuration_lock:
        _candidate(identifier)  # Recheck registry CAS after network requests.
        managed = packages.registry()
        record = managed.get(item['pid'])
        if record and (record.get('pending') or record.get('deleted_at')):
            raise packages.PackageError('任务正在发布或已删除，请刷新。', 409)
        if record is None:
            from app.bootstrap.timebase import business_now
            record = dict(pid=item['pid'], group_name=item['group_name'], folder_name=item['folder_name'],
                          task_name=item['task_name'], active_version=None, deleted_at=None, origin='gitlab',
                          created_at=str(business_now()), created_by=actor, revision=0)
        data = packages._create(record, blob=blob, entry=item['main_file'], actor=actor,
                                note='GitLab ' + config['target'] + ' @ ' + item['sha'], archive_layout='preserve')
        if item['pid'] not in managed:
            record = packages._write_task(record, expected=0)
            data['base_revision'] = record['revision']
        data['git_source'] = dict(project_key=project_key(config), path=item['path'], sha=item['sha'],
                                  fingerprint=item['fingerprint'], group_name=item['group_name'], folder_name=item['folder_name'])
        packages._write_release(data)
        return data


def validate_release(data):
    source = data.get('git_source')
    if not source:
        return
    config = updates.configuration()
    if not config['enabled'] or source['project_key'] != project_key(config):
        raise packages.PackageError('GitLab 项目配置已变化，请重新获取版本。', 409)
    client = updates.Client(config)
    try:
        _target(config, source['sha'], client)
    except updates.GitLabError as exc:
        raise packages.PackageError(str(exc), exc.status) from None
    finally:
        client.close()


def remove(identifier, actor):
    item = _candidate(identifier)
    if item['kind'] != 'delete':
        raise packages.PackageError('GitLab 中的任务目录仍存在，不能按删除变更处理。', 409)
    config = updates.configuration()
    client = updates.Client(config)
    try:
        _target(config, item['sha'], client)
    finally:
        client.close()
    _candidate(identifier)
    return packages.recycle(item['pid'], item['revision'], actor)
