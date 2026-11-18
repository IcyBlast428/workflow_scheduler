"""Archive durability and cursor pagination with same-second executions."""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
import unittest
from unittest.mock import patch

import test_local_integration as shared
from app import create_app
from app.bootstrap.database import GaussDB
from app.bootstrap.history import archive_batch, RUN_COLUMNS
from app.bootstrap import failure_totals, operations, run_summary
from app.api.task import views


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.pid = 'history-' + uuid.uuid4().hex
        self.client = create_app().test_client()
        login = self.client.post('/api/user/login', json={'username':'admin','password':'test-password'})
        self.headers = {'X-CSRF-Token':login.json['data']['csrf_token']}

    def tearDown(self):
        with GaussDB() as db:
            for table in ('wfs_run_history','wfs_run_history_archive','wfs_history_rollup','wfs_run_summary','wfs_run_totals'):
                db.execute_sql(f'DELETE FROM {table} WHERE pid=?', params=(self.pid,))

    def insert(self, identifier, when, state=0, text='中文日志', summarized=True):
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)', params=(identifier,self.pid,self.pid,'test','test','test',state,text,when-dt.timedelta(seconds=2),when))
            if summarized:
                run_summary.summarize_row(db, identifier, self.pid, state, when)

    def query(self, **kwargs):
        return self.client.post('/api/taskinfo/taskLogs', headers=self.headers, query_string={'taskid':self.pid, **kwargs})

    def test_cursor_same_timestamp_no_duplicates_with_new_writes(self):
        stamp = dt.datetime.now().replace(microsecond=0)
        expected = sorted([f'{self.pid[-12:]}-{i:03}' for i in range(15)], reverse=True)
        for identifier in expected:
            self.insert(identifier,stamp)
        response = self.query(pagesize=4)
        self.assertEqual(response.status_code,200)
        result = response.json['data']
        seen = [row['logid'] for row in result['data']]
        self.insert(self.pid[-12:]+'-zzz',stamp+dt.timedelta(seconds=1))
        page = 1
        while result['has_more']:
            page += 1
            response = self.query(pagesize=4,currentPage=page,cursor=result['next_cursor'])
            self.assertEqual(response.status_code,200)
            result = response.json['data']
            seen.extend(row['logid'] for row in result['data'])
        self.assertEqual(seen,expected)

    def test_verified_archive_query_and_log_detail(self):
        stamp = dt.datetime.now()-dt.timedelta(days=120)
        self.insert(self.pid,stamp,state=1)
        cutoff = dt.datetime.now()-dt.timedelta(days=90)
        self.assertEqual(archive_batch(cutoff),1)
        self.assertEqual(archive_batch(cutoff),0)
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history WHERE pid=?',params=(self.pid,))[0][0],0)
            self.assertEqual(db.execute_query_sql('SELECT archived_failures FROM wfs_history_rollup WHERE pid=?',params=(self.pid,))[0][0],1)
        dates = [(stamp-dt.timedelta(days=1)).isoformat(' '),(stamp+dt.timedelta(days=1)).isoformat(' ')]
        result = self.query(scope='all', **{'datetimeval[]':dates}).json['data']
        self.assertEqual(len(result['data']),1)
        row = result['data'][0]
        detail = self.client.post('/api/taskinfo/taskLogDetail', headers=self.headers,query_string={'id':row['logid'],'end_time':row['datetime'],'pid':self.pid})
        self.assertEqual(detail.json['data'],'中文日志')
        self.assertEqual(self.query().json['data']['data'],[])
        views._failure_totals_expiry = 0
        self.assertEqual(views._failure_totals()[self.pid],1)

    def test_unified_non_failure_states_do_not_inflate_archive_totals(self):
        stamp = dt.datetime.now()-dt.timedelta(days=120)
        for index, state in enumerate((-10001, -10002, -15, -1, -9)):
            self.insert(self.pid+str(index), stamp, state=state)
        self.assertEqual(archive_batch(dt.datetime.now()-dt.timedelta(days=90)), 5)
        with GaussDB() as db:
            total = db.execute_query_sql('SELECT archived_failures FROM wfs_history_rollup WHERE pid=?', params=(self.pid,))[0][0]
        self.assertEqual(total, 1)

    def test_failure_counts_during_backfill_and_archive_do_not_lock(self):
        stamp = dt.datetime.now() - dt.timedelta(days=120)
        self.insert(self.pid+'-archived', stamp, state=1)
        self.insert(self.pid+'-pending', stamp, state=-9, summarized=False)
        self.assertEqual(archive_batch(dt.datetime.now()-dt.timedelta(days=90)), 1)
        with patch.object(GaussDB, 'execute_sql', side_effect=AssertionError('normal reads may not lock or write')):
            self.assertEqual(dict(failure_totals.load_totals())[self.pid], 2)
        self.assertEqual(run_summary.backfill(), 1)
        with patch.object(GaussDB, 'execute_sql', side_effect=AssertionError('unexpected counter repair')):
            self.assertEqual(dict(failure_totals.load_totals())[self.pid], 2)

    def test_external_rollup_repair_preserves_unsummarized_failures(self):
        stamp = dt.datetime.now()
        self.insert(self.pid+'-summary', stamp, state=1)
        self.insert(self.pid+'-pending', stamp, state=1, summarized=False)
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_history_rollup(pid,archived_failures) VALUES(?,3)',params=(self.pid,))
        self.assertEqual(dict(failure_totals.load_totals())[self.pid], 5)
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT failures,archived_failures FROM wfs_run_totals WHERE pid=?', params=(self.pid,)), [(4, 3)])
        self.assertEqual(run_summary.backfill(), 1)
        with patch.object(GaussDB, 'execute_sql', side_effect=AssertionError('repair should be complete')):
            self.assertEqual(dict(failure_totals.load_totals())[self.pid], 5)

    def test_two_reconcilers_recheck_after_acquiring_the_lock(self):
        self.insert(self.pid+'-summary', dt.datetime.now(), state=1)
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_history_rollup(pid,archived_failures) VALUES(?,2)', params=(self.pid,))
        initial_reads = threading.Barrier(2, timeout=10)
        first = threading.local()
        original_counts = failure_totals._counts
        repairs = []
        original_write = GaussDB.execute_sql

        def read(db):
            result = original_counts(db)
            if not getattr(first, 'done', False):
                first.done = True
                initial_reads.wait()
            return result

        def write(db, sql, **kwargs):
            if sql.startswith('DELETE FROM wfs_run_totals'):
                repairs.append(sql)
            return original_write(db, sql, **kwargs)

        with patch.object(failure_totals, '_counts', read), patch.object(GaussDB, 'execute_sql', write):
            with ThreadPoolExecutor(max_workers=2) as workers:
                readers = [workers.submit(failure_totals.load_totals) for _ in range(2)]
                self.assertEqual([dict(reader.result())[self.pid] for reader in readers], [3, 3])
        self.assertEqual(len(repairs), 1)

    def test_dashboard_status_lookup_skips_cumulative_counts(self):
        with patch.object(views, '_failure_totals') as totals:
            self.assertEqual(self.client.get('/api/taskinfo/dashboard').status_code, 200)
        totals.assert_not_called()

    def test_archive_mismatch_rolls_back_entire_batch_and_maintenance_retains_history(self):
        stamp = dt.datetime.now()-dt.timedelta(days=120)
        self.insert(self.pid+'-a',stamp)
        self.insert(self.pid+'-b',stamp)
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history_archive({RUN_COLUMNS}) SELECT {RUN_COLUMNS} FROM wfs_run_history WHERE id=?',params=(self.pid+'-b',))
            db.execute_sql('UPDATE wfs_run_history_archive SET tasklog=? WHERE id=?',params=('mismatch',self.pid+'-b'))
        with self.assertRaisesRegex(RuntimeError,'verification'):
            archive_batch(dt.datetime.now()-dt.timedelta(days=90))
        operations.maintenance()
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history WHERE pid=?',params=(self.pid,))[0][0],2)
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history_archive WHERE id=?',params=(self.pid+'-a',))[0][0],0)

    def test_unsummarized_old_history_stays_online_until_backfilled(self):
        stamp = dt.datetime.now() - dt.timedelta(days=120)
        self.insert(self.pid, stamp, state=1, summarized=False)
        cutoff = dt.datetime.now() - dt.timedelta(days=90)
        self.assertEqual(archive_batch(cutoff), 0)
        with GaussDB() as db:
            self.assertFalse(run_summary.coverage(db)['complete'])
            self.assertEqual(db.execute_query_sql('SELECT count(*) FROM wfs_run_history WHERE pid=?', params=(self.pid,))[0][0], 1)
            self.assertEqual(db.execute_query_sql('SELECT count(*) FROM wfs_run_history_archive WHERE pid=?', params=(self.pid,))[0][0], 0)
        self.assertEqual(run_summary.backfill(), 1)
        self.assertEqual(archive_batch(cutoff), 1)
        with GaussDB() as db:
            self.assertTrue(run_summary.coverage(db)['complete'])
            self.assertEqual(db.execute_query_sql('SELECT sum(executions) FROM wfs_run_summary WHERE pid=?', params=(self.pid,))[0][0], 1)
            self.assertEqual(db.execute_query_sql('SELECT failures FROM wfs_run_totals WHERE pid=?', params=(self.pid,))[0][0], 1)
        self.assertEqual(run_summary.backfill(), 0)

    def test_invalid_range_cursor_and_online_retention_guard(self):
        stamp = dt.datetime.now()
        self.insert(self.pid+'1',stamp)
        self.insert(self.pid+'2',stamp)
        today = stamp.date().isoformat()
        self.assertEqual(len(self.query(**{'datetimeval[]':[today,today]}).json['data']['data']),2)
        cursor = self.query(pagesize=1).json['data']['next_cursor']
        self.assertEqual(self.query(pagesize=1,cursor=cursor,taskstate='失败').status_code,400)
        self.assertEqual(self.query(cursor='invalid').status_code,400)
        self.assertEqual(self.query(**{'datetimeval[]':['2020-01-01','2021-01-01']}).status_code,400)
        with self.assertRaises(ValueError):
            archive_batch(dt.datetime.now()-dt.timedelta(days=30))

    def test_live_marker_counts_only_latest_timestamp_and_detects_ties(self):
        # This marker is global: other tests can retain records in business time,
        # ahead of the host clock. Put this fixture after the actual latest row.
        from app.bootstrap.timebase import business_now
        with GaussDB() as db:
            latest = db.execute_query_sql('SELECT MAX(end_time) FROM wfs_run_history')[0][0]
        stamp = max(business_now(), dt.datetime.fromisoformat(str(latest)) if latest else business_now())+dt.timedelta(minutes=1)
        self.insert(self.pid+'z',stamp)
        self.insert(self.pid+'y',stamp)
        self.insert(self.pid+'old',stamp-dt.timedelta(days=1))
        before = views._latest_log_marker()
        self.assertEqual(before['count'],2)
        self.insert(self.pid+'a',stamp)
        after = views._latest_log_marker()
        self.assertEqual(before['latest_id'],after['latest_id'])
        self.assertEqual(after['count'],3)
