"""Versioned task packages. Published code and environments are never overwritten.

The database is the registry; disk holds releases, independently of platform Git.
Activation has a durable intent and a scheduler acknowledgement. An interrupted
intent is conservatively rolled back during scheduler startup.
"""
import ast
import datetime as dt
import difflib
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unicodedata
import uuid
import zipfile

from app.bootstrap.database import GaussDB
from app.bootstrap.global_vars import DATA_DIR

logger = logging.getLogger(__name__)
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$')
VERSION = re.compile(r'^[a-f0-9]{32}$')
EXCLUDED = {'.git', '.venv', '__pycache__', '.env', '.wfs-task.json'}
_preparing = {}
_prepare_lock = threading.Lock()
_slots = threading.BoundedSemaphore(2)


class PackageError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def limits():
    return {'upload_bytes': int(os.environ.get('WFS_PACKAGE_UPLOAD_MB', '64')) * 1024**2,
            'expanded_bytes': int(os.environ.get('WFS_PACKAGE_EXPANDED_MB', '256')) * 1024**2,
            'files': int(os.environ.get('WFS_PACKAGE_MAX_FILES', '2000'))}


def storage_root():
    return Path(os.environ.get('WFS_TASK_RELEASE_DIR', str(Path(DATA_DIR) / 'task-packages'))).resolve()


def release_dir(pid, version):
    if not isinstance(pid, str) or not isinstance(version, str) or not IDENTIFIER.fullmatch(pid) or not VERSION.fullmatch(version):
        raise PackageError('任务或版本编号无效。')
    root = storage_root()
    path = root / pid / 'releases' / version
    for current in (root / pid, root / pid / 'releases', path):
        if current.is_symlink():
            raise PackageError('版本目录不能使用符号链接。', 403)
    path.resolve().relative_to(root)
    return path


def registry():
    with GaussDB() as db:
        return {row['pid']: {**json.loads(row['payload']), 'revision': int(row['revision'])}
                for row in db.execute_query_sql('SELECT pid,revision,payload FROM wfs_package_tasks', return_json=True)}


def task(pid):
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT revision,payload FROM wfs_package_tasks WHERE pid=?', params=(pid,), return_json=True)
    if not rows:
        raise PackageError('任务尚未纳入版本管理。', 404)
    return {**json.loads(rows[0]['payload']), 'revision': int(rows[0]['revision'])}


def release(pid, version):
    release_dir(pid, version)
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT payload FROM wfs_task_releases WHERE pid=? AND version=?', params=(pid, version))
    if not rows:
        raise PackageError('版本不存在。', 404)
    return json.loads(rows[0][0])


def _write_task(record, expected=None):
    """CAS protects registry writes across processes as well as API requests."""
    with GaussDB() as db:
        db.begin_transaction()
        try:
            if not db._local_sqlite:
                db.execute_sql('LOCK TABLE wfs_package_tasks IN EXCLUSIVE MODE')
            rows = db.execute_query_sql('SELECT revision FROM wfs_package_tasks WHERE pid=?', params=(record['pid'],))
            revision = int(rows[0][0]) if rows else 0
            if expected is not None and revision != expected:
                raise PackageError('任务版本已发生变化，请刷新后重新预览。', 409)
            data = {**record, 'revision': revision + 1}
            if rows:
                db.execute_sql('UPDATE wfs_package_tasks SET revision=?,payload=? WHERE pid=?',
                               params=(data['revision'], json.dumps(data, ensure_ascii=False), data['pid']))
            else:
                db.execute_sql('INSERT INTO wfs_package_tasks(pid,revision,payload) VALUES(?,?,?)',
                               params=(data['pid'], data['revision'], json.dumps(data, ensure_ascii=False)))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
    from app.bootstrap.task_loader import invalidate_task_cache
    invalidate_task_cache()
    return data


def _write_release(record, insert=False):
    with GaussDB() as db:
        if insert:
            db.execute_sql('INSERT INTO wfs_task_releases(pid,version,created_at,payload) VALUES(?,?,?,?)',
                           params=(record['pid'], record['version'], record['created_at'], json.dumps(record, ensure_ascii=False)))
        else:
            db.execute_sql('UPDATE wfs_task_releases SET payload=? WHERE pid=? AND version=?',
                           params=(json.dumps(record, ensure_ascii=False), record['pid'], record['version']))
    return record


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[\w-]{1,80}', value, re.UNICODE) or value.startswith('_'):
        raise PackageError(label + '只能使用文字、数字、下划线或连字符，最多 80 个字符。')
    return value


def _path(name):
    if not isinstance(name, str) or len(name) > 512 or any(c in name for c in ('\\', ':', '\0')):
        raise PackageError('压缩包包含无效文件路径。')
    parts = name.rstrip('/').split('/')
    if PurePosixPath(name).is_absolute() or len(parts) > 32 or any(p in ('', '.', '..') for p in parts):
        raise PackageError('压缩包不能包含绝对路径或上级目录。')
    # Reject names which alias other paths on Windows or create device files.
    for part in parts:
        if part.endswith((' ', '.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part):
            raise PackageError('压缩包包含系统保留文件名。')
        if any(ord(char) < 32 or char in '<>"|?*' for char in part):
            raise PackageError('压缩包包含无效文件名。')
    if any(p.casefold() in EXCLUDED or p.casefold().startswith('.env.') for p in parts):
        raise PackageError('请移除 .git、.venv、缓存、身份文件和本地 .env 配置后上传。')
    return '/'.join(unicodedata.normalize('NFC', p) for p in parts)


def _unpack(blob, code, entry=''):
    bound = limits()
    if len(blob) > bound['upload_bytes']:
        raise PackageError('任务包超过上传大小限制。', 413)
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            if len(entries) > bound['files'] * 2 or sum(e.file_size for e in entries) > bound['expanded_bytes']:
                raise PackageError('解压大小或文件数超过限制。', 413)
            files = []
            seen = set()
            for entry in entries:
                name = _path(entry.filename)
                key = name.casefold()
                mode = entry.external_attr >> 16
                if entry.flag_bits & 1 or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise PackageError('压缩包不能包含加密文件、符号链接或特殊文件。')
                if key in seen:
                    raise PackageError('压缩包包含重复文件路径。')
                seen.add(key)
                if not entry.is_dir():
                    files.append((entry, name))
            if not files or len(files) > bound['files']:
                raise PackageError('任务包为空或文件数超过限制。')
            # A single wrapper directory is conventional ZIP export structure.
            prefix = files[0][1].split('/')[0]
            strip = entry not in {name for _, name in files} and all('/' in name and name.split('/')[0] == prefix for _, name in files)
            total = 0
            for entry, name in files:
                name = name.split('/', 1)[1] if strip else name
                destination = code / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open('xb') as output:
                    while chunk := source.read(65536):
                        total += len(chunk)
                        if total > bound['expanded_bytes']:
                            raise PackageError('解压大小超过限制。', 413)
                        output.write(chunk)
    except PackageError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise PackageError('无法读取 ZIP，可能损坏或存在文件与目录冲突。') from exc


def _manifest(code):
    result = []
    total = 0
    for path in sorted(code.rglob('*')):
        if path.is_symlink():
            raise PackageError('任务代码不能包含符号链接。')
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if len(result) >= limits()['files'] or total > limits()['expanded_bytes']:
            raise PackageError('文件数或大小超过限制。')
        if path.suffix == '.py' and size > 2 * 1024**2:
            raise PackageError('单个 Python 文件不能超过 2 MiB。')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if path.suffix == '.py':
            try:
                ast.parse(path.read_bytes(), filename=str(path.relative_to(code)))
            except (SyntaxError, ValueError) as exc:
                raise PackageError('Python 语法检查失败：' + str(exc)) from exc
        result.append({'path': path.relative_to(code).as_posix(), 'size': size, 'sha256': digest.hexdigest()})
    if not result or len(result) > limits()['files'] or sum(item['size'] for item in result) > limits()['expanded_bytes']:
        raise PackageError('文件数或大小超过限制。')
    return result


def _requirements(code):
    path = code / 'requirements.txt'
    if not path.exists():
        return []
    if path.stat().st_size > 65536:
        raise PackageError('requirements.txt 太大。')
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except UnicodeError as exc:
        raise PackageError('requirements.txt 必须使用 UTF-8。') from exc
    requirements = []
    for line in lines:
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9][A-Za-z0-9.!+_-]*', line):
            raise PackageError('依赖必须逐行写成 package==version；不接受网络地址、脚本或其他路径。')
        requirements.append(line)
    return requirements


def _checksum(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def _entry(manifest, selected=''):
    candidates = [f['path'] for f in manifest if f['path'].endswith('.py')]
    if not candidates:
        raise PackageError('任务包中至少需要一个 Python 入口文件。')
    entry = selected or ('main.py' if 'main.py' in candidates else candidates[0] if len(candidates) == 1 else '')
    if entry and entry not in candidates:
        raise PackageError('所选 Python 入口不在任务包中。')
    return entry


def _create(record, blob=None, source=None, entry='', actor='admin', note=''):
    version = uuid.uuid4().hex
    destination = release_dir(record['pid'], version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.upload-', dir=destination.parent))
    try:
        code = temporary / 'code'
        code.mkdir()
        if source is not None:
            count = total = 0
            def files():
                for directory, children, names in os.walk(source, followlinks=False):
                    children[:] = [name for name in children if name.casefold() not in EXCLUDED and not name.casefold().startswith('.env.')]
                    for name in children:
                        if (Path(directory) / name).is_symlink():
                            raise PackageError('现有任务包含符号链接目录，请先清理后导入。')
                    for name in names:
                        yield Path(directory) / name
            for path in files():
                relative = path.relative_to(source)
                if any(p.casefold() in EXCLUDED or p.casefold().startswith('.env.') for p in relative.parts):
                    continue
                _path(relative.as_posix())
                if path.is_symlink():
                    raise PackageError('现有任务包含符号链接，请先清理后导入。')
                if not path.is_file():
                    raise PackageError('现有任务包含特殊文件，请先清理后导入。')
                if path.is_file():
                    count += 1
                    total += path.stat().st_size
                    if count > limits()['files'] or total > limits()['expanded_bytes']:
                        raise PackageError('现有任务超过大小限制。')
                    output = code / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, output)
        else:
            _unpack(blob, code, entry)
        manifest = _manifest(code)
        requirements = _requirements(code)
        selected = _entry(manifest, entry)
        data = {'pid': record['pid'], 'version': version, 'created_at': str(dt.datetime.now()),
                'actor': actor, 'note': str(note)[:1000], 'status': 'staged', 'message': '',
                'main_file': selected, 'manifest': manifest, 'checksum': _checksum(manifest),
                'requirements': requirements, 'base_version': record.get('active_version'),
                'base_revision': record['revision']}
        temporary.rename(destination)
        _write_release(data, insert=True)
        return data
    except Exception:
        # These are newly generated staging paths, never an existing version.
        for path in (temporary, destination):
            if path.exists():
                path.resolve().relative_to(storage_root())
                shutil.rmtree(path)
        raise


def stage(blob, fields, actor):
    from app.bootstrap.core import _configuration_lock
    from app.bootstrap.task_loader import discover_task_specs
    with _configuration_lock:
        pid = fields.get('pid')
        if pid:
            record = task(pid)
            if record.get('deleted_at') or record.get('pending'):
                raise PackageError('回收站或正在发布的任务不能上传版本。', 409)
            selected = fields.get('main_file') or (release(pid, record['active_version'])['main_file'] if record.get('active_version') else '')
        else:
            group = _name(fields.get('group_name', ''), '分类')
            folder = _name(fields.get('folder_name', ''), '目录名称')
            name = str(fields.get('task_name', '')).strip()
            if not name or len(name) > 200:
                raise PackageError('请填写任务名称，最多 200 个字符。')
            if any(s['group_name'] == group and s['folder_name'] == folder for s in discover_task_specs()) or any(
                    s['group_name'] == group and s['folder_name'] == folder for s in registry().values()):
                raise PackageError('该分类下已存在同名目录，请换一个目录名称。', 409)
            record = {'pid': 'task_' + uuid.uuid4().hex, 'group_name': group, 'folder_name': folder,
                      'task_name': name, 'active_version': None, 'deleted_at': None, 'origin': 'upload',
                      'created_at': str(dt.datetime.now()), 'created_by': actor, 'revision': 0}
            selected = fields.get('main_file', '')
        # Validate before creating the registry row: a rejected upload adds no task.
        data = _create(record, blob=blob, entry=selected, actor=actor, note=fields.get('note', ''))
        if not pid:
            try:
                record = _write_task(record, expected=0)
                data['base_revision'] = record['revision']
                _write_release(data)
            except Exception:
                with GaussDB() as db:
                    db.execute_sql('DELETE FROM wfs_task_releases WHERE pid=? AND version=?', params=(data['pid'], data['version']))
                raise
        return data


def import_task(pid, actor):
    from app.bootstrap.core import _configuration_lock
    from app.bootstrap.task_loader import discover_task_specs
    with _configuration_lock:
        if pid in registry():
            raise PackageError('任务已经纳入版本管理。', 409)
        spec = next((s for s in discover_task_specs() if s['pid'] == pid), None)
        if not spec or spec.get('error') or spec.get('main_file_error'):
            raise PackageError('任务不存在或入口配置无效。', 404)
        record = {'pid': pid, 'group_name': spec['group_name'], 'folder_name': spec['folder_name'],
                  'task_name': spec.get('task_name') or spec['folder_name'], 'active_version': None,
                  'deleted_at': None, 'origin': 'git', 'created_at': str(dt.datetime.now()),
                  'created_by': actor, 'revision': 0, 'legacy': True}
        data = _create(record, source=spec['task_dir'], entry=spec['main_file'], actor=actor, note='从现有任务导入初始版本')
        record = _write_task(record, expected=0)
        data['base_revision'] = record['revision']
        return _write_release(data)


def prepare(pid, version, entry=''):
    from app.bootstrap.core import _configuration_lock
    with _configuration_lock, _prepare_lock:
        record, data = task(pid), release(pid, version)
        if record.get('deleted_at') or record.get('pending'):
            raise PackageError('任务当前不能准备版本。', 409)
        if data['status'] == 'preparing':
            return data
        if data['status'] in ('ready', 'applied'):
            return data
        if not _slots.acquire(blocking=False):
            raise PackageError('已有两个版本正在准备依赖，请稍后重试。', 409)
        try:
            data['main_file'] = _entry(data['manifest'], entry or data['main_file'])
            if not data['main_file']:
                raise PackageError('请先选择 Python 入口。')
            data.update(status='preparing', message='正在创建独立环境并检查离线依赖。', prepare_token=uuid.uuid4().hex)
            _write_release(data)
            _preparing[(pid, version)] = data['prepare_token']
            thread = threading.Thread(target=_prepare_worker, args=(pid, version, data['prepare_token']), daemon=True, name='task-package-prepare')
            thread.start()
        except Exception:
            _preparing.pop((pid, version), None)
            _slots.release()
            raise
        return data


def _command(command, root, timeout):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('WFS_', 'PIP_', 'PYTHON')):
            env.pop(key, None)
    # Don't send pip diagnostics through the UI; they can contain machine paths.
    with (root / 'prepare.log').open('ab') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                cwd=root, timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise PackageError('依赖准备失败，请确认离线 wheel 与 Python/操作系统版本匹配。管理员可查看版本目录中的 prepare.log。')


def _prepare_worker(pid, version, token):
    try:
        data = release(pid, version)
        if data.get('prepare_token') != token:
            return
        root = release_dir(pid, version)
        code = root / 'code'
        if _checksum(_manifest(code)) != data['checksum']:
            raise PackageError('暂存代码校验不一致，请重新上传。')
        # A process interrupted by restart cannot overwrite a newer attempt.
        env = root / ('environment-' + token)
        timeout = max(30, min(int(os.environ.get('WFS_PACKAGE_PREPARE_SECONDS', '300')), 1800))
        _command([sys.executable, '-I', '-m', 'venv', str(env)], root, timeout)
        python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if data['requirements']:
            wheels = [code / 'wheels']
            if os.environ.get('WFS_TASK_WHEELHOUSE'):
                wheels.append(Path(os.environ['WFS_TASK_WHEELHOUSE']).resolve())
            arguments = [str(python), '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install',
                         '--no-index', '--no-deps', '--only-binary=:all:', '--no-cache-dir']
            for wheelhouse in wheels:
                if wheelhouse.is_dir():
                    arguments += ['--find-links', str(wheelhouse)]
            _command(arguments + data['requirements'], root, timeout)
            _command([str(python), '-I', '-m', 'pip', 'check'], root, timeout)
        # Marker is outside user code; it follows nested entry files as well.
        marker = {'task_release': version, 'package_sha256': data['checksum'], 'pid': pid}
        (root / '.release.json').write_text(json.dumps(marker), encoding='utf-8')
        if os.name != 'nt':
            for path in code.rglob('*'):
                path.chmod(0o555 if path.is_dir() else 0o444)
            code.chmod(0o555)
        data.update(status='ready', message='语法与离线依赖检查通过；尚未执行业务代码。', python=env.name + '/' + ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
        if release(pid, version).get('prepare_token') == token:
            _write_release(data)
    except Exception as exc:
        logger.exception('package preparation failed %s %s', pid, version)
        try:
            data = release(pid, version)
            if data.get('prepare_token') == token:
                data.update(status='failed', message=str(exc) if isinstance(exc, PackageError) else '准备失败或超时，请检查本地依赖环境后重试。')
                _write_release(data)
        except Exception:
            logger.exception('failed to save package preparation result')
    finally:
        with _prepare_lock:
            if _preparing.get((pid, version)) == token:
                _preparing.pop((pid, version), None)
        _slots.release()


def publish(pid, version, revision, actor, rollback=False):
    from app.bootstrap.core import _configuration_lock, aps_start
    from app.bootstrap.schedule_config import load_schedule
    with _configuration_lock:
        record, data = task(pid), release(pid, version)
        if record['revision'] != revision or record.get('deleted_at') or record.get('pending'):
            raise PackageError('任务状态已变化，请刷新后重新发布。', 409)
        if data['status'] not in ('ready', 'applied'):
            raise PackageError('此版本还未通过环境检查。', 409)
        if rollback and not data.get('published_at'):
            raise PackageError('只能回滚到曾成功发布过的版本。', 409)
        if not rollback and data.get('base_version') != record.get('active_version'):
            raise PackageError('预览后当前版本发生变化，请重新上传以核对差异，或选择已发布版本回滚。', 409)
        if record.get('active_version') == version:
            return record
        # Preserve scheduling. A missing configured entry must be addressed in
        # configuration first, rather than silently changing it on publication.
        from app.bootstrap.task_loader import _record_maps
        config = _record_maps().get(pid)
        selected = (config or {}).get('main_file') or data['main_file']
        if selected not in {f['path'] for f in data['manifest'] if f['path'].endswith('.py')}:
            raise PackageError('任务包缺少当前调度配置使用的入口文件，请保留入口后重新上传。', 409)
        root = release_dir(pid, version)
        if _checksum(_manifest(root / 'code')) != data['checksum'] or not (root / data['python']).is_file():
            raise PackageError('版本文件或环境校验失败，请重新准备或上传。', 409)
        previous = {**record}
        record['pending'] = {'previous': previous, 'version': version, 'actor': actor}
        record['active_version'] = version
        record['legacy'] = False
        record = _write_task(record, expected=revision)
        try:
            aps_start(task_pid=pid, action='refresh')
            record.pop('pending', None)
            record['last_published_at'] = str(dt.datetime.now())
            record['last_published_by'] = actor
            data.update(status='applied', message='调度器已确认此版本。', published_at=record['last_published_at'])
            try:
                data['schedule_snapshot'] = load_schedule(pid)
            except ValueError:
                data['schedule_snapshot'] = None
            # Keep the durable intent until both result records have been saved.
            _write_release(data)
            record = _write_task(record, expected=record['revision'])
        except Exception as exc:
            _write_task(previous, expected=record['revision'])
            try:
                if previous.get('active_version') or previous.get('legacy'):
                    aps_start(task_pid=pid, action='refresh')
                else:
                    from app.extensions import scheduler
                    if scheduler.get_job(pid):
                        scheduler.remove_job(pid)
            except Exception:
                logger.exception('old package scheduler restoration failed %s', pid)
            data.update(status='ready', message='激活失败，已恢复上一版本；请检查配置后重试。')
            _write_release(data)
            raise PackageError('发布失败，上一版本仍保留：' + str(exc), 409) from exc
        return record


def recycle(pid, revision, actor, restore=False):
    from app.bootstrap.core import _configuration_lock, aps_start
    from app.bootstrap.schedule_config import set_schedule_enabled
    from app.bootstrap.task_loader import discover_task_specs
    from app.extensions import scheduler
    with _configuration_lock:
        record = task(pid)
        if record['revision'] != revision or record.get('pending'):
            raise PackageError('任务状态已变化，请刷新重试。', 409)
        if bool(record.get('deleted_at')) != bool(restore):
            raise PackageError('任务已删除或已恢复，请刷新。', 409)
        if not restore:
            spec = next((s for s in discover_task_specs() if s['pid'] == pid), None)
            if spec and spec.get('schedule_configured'):
                set_schedule_enabled(pid, False, actor=actor)
            if scheduler.get_job(pid):
                scheduler.remove_job(pid)
            record.update(deleted_at=str(dt.datetime.now()), deleted_by=actor)
        else:
            record.update(deleted_at=None, restored_by=actor)
        record = _write_task(record, expected=revision)
        if restore and (record.get('active_version') or record.get('legacy')):
            # Disabling before tombstoning means restoring cannot resume a job.
            aps_start(task_pid=pid, action='refresh')
        return record


def recover():
    """Run only on scheduler bootstrap, never from API reads."""
    for pid, record in registry().items():
        if record.get('pending'):
            intent = record['pending']
            _write_task(intent['previous'], expected=record['revision'])
            data = release(pid, intent['version'])
            data.update(status='ready', message='上次发布中断，已恢复之前版本，请重新确认发布。')
            _write_release(data)
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT payload FROM wfs_task_releases WHERE pid=?', params=(pid,))
        for row in rows:
            data = json.loads(row[0])
            with _prepare_lock:
                active = (pid, data['version']) in _preparing
            if data['status'] == 'preparing' and not active:
                # Re-read after checking the worker: it may just have completed.
                data = release(pid, data['version'])
                if data['status'] == 'preparing':
                    data.update(status='failed', message='服务重启中断了依赖准备，可重新检查。')
                    _write_release(data)


def discovery(records_by_pid, legacy_specs):
    from app.bootstrap.task_loader import load_task_spec
    managed = registry()
    active = [(pid, r['active_version']) for pid, r in managed.items() if r.get('active_version') and not r.get('deleted_at')]
    releases = {}
    # Batch the registry lookup; discovery must not open a connection per task.
    for offset in range(0, len(active), 100):
        batch = active[offset:offset+100]
        where = ' OR '.join('(pid=? AND version=?)' for _ in batch)
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT pid,payload FROM wfs_task_releases WHERE ' + where,
                                        params=tuple(value for pair in batch for value in pair))
        releases.update({row[0]: json.loads(row[1]) for row in rows})
    # An imported baseline stays on its original path until explicitly published.
    result = [s for s in legacy_specs if s['pid'] not in managed or
              (managed[s['pid']].get('legacy') and not managed[s['pid']].get('deleted_at'))]
    for pid, record in managed.items():
        if record.get('deleted_at') or not record.get('active_version'):
            continue
        data = releases.get(pid)
        if data is None:
            raise RuntimeError('Active task release is missing: ' + pid)
        root = release_dir(pid, data['version'])
        code = root / 'code'
        spec = load_task_spec(record['group_name'], record['folder_name'], code, None, pid_override=pid)
        spec.update(pid=pid, main_file=data['main_file'], task_name=record['task_name'], managed=True,
                    task_release=data['version'], package_sha256=data['checksum'],
                    main_file_options=[f['path'] for f in data['manifest'] if f['path'].endswith('.py')])
        from app.bootstrap.task_loader import _apply_record, resolve_main_file
        try:
            _apply_record(spec, records_by_pid.get(pid))
            spec['main_file_path'] = resolve_main_file(code, spec['main_file'])
            spec['main_file_error'] = ''
        except Exception as exc:
            spec['error'] = str(exc)
        spec.update(python_executable=str(root / data['python']), python_source='任务版本独立环境')
        result.append(spec)
    return result


def overview(pid=None):
    from app.bootstrap.task_loader import discover_task_specs
    from app.bootstrap.task_loader import _record_maps
    managed = registry()
    configurations = _record_maps()
    def display(record):
        name = (configurations.get(record['pid']) or {}).get('task_name')
        return {**record, 'task_name': name or record['task_name']}
    if pid:
        record = display(task(pid))
        with GaussDB() as db:
            rows = db.execute_query_sql('SELECT payload FROM wfs_task_releases WHERE pid=? ORDER BY created_at DESC LIMIT 50', params=(pid,))
        versions = [json.loads(row[0]) for row in rows]
        # File manifests are loaded only for the selected release.
        for data in versions:
            data['file_count'] = len(data.pop('manifest', []))
        return {'task': record, 'versions': versions, 'limits': limits()}
    summaries = [display(record) for record in managed.values()]
    for spec in discover_task_specs():
        if spec['pid'] not in managed:
            summaries.append({'pid': spec['pid'], 'group_name': spec['group_name'], 'folder_name': spec['folder_name'],
                              'task_name': spec.get('task_name') or spec['folder_name'], 'origin': 'git', 'unmanaged': True, 'revision': 0})
    return {'tasks': summaries, 'limits': limits()}


def preview(pid, version, filename=None):
    data = release(pid, version)
    record = task(pid)
    base = release(pid, record['active_version']) if record.get('active_version') else None
    old = {f['path']: f for f in base['manifest']} if base else {}
    new = {f['path']: f for f in data['manifest']}
    changes = [{'path': name, 'kind': 'added' if name not in old else 'deleted' if name not in new else 'modified'}
               for name in sorted(old.keys() | new.keys()) if old.get(name) != new.get(name)]
    result = {'release': data, 'changes': changes, 'current_revision': record['revision'],
              'against_version': record.get('active_version')}
    if filename is not None:
        if filename not in old and filename not in new:
            raise PackageError('文件不在版本清单中。', 404)
        def contents(item, files):
            if filename not in files or item is None:
                return ''
            if files[filename]['size'] > 256 * 1024:
                raise PackageError('此文件过大，仅提供大小和校验值。')
            path = release_dir(pid, item['version']) / 'code' / filename
            try:
                data = path.read_bytes()
                if b'\0' in data:
                    raise UnicodeError()
                return data.decode('utf-8-sig')
            except UnicodeError:
                raise PackageError('非 UTF-8 文本，仅提供大小和校验值。')
        try:
            before, after = contents(base, old), contents(data, new)
            result['diff'] = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='当前/' + filename, tofile='预览/' + filename))[:128000]
            result['content'] = after[:128000]
        except PackageError as exc:
            result['diff'] = str(exc)
            result['content'] = ''
    return result


def download(pid, version):
    data = release(pid, version)
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for item in data['manifest']:
            path = release_dir(pid, version) / 'code' / item['path']
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise PackageError('版本文件校验失败。', 409)
            archive.write(path, item['path'])
    result.seek(0)
    return result
