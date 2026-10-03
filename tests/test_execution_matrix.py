"""Real SQL snapshot bounds, status preservation and precise log drilldown."""
import datetime as dt
import json
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace

import test_local_integration as shared
from app import create_app
from app.bootstrap.database import GaussDB
from app.bootstrap.history import RUN_COLUMNS
from app.bootstrap import execution_matrix as matrix


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.pid = 'matrix-' + uuid.uuid4().hex
        self.day = dt.date.today()-dt.timedelta(days=1)
        self.start = dt.datetime.combine(self.day, dt.time())
        self.client = create_app().test_client()
        login = self.client.post('/api/user/login', json={'username':'admin','password':'test-password'})
        self.headers = {'X-CSRF-Token':login.json['data']['csrf_token']}
        self.tasks = patch.object(matrix, 'discover_task_specs', return_value=[{'pid':self.pid,'task_name':'矩阵测试','group_name':'测试'}])
        self.tasks.start()
        self.jobs = patch.object(matrix.scheduler, 'get_job', return_value=None)
        self.jobs.start()

    def tearDown(self):
        self.tasks.stop()
        self.jobs.stop()
        with GaussDB() as db:
            for table in ('wfs_run_history','wfs_executions'):
                db.execute_sql(f'DELETE FROM {table} WHERE pid=?', params=(self.pid,))

    def insert(self, when, state=0):
        with GaussDB() as db:
            db.execute_sql(f'INSERT INTO wfs_run_history({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)',params=(uuid.uuid4().hex,self.pid,'任务','dir','测试','folder',state,'THIS LOG BODY MUST NOT REACH THE SNAPSHOT',when-dt.timedelta(seconds=2),when))

    def test_authenticated_raw_snapshot_and_precise_completion_query(self):
        stamp=self.start+dt.timedelta(hours=12,microseconds=123456)
        self.insert(stamp)
        self.insert(stamp+dt.timedelta(seconds=1),-9)
        self.insert(self.start-dt.timedelta(microseconds=1))
        self.insert(self.start+dt.timedelta(days=1))
        response=self.client.get('/api/taskinfo/matrix',query_string={'date':self.day.isoformat()})
        self.assertEqual(response.status_code,200,response.json)
        data=response.json['data']
        self.assertEqual(data['total_executions'],2)
        self.assertFalse(data['aggregated'])
        self.assertEqual({r['status'] for r in data['records']},{'success','timed_out'})
        self.assertNotIn('LOG BODY',json.dumps(data))
        self.assertFalse(data['active'])
        row=next(r for r in data['records'] if r['status']=='success')
        self.assertEqual(row['duration'],2)
        logs=self.client.post('/api/taskinfo/taskLogs',headers=self.headers,query_string={'taskid':self.pid,'datetimeval[]':[row['query_start'],row['query_end']]})
        self.assertEqual(len(logs.json['data']['data']),1,logs.json)
        self.assertEqual(logs.json['data']['data'][0]['logid'],row['run_id'])
        self.assertEqual(create_app().test_client().get('/api/taskinfo/matrix').status_code,401)

    def test_aggregation_keeps_failure_counts_and_half_open_bin(self):
        for i in range(12): self.insert(self.start+dt.timedelta(hours=1,seconds=i),1 if i==7 else 0)
        # With 20 marks the bucket becomes 75 minutes; this lies exactly in the next bin.
        self.insert(self.start+dt.timedelta(minutes=75),-15)
        with patch.object(matrix,'MAX_MARKS',20):
            for i in range(10): self.insert(self.start+dt.timedelta(hours=2,seconds=i))
            data=matrix.snapshot(self.day.isoformat())
        self.assertTrue(data['aggregated'])
        self.assertLessEqual(len(data['records']),20)
        self.assertEqual(data['total_executions'],23)
        failed=next(r for r in data['records'] if r['failed'])
        self.assertEqual((failed['status'],failed['count'],failed['failed']),('failed',12,1))
        logs=self.client.post('/api/taskinfo/taskLogs',headers=self.headers,query_string={'taskid':self.pid,'pagesize':100,'datetimeval[]':[failed['query_start'],failed['query_end']]})
        self.assertEqual(len(logs.json['data']['data']),12,logs.json)

    def test_current_active_journal_and_invalid_date(self):
        now=dt.datetime.now()-dt.timedelta(seconds=2)
        identifier=uuid.uuid4().hex
        payload={'pid':self.pid,'status':'queued','created_at':now.isoformat(' ')}
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_executions(run_id,pid,status,created_at,payload) VALUES(?,?,?,?,?)',params=(identifier,self.pid,'queued',now,json.dumps(payload)))
        fresh={**payload,'status':'running','start_time':now.isoformat(' ')}
        with patch.object(matrix,'read_run',return_value=fresh) as read:
            data=matrix.snapshot()
        self.assertEqual(data['active'][0]['status'],'running')
        self.assertTrue(data['active'][0]['inspectable'])
        read.assert_called_once_with(identifier)
        for value in ['bad',(dt.date.today()+dt.timedelta(days=1)).isoformat(),(dt.date.today()-dt.timedelta(days=90)).isoformat()]:
            self.assertEqual(self.client.get('/api/taskinfo/matrix',query_string={'date':value}).status_code,400)


if __name__=='__main__': unittest.main()
