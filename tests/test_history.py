"""Archive durability and cursor pagination with same-second executions."""
import datetime as dt
import uuid
import unittest

import test_local_integration as shared
from app import create_app
from app.bootstrap.database import GaussDB
from app.bootstrap.history import archive_batch, RUN_COLUMNS
from app.bootstrap import operations
from app.api.task import views


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.pid = 'history-' + uuid.uuid4().hex
        self.client = create_app().test_client()
        login = self.client.post('/api/user/login', json={'username':'admin','password':'test-password'})
        self.headers = {'X-CSRF-Token':login.json['data']['csrf_token']}

    def tearDown(self):
        with GaussDB() as db:
            for table in ('wfs_run_history','wfs_run_history_archive','wfs_history_rollup'):
                db.execute_sql(f'DELETE FROM {table} WHERE pid=?', params=(self.pid,))

    def insert(self, identifier, when, state=0, text='中文日志'):
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)', params=(identifier,self.pid,self.pid,'test','test','test',state,text,when-dt.timedelta(seconds=2),when))

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
        stamp = dt.datetime.now()+dt.timedelta(minutes=1)
        self.insert(self.pid+'z',stamp)
        self.insert(self.pid+'y',stamp)
        self.insert(self.pid+'old',stamp-dt.timedelta(days=1))
        before = views._latest_log_marker()
        self.assertEqual(before['count'],2)
        self.insert(self.pid+'a',stamp)
        after = views._latest_log_marker()
        self.assertEqual(before['latest_id'],after['latest_id'])
        self.assertEqual(after['count'],3)
