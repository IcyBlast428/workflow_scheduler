import datetime
import json
import os
from pathlib import Path

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from configobj import ConfigObj
from pytz import timezone as pytz_timezone

from app.bootstrap.global_vars import TASK_DIR
from app.bootstrap.task_loader import discover_task_specs, load_task_spec


TRIGGER_SECTIONS = ('interval', 'cron', 'date')
WEEKDAY_OPTIONS = {'*', 'mon-fri', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
SCHEDULER_TZ = pytz_timezone('Asia/Shanghai')
PREVIEW_LIMIT = 16


def find_task_spec(pid):
    for spec in discover_task_specs(TASK_DIR):
        if spec.get('pid') == pid:
            return spec
    return None


def _as_text(value, default=''):
    if value is None:
        return default
    return str(value)


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
    interval = _as_int(form.get('window_interval_minutes') or 1, 'window_interval_minutes', 1, 1440)
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
        return 'interval', {'MINUTES': str(_as_int(form.get('interval_minutes') or 1, 'interval_minutes', 1))}, schedule_type
    if schedule_type == 'interval_hours':
        return 'interval', {'HOURS': str(_as_int(form.get('interval_hours') or 1, 'interval_hours', 1))}, schedule_type
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
        month_day = _as_int(form.get('month_day') or 1, 'month_day', 1, 31)
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


def _default_form():
    return {
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


def schedule_to_form(trigger, rules, schedule_type=None, saved_form=None):
    form = _default_form()
    if saved_form:
        form.update(saved_form)
    rules = {str(key).upper(): _as_text(value) for key, value in (rules or {}).items()}
    if schedule_type:
        form['schedule_type'] = schedule_type
        form['schedule_family'] = _family_for_type(schedule_type)
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
    return form


def _load_schedule_record(pid):
    try:
        from app.bootstrap.database import GaussDB
        with GaussDB() as db:
            rows = db.execute_query_sql(
                """
                SELECT pid, group_name, folder_name, task_name, trigger_type, schedule_type,
                       schedule_json, trigger_json, updated_at
                FROM wfs_task_config
                WHERE pid = ?
                """,
                params=(pid,),
                return_json=True,
            )
        return rows[0] if rows else None
    except Exception:
        return None


def _save_schedule_record(spec, trigger, rules, schedule_type, form):
    from app.bootstrap.database import GaussDB
    payload = (
        spec.get('pid'),
        spec.get('group_name') or '',
        spec.get('folder_name') or '',
        spec.get('task_name') or '',
        trigger,
        schedule_type,
        _json_dumps(form),
        _json_dumps(rules),
        datetime.datetime.now(),
    )
    with GaussDB() as db:
        rows = db.execute_query_sql(
            "SELECT pid FROM wfs_task_config WHERE pid = ?",
            params=(spec.get('pid'),),
            return_json=False,
        )
        if rows:
            db.execute_sql(
                """
                UPDATE wfs_task_config
                SET group_name = ?, folder_name = ?, task_name = ?, trigger_type = ?,
                    schedule_type = ?, schedule_json = ?, trigger_json = ?, updated_at = ?
                WHERE pid = ?
                """,
                params=payload[1:] + (payload[0],),
            )
        else:
            db.execute_sql(
                """
                INSERT INTO wfs_task_config (
                    pid, group_name, folder_name, task_name, trigger_type, schedule_type,
                    schedule_json, trigger_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params=payload,
            )


def _config_schedule(spec):
    config_path = Path(spec.get('config_path'))
    if not config_path.is_file():
        raise ValueError('config.ini is missing')
    config_base = ConfigObj(str(config_path), encoding='utf-8')
    base = config_base.get('base') or {}
    trigger = str(base.get('TRIGGER') or '').strip().lower()
    rules = dict(config_base.get(trigger) or {}) if trigger else {}
    form = schedule_to_form(trigger, rules)
    return {
        'pid': spec.get('pid'),
        'group_name': spec.get('group_name') or '',
        'folder_name': spec.get('folder_name') or '',
        'task_name': spec.get('task_name') or '',
        'trigger': trigger,
        'rules': rules,
        'source': 'config',
        'form': form,
    }


def _record_schedule(spec, record):
    trigger = record.get('trigger_type') or 'interval'
    rules = _json_loads(record.get('trigger_json'), {})
    saved_form = _json_loads(record.get('schedule_json'), {})
    schedule_type = record.get('schedule_type') or saved_form.get('schedule_type')
    form = schedule_to_form(trigger, rules, schedule_type=schedule_type, saved_form=saved_form)
    return {
        'pid': spec.get('pid'),
        'group_name': record.get('group_name') or spec.get('group_name') or '',
        'folder_name': record.get('folder_name') or spec.get('folder_name') or '',
        'task_name': record.get('task_name') or spec.get('task_name') or '',
        'trigger': trigger,
        'rules': rules,
        'source': 'database',
        'form': form,
    }


def load_schedule(pid):
    spec = find_task_spec(pid)
    if not spec:
        raise ValueError('task not found: {}'.format(pid))
    record = _load_schedule_record(pid)
    data = _record_schedule(spec, record) if record else _config_schedule(spec)
    try:
        data['preview'] = preview_schedule(trigger=data['trigger'], rules=data['rules'])
    except Exception as exc:
        data['preview'] = []
        data['preview_error'] = str(exc)
    return data


def apply_persisted_schedule(spec):
    pid = spec.get('pid')
    if not pid:
        return spec
    record = _load_schedule_record(pid)
    if not record:
        return spec
    data = _record_schedule(spec, record)
    spec['trigger'] = data['trigger']
    spec['schedule_rules'] = data['rules']
    spec['schedule_type'] = data['form'].get('schedule_type')
    spec['schedule_source'] = 'database'
    return spec


def _write_config(config_base, config_path):
    config_path = Path(config_path)
    temp_path = config_path.with_suffix(config_path.suffix + '.tmp')
    original_filename = config_base.filename
    config_base.filename = str(temp_path)
    try:
        config_base.write()
        os.replace(str(temp_path), str(config_path))
    finally:
        config_base.filename = original_filename
        if temp_path.exists():
            temp_path.unlink()


def _save_config_fallback(spec, trigger, rules):
    config_path = Path(spec.get('config_path'))
    original_text = config_path.read_text(encoding='utf-8')
    config_base = ConfigObj(str(config_path), encoding='utf-8')
    base = config_base.get('base')
    if not base:
        raise ValueError('base section is missing')
    if trigger not in TRIGGER_SECTIONS:
        raise ValueError('database table wfs_task_config is required for {}'.format(trigger))
    base['TRIGGER'] = trigger
    for section in TRIGGER_SECTIONS:
        if section in config_base:
            del config_base[section]
    config_base[trigger] = rules
    try:
        _write_config(config_base, config_path)
        next_spec = load_task_spec(spec.get('group_name'), spec.get('folder_name'), spec.get('task_dir'))
        if next_spec.get('error'):
            raise ValueError(next_spec.get('error'))
    except Exception:
        config_path.write_text(original_text, encoding='utf-8')
        raise


def save_schedule(pid, form):
    spec = find_task_spec(pid)
    if not spec:
        raise ValueError('task not found: {}'.format(pid))
    if spec.get('error'):
        raise ValueError('task config is invalid: {}'.format(spec.get('error')))

    trigger, rules, schedule_type = build_schedule_payload(form or {})
    build_scheduler_trigger(trigger, rules)
    try:
        _save_schedule_record(spec, trigger, rules, schedule_type, form or {})
    except Exception:
        _save_config_fallback(spec, trigger, rules)
    return load_schedule(pid)
