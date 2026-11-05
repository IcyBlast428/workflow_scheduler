"""Latest-per-task reads include archives without transferring log bodies."""
import datetime as dt
import unittest
import uuid
from unittest.mock import patch
import test_local_integration as fixture
from app.bootstrap import recent_execution_matrix as recent
from app.bootstrap.database import GaussDB
from app.bootstrap.timebase import business_now


class RecentMatrixTests(unittest.TestCase):
    def test_ten_per_task_archive_deduplication_and_nonfailure_status(self):
        pids=['recent-a','recent-b','empty']
        specs=[{'pid':pid,'task_name':pid,'group_name':'组'+str(index//2)} for index,pid in enumerate(pids)]
        end=business_now()-dt.timedelta(days=1)
        with GaussDB() as db:
            for index in range(57):
                table='wfs_run_history_archive' if index<25 else 'wfs_run_history'
                when=end+dt.timedelta(seconds=index)
                identifier=uuid.uuid4().hex
                row=(identifier,pids[0],0 if index%2 else 1,'LOG_BODY_MUST_NEVER_BE_RETURNED',when,when)
                db.execute_sql(f'INSERT INTO {table}(id,pid,state,tasklog,start_time,end_time) VALUES(?,?,?,?,?,?)',params=row)
                if index==25:db.execute_sql('INSERT INTO wfs_run_history_archive(id,pid,state,tasklog,start_time,end_time) VALUES(?,?,?,?,?,?)',params=row)
            for index,state in enumerate([-15,-10001,-9]):
                when=end+dt.timedelta(seconds=index)
                db.execute_sql('INSERT INTO wfs_run_history(id,pid,state,start_time,end_time) VALUES(?,?,?,?,?)',params=(uuid.uuid4().hex,pids[1],state,when,when))
        with patch.object(recent,'discover_task_specs',return_value=specs):
            data=recent.cached_snapshot()
            for limit in (25,):
                with self.subTest(limit=limit):
                    expanded=recent.cached_snapshot(str(limit))
                    records=expanded['tasks'][0]['records']
                    self.assertEqual(expanded['limit'],limit)
                    self.assertEqual(len({r['key'] for r in records}),limit)
                    self.assertEqual(records[-1]['query_end'],str(end+dt.timedelta(seconds=57-limit)))
        self.assertEqual([len(task['records']) for task in data['tasks']],[10,3,0])
        self.assertEqual(len({r['key'] for r in data['tasks'][0]['records']}),10)
        self.assertEqual([r['status'] for r in data['tasks'][1]['records']],['timed_out','skipped','cancelled'])
        self.assertEqual(data['tasks'][0]['records'][-1]['query_end'],str(end+dt.timedelta(seconds=47)))
        self.assertNotIn('LOG_BODY',str(data))
        self.assertTrue(all(r['scope']=='all' for task in data['tasks'] for r in task['records']))

    def test_empty_and_task_limit(self):
        with patch.object(recent,'discover_task_specs',return_value=[]):self.assertEqual(recent.snapshot()['tasks'],[])
        with patch.object(recent,'discover_task_specs',return_value=[{'pid':str(i)} for i in range(1001)]):
            with self.assertRaises(ValueError):recent.snapshot()

    def test_invalid_depth_is_rejected_before_querying(self):
        with patch.object(recent,'snapshot') as query:
            for value in ('','0','11','50','51','1000','1e1'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    recent.cached_snapshot(value)
            query.assert_not_called()
