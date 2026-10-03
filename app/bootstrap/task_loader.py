import json
import re
from pathlib import Path
import threading
import time
import copy

from app.bootstrap.global_vars import TASK_DIR


VALID_TRIGGERS = {'interval', 'date', 'cron', 'window'}
PID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
DEFAULT_MAIN_FILE = 'main.py'


def _is_hidden_name(name):
    return bool(re.findall(r'^\W', name))


def _as_bool(raw_value, default=False):
    if raw_value in (None, ''):
        return default
    return str(raw_value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _as_int(raw_value, default=0, minimum=0):
    if raw_value in (None, ''):
        return default
    value = int(raw_value)
    if value < minimum:
        raise ValueError('value must be greater than or equal to {}'.format(minimum))
    return value


def _json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else {}


def list_python_entry_files(task_dir):
    task_dir = Path(task_dir)
    if not task_dir.exists():
        return []
    return [
        str(path.relative_to(task_dir)).replace('\\', '/')
        for path in sorted(task_dir.glob('*.py'), key=lambda item: item.name)
        if path.is_file() and not _is_hidden_name(path.name)
    ]


def _has_python_entry_candidate(task_dir):
    """只有包含直接 Python 入口候选文件的目录才认为是任务目录。"""
    return bool(list_python_entry_files(task_dir))


def resolve_main_file(task_dir, main_file):
    if not main_file:
        raise ValueError('MAIN_FILE is required')

    task_dir = Path(task_dir).resolve()
    main_path = (task_dir / main_file).resolve()
    try:
        # 防止通过 ../ 跳出任务目录，只允许任务执行自己的目录内文件。
        main_path.relative_to(task_dir)
    except ValueError:
        raise ValueError('MAIN_FILE must stay inside the task directory')

    if not main_path.is_file():
        raise ValueError('MAIN_FILE does not exist: {}'.format(main_file))
    return main_path


def _venv_python_path(venv_dir):
    venv_dir = Path(venv_dir)
    candidates = [
        venv_dir / 'Scripts' / 'python.exe',
        venv_dir / 'bin' / 'python',
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ''


def resolve_python_executable(group_dir, task_dir):
    # 任务依赖隔离优先级：单任务 .venv > 任务组 .venv > 平台主环境。
    task_python = _venv_python_path(Path(task_dir) / '.venv')
    if task_python:
        return task_python, 'task'
    group_python = _venv_python_path(Path(group_dir) / '.venv')
    if group_python:
        return group_python, 'group'
    return '', 'project'


def infer_main_file(task_dir):
    task_dir = Path(task_dir)
    if (task_dir / DEFAULT_MAIN_FILE).is_file():
        return DEFAULT_MAIN_FILE
    options = list_python_entry_files(task_dir)
    if len(options) == 1:
        return options[0]
    return ''


def iter_task_directories(task_root=TASK_DIR):
    task_root = Path(task_root)
    if not task_root.exists():
        return

    # 任务目录固定为 app/jobs/<group>/<task>，隐藏目录和非目录均跳过。
    for group_dir in sorted(task_root.iterdir(), key=lambda path: path.name):
        if _is_hidden_name(group_dir.name) or not group_dir.is_dir():
            continue
        for task_dir in sorted(group_dir.iterdir(), key=lambda path: path.name):
            if _is_hidden_name(task_dir.name) or not task_dir.is_dir():
                continue
            # 纯分类目录不展示为任务；至少要有一个直接的 .py 入口候选文件。
            if not _has_python_entry_candidate(task_dir):
                continue
            yield group_dir.name, task_dir.name, task_dir


def _load_task_config_records():
    try:
        from app.bootstrap.database import GaussDB
        with GaussDB() as db:
            try:
                # 新版表结构包含 main_file、enabled、max_instances、timeout_seconds。
                rows = db.execute_query_sql(
                    """
                    SELECT pid, group_name, folder_name, task_name, main_file, enabled,
                           max_instances, timeout_seconds, trigger_type, schedule_type,
                           schedule_json, trigger_json, updated_at, version, updated_by
                    FROM wfs_task_config
                    ORDER BY updated_at DESC
                    """,
                    return_json=True,
                )
            except Exception:
                # 兼容尚未执行最新 DDL 的环境，避免任务扫描阶段直接失败。
                rows = db.execute_query_sql(
                    """
                    SELECT pid, group_name, folder_name, task_name, trigger_type, schedule_type,
                           schedule_json, trigger_json, updated_at
                    FROM wfs_task_config
                    ORDER BY updated_at DESC
                    """,
                    return_json=True,
                )
        return rows
    except Exception as exc:
        raise RuntimeError('failed to load task configuration from database') from exc


def build_task_pid(group_name, folder_name):
    return '{}__{}'.format(group_name, folder_name)


def _record_maps():
    by_pid = {}
    for row in _load_task_config_records():
        # PID 是任务配置唯一主键，不再按旧的 folder_name 或 group/folder 做兜底匹配。
        pid = row.get('pid')
        if pid and pid not in by_pid:
            by_pid[pid] = row
    return by_pid


def _record_belongs_to_task(record, group_name, folder_name, pid):
    """任务配置只按 PID 归属，group/folder 只是扫描和展示元数据。"""
    return bool(record and record.get('pid') == pid)


def _apply_record(spec, record):
    if not record:
        return

    # 数据库中的前端配置覆盖目录推断值；目录只负责发现任务代码。
    spec['config_record'] = record
    spec['task_name'] = record.get('task_name') or spec['task_name']
    spec['main_file'] = record.get('main_file') or spec['main_file']
    spec['max_instances'] = _as_int(record.get('max_instances'), default=spec['max_instances'], minimum=1)
    spec['timeout_seconds'] = _as_int(record.get('timeout_seconds'), default=spec['timeout_seconds'], minimum=0)
    spec['schedule_type'] = record.get('schedule_type') or ''
    spec['trigger'] = record.get('trigger_type') or ''
    spec['schedule_rules'] = _json_loads(record.get('trigger_json'), {})
    spec['schedule_form'] = _json_loads(record.get('schedule_json'), {})
    spec['schedule_configured'] = bool(spec['trigger'] and spec['schedule_rules'])
    spec['schedule_enabled'] = _as_bool(record.get('enabled'), default=False)
    spec['start_enabled'] = spec['schedule_enabled'] and spec['schedule_configured']
    spec['raw_start'] = 'true' if spec['start_enabled'] else 'false'
    spec['schedule_source'] = 'database'


def load_task_spec(group_name, folder_name, task_dir, records_by_pid=None):
    task_dir = Path(task_dir)
    group_dir = task_dir.parent
    inferred_main_file = infer_main_file(task_dir)
    python_executable, python_source = resolve_python_executable(group_dir, task_dir)
    identity_error = ''
    manifest = task_dir / '.wfs-task.json'
    pid = build_task_pid(group_name, folder_name)
    if manifest.exists():
        try:
            if manifest.is_symlink() or manifest.stat().st_size > 4096:
                raise ValueError('invalid identity manifest')
            identity = json.loads(manifest.read_text(encoding='utf-8'))
            pid = identity['task_id']
            if not isinstance(pid,str) or len(pid)>200 or not PID_PATTERN.fullmatch(pid):
                raise ValueError('invalid stable task ID')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            identity_error = '任务标识文件无效：'+str(exc)
    max_instances = 1
    timeout_seconds = 0

    # spec 是调度器、API 和前端共用的任务描述结构，新增字段时优先在这里集中补齐默认值。
    spec = {
        'group_name': group_name,
        'folder_name': folder_name,
        'task_dir': task_dir,
        'dir_name': '/{}/{}'.format(group_name, folder_name),
        'config_path': None,
        'config_base': None,
        'config': {},
        'pid': pid,
        'task_name': '',
        'raw_start': 'false',
        'start_enabled': False,
        'trigger': '',
        'schedule_rules': {},
        'schedule_type': '',
        'schedule_form': {},
        'schedule_source': 'unconfigured',
        'schedule_configured': False,
        'schedule_enabled': False,
        'max_instances': max_instances,
        'timeout_seconds': timeout_seconds,
        'main_file': (inferred_main_file or '').strip(),
        'main_file_path': None,
        'main_file_options': list_python_entry_files(task_dir),
        'python_executable': python_executable,
        'python_source': python_source,
        'error': identity_error or None,
        'main_file_error': '',
        'config_record': None,
    }

    record = None
    if records_by_pid is not None:
        candidate = records_by_pid.get(pid)
        if _record_belongs_to_task(candidate, group_name, folder_name, pid):
            record = candidate
    try:
        _apply_record(spec, record)
    except Exception as exc:
        spec['error'] = str(exc)

    if spec['pid'] and not PID_PATTERN.match(spec['pid']):
        spec['error'] = 'PID must use letters, numbers, hyphen or underscore'

    try:
        spec['main_file_path'] = resolve_main_file(task_dir, spec.get('main_file'))
    except Exception as exc:
        spec['main_file_error'] = str(exc)

    return spec


_cache = {}
_cache_lock = threading.RLock()


def invalidate_task_cache():
    with _cache_lock:
        _cache.clear()


def discover_task_specs(task_root=TASK_DIR):
    key = str(task_root)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 3:
            return copy.deepcopy(cached[1])
        specs = _discover_task_specs(task_root)
        _cache[key] = (time.monotonic(), specs)
        return copy.deepcopy(specs)


def _discover_task_specs(task_root=TASK_DIR):
    specs = []
    records_by_pid = _record_maps()
    for group_name, folder_name, task_dir in iter_task_directories(task_root):
        spec = load_task_spec(group_name, folder_name, task_dir, records_by_pid)
        specs.append(spec)

    pid_locations = {}
    for spec in specs:
        pid = spec.get('pid')
        if pid:
            pid_locations.setdefault(pid, []).append(spec.get('dir_name'))

    # PID 是调度器 job_id，也是运行日志和统计表的主键，必须全局唯一。
    for spec in specs:
        pid = spec.get('pid')
        if pid and len(pid_locations.get(pid, [])) > 1:
            spec['error'] = 'duplicate PID found in {}'.format(', '.join(pid_locations[pid]))
    return specs
