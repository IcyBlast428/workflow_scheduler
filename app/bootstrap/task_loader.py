import re
from pathlib import Path

from configobj import ConfigObj

from app.bootstrap.global_vars import TASK_DIR


VALID_TRIGGERS = {'interval', 'date', 'cron'}
PID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


def _is_hidden_name(name):
    return bool(re.findall(r'^\W', name))


def _ensure_bool(raw_value, field_name):
    value = str(raw_value or '').strip().lower()
    if value not in {'true', 'false'}:
        raise ValueError('{} must be true or false'.format(field_name))
    return value == 'true', value


def _ensure_int(raw_value, field_name, default=1):
    if raw_value in (None, ''):
        return default
    value = int(raw_value)
    if value <= 0:
        raise ValueError('{} must be greater than 0'.format(field_name))
    return value


def _ensure_non_negative_int(raw_value, field_name, default=0):
    if raw_value in (None, ''):
        return default
    value = int(raw_value)
    if value < 0:
        raise ValueError('{} must be greater than or equal to 0'.format(field_name))
    return value


def _resolve_main_file(task_dir, main_file):
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


def load_task_spec(group_name, folder_name, task_dir):
    task_dir = Path(task_dir)
    config_path = task_dir / 'config.ini'
    spec = {
        'group_name': group_name,
        'folder_name': folder_name,
        'task_dir': task_dir,
        'dir_name': '/{}/{}'.format(group_name, folder_name),
        'config_path': config_path,
        'config_base': None,
        'config': {},
        'pid': None,
        'task_name': folder_name,
        'raw_start': 'false',
        'start_enabled': False,
        'trigger': None,
        'max_instances': 1,
        'timeout_seconds': 0,
        'main_file': None,
        'main_file_path': None,
        'error': None,
    }

    if not config_path.is_file():
        spec['error'] = 'config.ini is missing'
        return spec

    try:
        config_base = ConfigObj(str(config_path), encoding='utf-8')
        config = config_base.get('base')
        if not config:
            raise ValueError('base section is missing')

        spec['config_base'] = config_base
        spec['config'] = config
        spec['pid'] = (config.get('PID') or '').strip() or None
        if not spec['pid']:
            raise ValueError('PID is required')
        spec['task_name'] = (config.get('NAME') or folder_name).strip() or folder_name
        start_enabled, raw_start = _ensure_bool(config.get('START'), 'START')
        spec['start_enabled'] = start_enabled
        spec['raw_start'] = raw_start

        trigger = (config.get('TRIGGER') or '').strip().lower()
        if trigger not in VALID_TRIGGERS:
            raise ValueError('TRIGGER must be one of {}'.format(', '.join(sorted(VALID_TRIGGERS))))
        if config_base.get(trigger) is None:
            raise ValueError('missing [{}] section for trigger {}'.format(trigger, trigger))
        spec['trigger'] = trigger

        spec['max_instances'] = _ensure_int(config.get('MAX_INSTANCES'), 'MAX_INSTANCES', default=1)
        spec['timeout_seconds'] = _ensure_non_negative_int(config.get('TIMEOUT_SECONDS'), 'TIMEOUT_SECONDS', default=0)
        spec['main_file'] = config.get('MAIN_FILE')
        spec['main_file_path'] = _resolve_main_file(task_dir, spec['main_file'])
    except Exception as exc:
        spec['error'] = str(exc)

    return spec


def discover_task_specs(task_root=TASK_DIR):
    specs = []
    for group_name, folder_name, task_dir in iter_task_directories(task_root):
        spec = load_task_spec(group_name, folder_name, task_dir)
        pid = spec.get('pid')
        if pid and not PID_PATTERN.match(pid):
            spec['error'] = 'PID must use letters, numbers, hyphen or underscore'
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
