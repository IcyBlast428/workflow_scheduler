import json
import re
from pathlib import Path

from configobj import ConfigObj

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


def resolve_main_file(task_dir, main_file):
    if not main_file:
        raise ValueError('MAIN_FILE is required')

    task_dir = Path(task_dir).resolve()
    main_path = (task_dir / main_file).resolve()
    try:
        main_path.relative_to(task_dir)
    except ValueError:
        raise ValueError('MAIN_FILE must stay inside the task directory')

    if not main_path.is_file():
        raise ValueError('MAIN_FILE does not exist: {}'.format(main_file))
    return main_path


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

    for group_dir in sorted(task_root.iterdir(), key=lambda path: path.name):
        if _is_hidden_name(group_dir.name) or not group_dir.is_dir():
            continue
        for task_dir in sorted(group_dir.iterdir(), key=lambda path: path.name):
            if _is_hidden_name(task_dir.name) or not task_dir.is_dir():
                continue
            yield group_dir.name, task_dir.name, task_dir


def _legacy_config(task_dir):
    config_path = Path(task_dir) / 'config.ini'
    if not config_path.is_file():
        return {}, None
    try:
        config_base = ConfigObj(str(config_path), encoding='utf-8')
        return dict(config_base.get('base') or {}), config_base
    except Exception:
        return {}, None


def _load_task_config_records():
    try:
        from app.bootstrap.database import GaussDB
        with GaussDB() as db:
            try:
                rows = db.execute_query_sql(
                    """
                    SELECT pid, group_name, folder_name, task_name, main_file, enabled,
                           max_instances, timeout_seconds, trigger_type, schedule_type,
                           schedule_json, trigger_json, updated_at
                    FROM wfs_task_config
                    """,
                    return_json=True,
                )
            except Exception:
                rows = db.execute_query_sql(
                    """
                    SELECT pid, group_name, folder_name, task_name, trigger_type, schedule_type,
                           schedule_json, trigger_json, updated_at
                    FROM wfs_task_config
                    """,
                    return_json=True,
                )
        return rows
    except Exception:
        return []


def _record_maps():
    by_pid = {}
    by_folder = {}
    for row in _load_task_config_records():
        pid = row.get('pid')
        if pid:
            by_pid[pid] = row
        group_name = row.get('group_name')
        folder_name = row.get('folder_name')
        if group_name and folder_name:
            by_folder[(group_name, folder_name)] = row
    return by_pid, by_folder


def _apply_record(spec, record):
    if not record:
        return

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


def load_task_spec(group_name, folder_name, task_dir, records_by_pid=None, records_by_folder=None):
    task_dir = Path(task_dir)
    legacy, config_base = _legacy_config(task_dir)
    inferred_main_file = infer_main_file(task_dir)
    legacy_pid = (legacy.get('PID') or '').strip()
    pid = legacy_pid or folder_name
    error = None
    try:
        max_instances = _as_int(legacy.get('MAX_INSTANCES'), default=1, minimum=1)
        timeout_seconds = _as_int(legacy.get('TIMEOUT_SECONDS'), default=0, minimum=0)
    except Exception as exc:
        max_instances = 1
        timeout_seconds = 0
        error = str(exc)

    spec = {
        'group_name': group_name,
        'folder_name': folder_name,
        'task_dir': task_dir,
        'dir_name': '/{}/{}'.format(group_name, folder_name),
        'config_path': task_dir / 'config.ini',
        'config_base': config_base,
        'config': legacy,
        'pid': pid,
        'task_name': (legacy.get('NAME') or folder_name).strip() or folder_name,
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
        'main_file': (legacy.get('MAIN_FILE') or inferred_main_file or '').strip(),
        'main_file_path': None,
        'main_file_options': list_python_entry_files(task_dir),
        'error': error,
        'main_file_error': '',
        'config_record': None,
    }

    record = None
    if records_by_pid is not None:
        record = records_by_pid.get(pid)
    if not record and records_by_folder is not None:
        record = records_by_folder.get((group_name, folder_name))
        if record and record.get('pid'):
            spec['pid'] = record.get('pid')
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


def discover_task_specs(task_root=TASK_DIR):
    specs = []
    records_by_pid, records_by_folder = _record_maps()
    for group_name, folder_name, task_dir in iter_task_directories(task_root):
        spec = load_task_spec(group_name, folder_name, task_dir, records_by_pid, records_by_folder)
        specs.append(spec)

    pid_locations = {}
    for spec in specs:
        pid = spec.get('pid')
        if pid:
            pid_locations.setdefault(pid, []).append(spec.get('dir_name'))

    for spec in specs:
        pid = spec.get('pid')
        if pid and len(pid_locations.get(pid, [])) > 1:
            spec['error'] = 'duplicate PID found in {}'.format(', '.join(pid_locations[pid]))
    return specs
