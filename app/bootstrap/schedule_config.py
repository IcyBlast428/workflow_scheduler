import datetime
import json

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pytz import timezone as pytz_timezone

from app.bootstrap.global_vars import TASK_DIR
from app.bootstrap.task_loader import discover_task_specs, resolve_main_file


WEEKDAY_OPTIONS = {'*', 'mon-fri', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
SCHEDULER_TZ = pytz_timezone('Asia/Shanghai')
PREVIEW_LIMIT = 16


def find_task_spec(pid=None, group_name=None, folder_name=None):
    if not pid:
        return None
    for spec in discover_task_specs(TASK_DIR):
        if spec.get('pid') == pid:
            return spec
    return None


def resolve_task_spec(pid=None, group_name=None, folder_name=None):
    spec = find_task_spec(pid=pid)
    if not spec:
        raise ValueError('task not found: {}'.format(pid or ''))
    if spec.get('error'):
        raise ValueError('task config is invalid: {}'.format(spec.get('error')))
    return spec


def _as_text(value, default=''):
    if value is None:
        return default
    return str(value)


def _as_bool(value, default=False):
    if value in (None, ''):
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _as_int(value, field_name, minimum=1, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError('{} must be an integer'.format(field_name))
    if result < minimum:
        raise ValueError('{} must be greater than or equal to {}'.format(field_name, minimum))
    if maximum is not None and result > maximum:
        raise ValueError('{} must be less than or equal to {}'.format(field_name, maximum))
    return result


def _default_number(value, default):
    return default if value in (None, '') else value


def _time_parts(value, field_name='time'):
    try:
        parsed = datetime.datetime.strptime(str(value), '%H:%M')
    except (TypeError, ValueError):
        raise ValueError('{} must use HH:MM'.format(field_name))
    return parsed.hour, parsed.minute


def _time_text(hour, minute):
    try:
        return '{:02d}:{:02d}'.format(int(hour), int(minute))
    except (TypeError, ValueError):
        return '09:00'


def _normalize_datetime(value):
    value = str(value or '').strip()
    if not value:
        raise ValueError('run_datetime is required')
    if 'T' in value:
        value = value.replace('T', ' ')
    if len(value) == 16:
        value += ':00'
    try:
        parsed = datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise ValueError('run_datetime must use YYYY-MM-DD HH:MM:SS')
    if SCHEDULER_TZ.localize(parsed) <= datetime.datetime.now(SCHEDULER_TZ):
        raise ValueError('run_datetime must be in the future')
    return value


def _json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else {}


def _json_dumps(value):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _cron_rules(hour='9', minute='0', day='*', month='*', day_of_week='*'):
    return {
        'SECOND': '0',
        'MINUTE': str(minute),
        'HOUR': str(hour),
        'DAY': str(day),
        'MONTH': str(month),
        'DAY_OF_WEEK': str(day_of_week),
    }


def _build_window_rules(form):
    start_hour, start_minute = _time_parts(form.get('window_start') or '09:00', 'window_start')
    end_hour, end_minute = _time_parts(form.get('window_end') or '18:00', 'window_end')
    interval = _as_int(_default_number(form.get('window_interval_minutes'), 1), 'window_interval_minutes', 1, 1440)
    day_of_week = str(form.get('window_day_of_week') or '*').strip().lower()
    if day_of_week not in WEEKDAY_OPTIONS:
        raise ValueError('window_day_of_week is invalid')
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        raise ValueError('window_end must be later than window_start')
    return {
        'WINDOW_START': _time_text(start_hour, start_minute),
        'WINDOW_END': _time_text(end_hour, end_minute),
        'INTERVAL_MINUTES': str(interval),
        'DAY_OF_WEEK': day_of_week,
    }


def build_schedule_payload(form):
    schedule_type = str(form.get('schedule_type') or '').strip()
    if schedule_type == 'every_minute':
        return 'interval', {'MINUTES': '1'}, schedule_type
    if schedule_type == 'every_hour':
        return 'interval', {'HOURS': '1'}, schedule_type
    if schedule_type == 'interval_minutes':
        return 'interval', {'MINUTES': str(_as_int(_default_number(form.get('interval_minutes'), 1), 'interval_minutes', 1))}, schedule_type
    if schedule_type == 'interval_hours':
        return 'interval', {'HOURS': str(_as_int(_default_number(form.get('interval_hours'), 1), 'interval_hours', 1))}, schedule_type
    if schedule_type == 'daily_fixed':
        hour, minute = _time_parts(form.get('fixed_time') or '09:00', 'fixed_time')
        return 'cron', _cron_rules(hour=hour, minute=minute), schedule_type
    if schedule_type == 'weekly_fixed':
        hour, minute = _time_parts(form.get('fixed_time') or '09:00', 'fixed_time')
        day_of_week = str(form.get('weekday') or 'wed').strip().lower()
        if day_of_week not in WEEKDAY_OPTIONS - {'*'}:
            raise ValueError('weekday is invalid')
        return 'cron', _cron_rules(hour=hour, minute=minute, day_of_week=day_of_week), schedule_type
    if schedule_type == 'monthly_fixed':
        hour, minute = _time_parts(form.get('fixed_time') or '09:00', 'fixed_time')
        month_day = _as_int(_default_number(form.get('month_day'), 1), 'month_day', 1, 31)
        return 'cron', _cron_rules(hour=hour, minute=minute, day=month_day), schedule_type
    if schedule_type == 'monthly_last_day':
        hour, minute = _time_parts(form.get('fixed_time') or '09:00', 'fixed_time')
        return 'cron', _cron_rules(hour=hour, minute=minute, day='last'), schedule_type
    if schedule_type == 'window_minutes':
        return 'window', _build_window_rules(form), schedule_type
    if schedule_type == 'once_at':
        return 'date', {'RUN_DATE': _normalize_datetime(form.get('run_datetime'))}, schedule_type
    if schedule_type == 'custom_cron':
        return 'cron', _cron_rules(
            hour=form.get('cron_hour') or '*',
            minute=form.get('cron_minute') or '0',
            day=form.get('cron_day') or '*',
            month=form.get('cron_month') or '*',
            day_of_week=form.get('cron_day_of_week') or '*',
        ), schedule_type
    raise ValueError('unsupported schedule_type')


def _parse_rules_for_trigger(trigger, rules):
    parsed = {}
    for key, value in (rules or {}).items():
        field = str(key).lower()
        if value in ('', None):
            continue
        if trigger != 'cron' and value in ('0', 0):
            continue
        if value in ('last', 'LAST'):
            parsed[field] = str(value).lower()
            continue
        try:
            parsed[field] = int(value)
        except (TypeError, ValueError):
            parsed[field] = value
    return parsed


def _window_times_by_hour(rules):
    start_hour, start_minute = _time_parts(rules.get('WINDOW_START') or '09:00', 'WINDOW_START')
    end_hour, end_minute = _time_parts(rules.get('WINDOW_END') or '18:00', 'WINDOW_END')
    interval = _as_int(rules.get('INTERVAL_MINUTES') or 1, 'INTERVAL_MINUTES', 1, 1440)
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        raise ValueError('WINDOW_END must be later than WINDOW_START')
    by_hour = {}
    current = start_total
    while current <= end_total:
        hour = current // 60
        minute = current % 60
        if 0 <= hour <= 23:
            by_hour.setdefault(hour, []).append(minute)
        current += interval
    if not by_hour:
        raise ValueError('window schedule does not produce any fire time')
    return by_hour


def build_scheduler_trigger(trigger, rules):
    if trigger == 'interval':
        return IntervalTrigger(timezone=SCHEDULER_TZ, **_parse_rules_for_trigger(trigger, rules))
    if trigger == 'cron':
        return CronTrigger(timezone=SCHEDULER_TZ, **_parse_rules_for_trigger(trigger, rules))
    if trigger == 'date':
        return DateTrigger(timezone=SCHEDULER_TZ, **_parse_rules_for_trigger(trigger, rules))
    if trigger == 'window':
        day_of_week = str((rules or {}).get('DAY_OF_WEEK') or '*').strip().lower()
        if day_of_week not in WEEKDAY_OPTIONS:
            raise ValueError('DAY_OF_WEEK is invalid')
        triggers = []
        for hour, minutes in sorted(_window_times_by_hour(rules).items()):
            triggers.append(CronTrigger(
                timezone=SCHEDULER_TZ,
                second=0,
                minute=','.join(str(minute) for minute in sorted(set(minutes))),
                hour=str(hour),
                day='*',
                month='*',
                day_of_week=day_of_week,
            ))
        return OrTrigger(triggers)
    raise ValueError('unsupported trigger')


def preview_schedule(form=None, trigger=None, rules=None, limit=PREVIEW_LIMIT):
    if form is not None:
        trigger, rules, _ = build_schedule_payload(form)
    schedule_trigger = build_scheduler_trigger(trigger, rules)
    now = datetime.datetime.now(SCHEDULER_TZ)
    if expired_once(schedule_trigger, now):
        return []
    previous = None
    upcoming = []
    for _ in range(limit):
        next_time = schedule_trigger.get_next_fire_time(previous, now if previous is None else previous)
        if not next_time:
            break
        if next_time.tzinfo is None:
            next_time = SCHEDULER_TZ.localize(next_time)
        upcoming.append({
            'datetime': next_time.strftime('%Y-%m-%d %H:%M:%S'),
            'date': next_time.strftime('%Y-%m-%d'),
            'time': next_time.strftime('%H:%M:%S'),
        })
        previous = next_time
    return upcoming


def expired_once(trigger, now=None):
    return isinstance(trigger, DateTrigger) and trigger.run_date <= (now or datetime.datetime.now(SCHEDULER_TZ))


def _default_form(enabled=True):
    return {
        'enabled': enabled,
        'task_name': '',
        'main_file': '',
        'max_instances': 1,
        'timeout_seconds': 0,
        'schedule_family': 'interval',
        'schedule_type': 'every_minute',
        'interval_minutes': 1,
        'interval_hours': 1,
        'fixed_time': '09:00',
        'weekday': 'wed',
        'month_day': 1,
        'window_start': '09:30',
        'window_end': '18:15',
        'window_interval_minutes': 1,
        'window_day_of_week': '*',
        'run_datetime': '',
        'cron_minute': '0',
        'cron_hour': '9',
        'cron_day': '*',
        'cron_month': '*',
        'cron_day_of_week': '*',
    }


def _family_for_type(schedule_type):
    if schedule_type in {'every_minute', 'every_hour', 'interval_minutes', 'interval_hours'}:
        return 'interval'
    if schedule_type in {'daily_fixed', 'weekly_fixed', 'monthly_fixed', 'monthly_last_day', 'once_at'}:
        return 'fixed'
    if schedule_type == 'window_minutes':
        return 'window'
    return 'advanced'


def schedule_to_form(trigger, rules, schedule_type=None, saved_form=None, spec=None, enabled=True):
    form = _default_form(enabled=enabled)
    if spec:
        form.update({
            'task_name': spec.get('task_name') or '',
            'main_file': spec.get('main_file') or '',
            'max_instances': spec.get('max_instances') or 1,
            'timeout_seconds': spec.get('timeout_seconds') or 0,
        })
    if saved_form:
        form.update(saved_form)
    rules = {str(key).upper(): _as_text(value) for key, value in (rules or {}).items()}
    if schedule_type:
        form['schedule_type'] = schedule_type
        form['schedule_family'] = _family_for_type(schedule_type)
        form['enabled'] = enabled
        return form

    if trigger == 'interval':
        minutes = rules.get('MINUTES')
        hours = rules.get('HOURS')
        seconds = rules.get('SECONDS')
        if minutes == '1' or seconds == '60':
            form['schedule_type'] = 'every_minute'
        elif hours == '1':
            form['schedule_type'] = 'every_hour'
        elif minutes:
            form['schedule_type'] = 'interval_minutes'
            form['interval_minutes'] = _as_int(minutes, 'interval_minutes')
        elif hours:
            form['schedule_type'] = 'interval_hours'
            form['interval_hours'] = _as_int(hours, 'interval_hours')
    elif trigger == 'date':
        form['schedule_type'] = 'once_at'
        form['run_datetime'] = rules.get('RUN_DATE', '').replace(' ', 'T')[:16]
    elif trigger == 'window':
        form['schedule_type'] = 'window_minutes'
        form['window_start'] = rules.get('WINDOW_START', form['window_start'])
        form['window_end'] = rules.get('WINDOW_END', form['window_end'])
        form['window_interval_minutes'] = _as_int(rules.get('INTERVAL_MINUTES', 1), 'window_interval_minutes')
        form['window_day_of_week'] = rules.get('DAY_OF_WEEK', '*')
    elif trigger == 'cron':
        minute = rules.get('MINUTE', '0')
        hour = rules.get('HOUR', '9')
        day = rules.get('DAY', '*')
        month = rules.get('MONTH', '*')
        day_of_week = rules.get('DAY_OF_WEEK', '*')
        form.update({
            'cron_minute': minute,
            'cron_hour': hour,
            'cron_day': day,
            'cron_month': month,
            'cron_day_of_week': day_of_week,
            'fixed_time': _time_text(str(hour).split('-', 1)[0].split(',', 1)[0], str(minute).replace('*/', '').split(',', 1)[0]),
            'weekday': day_of_week if day_of_week != '*' else 'wed',
        })
        if day == 'last':
            form['schedule_type'] = 'monthly_last_day'
        elif day not in ('', '*'):
            form['schedule_type'] = 'monthly_fixed'
            try:
                form['month_day'] = int(str(day).split(',', 1)[0])
            except ValueError:
                form['schedule_type'] = 'custom_cron'
        elif day_of_week not in ('', '*') and '-' not in str(hour):
            form['schedule_type'] = 'weekly_fixed'
        elif hour not in ('', '*') and minute not in ('', '*'):
            form['schedule_type'] = 'daily_fixed'
        else:
            form['schedule_type'] = 'custom_cron'
    form['schedule_family'] = _family_for_type(form['schedule_type'])
    form['enabled'] = enabled
    return form


def _load_schedule_record(pid):
    from app.bootstrap.database import GaussDB
    with GaussDB() as db:
        rows = db.execute_query_sql(
                """
                SELECT pid, group_name, folder_name, task_name, main_file, enabled,
                       max_instances, timeout_seconds, trigger_type, schedule_type,
                       schedule_json, trigger_json, updated_at, version, updated_by
                FROM wfs_task_config
                WHERE pid = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params=(pid,),
                return_json=True,
        )
    return rows[0] if rows else None


def _record_belongs_to_spec(record, spec):
    return bool(record and spec and record.get('pid') == spec.get('pid'))


def _normalize_task_config(spec, form):
    task_name = str(form.get('task_name') or spec.get('task_name') or '').strip()
    main_file = str(form.get('main_file') or spec.get('main_file') or '').strip()
    max_instances = _as_int(_default_number(form.get('max_instances'), 1), 'max_instances', 1)
    timeout_seconds = _as_int(form.get('timeout_seconds') or 0, 'timeout_seconds', 0)
    resolve_main_file(spec.get('task_dir'), main_file)
    return task_name, main_file, max_instances, timeout_seconds


def _save_schedule_record(spec, trigger, rules, schedule_type, form):
    from app.bootstrap.database import GaussDB

    task_name, main_file, max_instances, timeout_seconds = _normalize_task_config(spec, form)
    for field in ('memory_mb','cpu_seconds','file_mb'):
        if field in form:
            form[field] = _as_int(form[field], field, 0)
    if 'misfire_grace_seconds' in form:
        form['misfire_grace_seconds'] = _as_int(form['misfire_grace_seconds'], 'misfire_grace_seconds', 1)
    if len(str(form.get('owner',''))) > 200 or len(str(form.get('description',''))) > 10000:
        raise ValueError('负责人或说明过长。')
    enabled = 'true' if _as_bool(form.get('enabled'), default=True) else 'false'
    saved_form = dict(form or {})
    saved_form.pop('pid', None)
    saved_form.pop('updated_by', None)
    saved_form.update({
        'enabled': enabled == 'true',
        'task_name': task_name,
        'main_file': main_file,
        'max_instances': max_instances,
        'timeout_seconds': timeout_seconds,
    })
    payload = (
        spec.get('pid'),
        spec.get('group_name') or '',
        spec.get('folder_name') or '',
        task_name,
        main_file,
        enabled,
        max_instances,
        timeout_seconds,
        trigger,
        schedule_type,
        _json_dumps(saved_form),
        _json_dumps(rules),
        datetime.datetime.now(),
    )
    with GaussDB() as db:
        db.begin_transaction()
        try:
            query = 'SELECT version FROM wfs_task_config WHERE pid=?'
            if not db._local_sqlite:
                query += ' FOR UPDATE'
            previous = db.execute_query_sql(query, params=(spec.get('pid'),))
            old_version = int(previous[0][0] or 1) if previous else 0
            expected = int(form.get('version', old_version))
            if expected != old_version:
                raise ValueError('配置已被其他操作修改，请重新打开配置后保存。')
            version = old_version + 1
            if previous and not db.execute_query_sql('SELECT 1 FROM wfs_config_versions WHERE pid=? AND version=?', params=(spec.get('pid'),old_version)):
                old_payload = db.execute_query_sql('SELECT schedule_json FROM wfs_task_config WHERE pid=?', params=(spec.get('pid'),))[0][0]
                db.execute_sql('INSERT INTO wfs_config_versions(pid,version,changed_at,changed_by,payload) VALUES(?,?,?,?,?)',params=(spec.get('pid'),old_version,datetime.datetime.now(),'migration-baseline',old_payload))
            # 旧版本如果没有主键约束，可能留下同 PID 多行。保存时先清理再插入，
            # 让数据库重新回到“一个 PID 一条配置”的模型。
            db.execute_sql(
                "DELETE FROM wfs_task_config WHERE pid = ?",
                params=(spec.get('pid'),),
            )
            db.execute_sql(
                """
                INSERT INTO wfs_task_config (
                    pid, group_name, folder_name, task_name, main_file, enabled,
                    max_instances, timeout_seconds, trigger_type, schedule_type,
                    schedule_json, trigger_json, updated_at, version, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params=payload + (version, form.get('updated_by', 'system')),
            )
            db.execute_sql('INSERT INTO wfs_config_versions(pid,version,changed_at,changed_by,payload) VALUES(?,?,?,?,?)',
                           params=(spec.get('pid'), version, datetime.datetime.now(), form.get('updated_by','system'), _json_dumps(saved_form)))
            db.set_commit()
        except Exception as exc:
            db.set_rollback()
            raise RuntimeError('配置保存失败：{}'.format(exc))
    from app.bootstrap.task_loader import invalidate_task_cache
    invalidate_task_cache()


def _record_schedule(spec, record):
    trigger = record.get('trigger_type') or ''
    rules = _json_loads(record.get('trigger_json'), {})
    saved_form = _json_loads(record.get('schedule_json'), {})
    schedule_type = record.get('schedule_type') or saved_form.get('schedule_type')
    enabled = _as_bool(record.get('enabled'), default=False)
    spec_for_form = dict(spec or {})
    spec_for_form.update({
        'task_name': record.get('task_name') or spec.get('task_name'),
        'main_file': record.get('main_file') or spec.get('main_file'),
        'max_instances': record.get('max_instances') or spec.get('max_instances'),
        'timeout_seconds': record.get('timeout_seconds') or spec.get('timeout_seconds'),
    })
    form = schedule_to_form(trigger, rules, schedule_type=schedule_type, saved_form=saved_form, spec=spec_for_form, enabled=enabled)
    # Historical JSON may contain request identity from older clients.
    form.pop('pid', None)
    form.pop('updated_by', None)
    form['version'] = int(record.get('version') or 1)
    return {
        'pid': spec.get('pid'),
        'version': form['version'],
        'updated_by': record.get('updated_by') or '',
        'updated_at': str(record.get('updated_at') or ''),
        'group_name': spec.get('group_name') or record.get('group_name') or '',
        'folder_name': spec.get('folder_name') or record.get('folder_name') or '',
        'task_name': record.get('task_name') or spec.get('task_name') or '',
        'main_file': record.get('main_file') or spec.get('main_file') or '',
        'main_file_options': spec.get('main_file_options') or [],
        'max_instances': record.get('max_instances') or spec.get('max_instances') or 1,
        'timeout_seconds': record.get('timeout_seconds') or spec.get('timeout_seconds') or 0,
        'enabled': enabled,
        'configured': bool(trigger and rules),
        'trigger': trigger,
        'rules': rules,
        'source': 'database',
        'form': form,
    }


def _unconfigured_schedule(spec):
    form = schedule_to_form('', {}, spec=spec, enabled=False)
    form['version'] = 0
    return {
        'pid': spec.get('pid'),
        'group_name': spec.get('group_name') or '',
        'folder_name': spec.get('folder_name') or '',
        'task_name': spec.get('task_name') or '',
        'main_file': spec.get('main_file') or '',
        'main_file_options': spec.get('main_file_options') or [],
        'max_instances': spec.get('max_instances') or 1,
        'timeout_seconds': spec.get('timeout_seconds') or 0,
        'enabled': False,
        'configured': False,
        'trigger': '',
        'rules': {},
        'source': 'unconfigured',
        'form': form,
    }


def load_schedule(pid, group_name=None, folder_name=None):
    spec = resolve_task_spec(pid=pid)
    record = _load_schedule_record(pid)
    if record and not _record_belongs_to_spec(record, spec):
        record = None
    data = _record_schedule(spec, record) if record else _unconfigured_schedule(spec)
    from app.bootstrap.database import GaussDB
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT version,status,message FROM wfs_config_application WHERE pid=?', params=(pid,), return_json=True)
    data['application'] = rows[0] if rows else {'status':'unconfigured' if not record else 'pending','message':''}
    if record and data['application'].get('version') != data['version']:
        data['application'] = {'status':'pending','message':'配置已保存，等待调度器应用。'}
    try:
        if data['configured']:
            data['preview'] = preview_schedule(trigger=data['trigger'], rules=data['rules'])
        else:
            data['preview'] = preview_schedule(form=data['form'])
    except Exception as exc:
        data['preview'] = []
        data['preview_error'] = str(exc)
    return data


def apply_persisted_schedule(spec):
    return spec


def save_schedule(pid, form):
    form = form or {}
    spec = resolve_task_spec(pid=pid)

    trigger, rules, schedule_type = build_schedule_payload(form)
    build_scheduler_trigger(trigger, rules)
    _save_schedule_record(spec, trigger, rules, schedule_type, form)
    return load_schedule(spec.get('pid'))


def set_schedule_enabled(pid, enabled, group_name=None, folder_name=None, actor='system'):
    spec = resolve_task_spec(pid=pid)

    record = _load_schedule_record(spec.get('pid'))
    if not record or not _record_belongs_to_spec(record, spec):
        raise ValueError('task {} has no saved schedule strategy yet'.format(pid))
    if not record.get('trigger_type') or not _json_loads(record.get('trigger_json'), {}):
        raise ValueError('task {} has no schedule strategy yet'.format(pid))

    saved_form = _json_loads(record.get('schedule_json'), {})
    saved_form['enabled'] = bool(enabled)
    saved_form.update(version=int(record.get('version') or 1), updated_by=actor)
    return save_schedule(pid, saved_form)


def record_application(pid, version, status, message=''):
    from app.bootstrap.database import GaussDB
    with GaussDB() as db:
        db.begin_transaction()
        try:
            db.execute_sql('DELETE FROM wfs_config_application WHERE pid=?', params=(pid,))
            db.execute_sql('INSERT INTO wfs_config_application(pid,version,status,message,updated_at) VALUES(?,?,?,?,?)',
                           params=(pid, version, status, message, datetime.datetime.now()))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
