"""Calendar boundaries and completed single-run plans must remain predictable."""
import calendar
import datetime as dt
import unittest
from unittest.mock import patch
import test_local_integration as shared
from app.bootstrap import core
from app.bootstrap.schedule_config import SCHEDULER_TZ, build_schedule_payload, build_scheduler_trigger, preview_schedule


class ScheduleRuleTests(unittest.TestCase):
    def test_all_supported_schedule_types_have_ordered_future_previews(self):
        future = (dt.datetime.now(SCHEDULER_TZ)+dt.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        cases = [
            {'schedule_type':'every_minute'}, {'schedule_type':'every_hour'},
            {'schedule_type':'interval_minutes','interval_minutes':3},
            {'schedule_type':'interval_hours','interval_hours':2},
            {'schedule_type':'daily_fixed','fixed_time':'08:15'},
            {'schedule_type':'weekly_fixed','weekday':'mon','fixed_time':'08:15'},
            {'schedule_type':'monthly_fixed','month_day':31},
            {'schedule_type':'monthly_last_day'},
            {'schedule_type':'window_minutes','window_start':'09:30','window_end':'11:00','window_interval_minutes':40},
            {'schedule_type':'once_at','run_datetime':future},
            {'schedule_type':'custom_cron','cron_minute':'*/15','cron_hour':'9-17','cron_day_of_week':'mon-fri'},
        ]
        for form in cases:
            with self.subTest(form=form):
                rows = preview_schedule(form=form)
                self.assertEqual(len(rows), 1 if form['schedule_type']=='once_at' else 16)
                dates = [dt.datetime.fromisoformat(row['datetime']) for row in rows]
                self.assertEqual(dates, sorted(set(dates)))
                self.assertTrue(all(SCHEDULER_TZ.localize(date)>dt.datetime.now(SCHEDULER_TZ)-dt.timedelta(seconds=1) for date in dates))
                if form['schedule_type']=='monthly_fixed':
                    self.assertTrue(all(date.day==31 for date in dates))
                if form['schedule_type']=='monthly_last_day':
                    self.assertTrue(all(date.day==calendar.monthrange(date.year,date.month)[1] for date in dates))
                if form['schedule_type']=='window_minutes':
                    self.assertTrue(all(date.strftime('%H:%M') in ('09:30','10:10','10:50') for date in dates))

    def test_expired_once_has_no_future_preview(self):
        past = (dt.datetime.now(SCHEDULER_TZ)-dt.timedelta(seconds=60)).strftime('%Y-%m-%d %H:%M:%S')
        rules = {'RUN_DATE':past}
        self.assertEqual(preview_schedule(trigger='date',rules=rules), [])

    def test_expired_once_is_not_registered_again(self):
        past = (dt.datetime.now(SCHEDULER_TZ)-dt.timedelta(seconds=60)).strftime('%Y-%m-%d %H:%M:%S')
        rules = {'RUN_DATE':past}
        spec = {'pid':'completed-once','trigger':'date','schedule_rules':rules,
                'schedule_configured':True,'schedule_enabled':True,'start_enabled':True,
                'raw_start':'true','main_file_path':str(shared._tmp.name)+'/once.py'}
        with patch.object(core,'discover_task_specs',return_value=[spec]), \
             patch.object(core.scheduler,'get_job',return_value=None), \
             patch.object(core.scheduler,'add_job') as add, \
             patch.object(core.scheduler,'resume_job'), \
             patch.object(core,'_sync_job_stats'), patch.object(core,'record_application'):
            core.aps_start(task_pid=spec['pid'])
        add.assert_not_called()

    def test_zero_intervals_are_rejected_instead_of_silently_becoming_one(self):
        for name,key in [('interval_minutes','interval_minutes'),('interval_hours','interval_hours'),
                         ('window_minutes','window_interval_minutes')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_schedule_payload({'schedule_type':name,key:0})

    def test_invalid_calendar_and_cron_values_are_rejected(self):
        for form in [{'schedule_type':'daily_fixed','fixed_time':'25:10'},
                     {'schedule_type':'monthly_fixed','month_day':32},
                     {'schedule_type':'weekly_fixed','weekday':'bad'},
                     {'schedule_type':'window_minutes','window_start':'18:00','window_end':'09:00'},
                     {'schedule_type':'custom_cron','cron_minute':'61'}]:
            with self.subTest(form=form), self.assertRaises(ValueError):
                trigger,rules,_ = build_schedule_payload(form)
                build_scheduler_trigger(trigger,rules)
