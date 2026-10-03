"""Recovery, complete statistics, notification ambiguity and stable task identity."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace
import test_local_integration as shared
from app import create_app
from app.bootstrap import operations as ops, journal, run_summary, notifications
from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import state_status, SKIPPED, MISSED
from app.bootstrap.history import RUN_COLUMNS
from app.bootstrap.task_loader import load_task_spec
from app.api.task import views
from scripts.assign_task_ids import freeze


class ScaleTests(unittest.TestCase):
    def setUp(self):
        self.pid='scale-'+uuid.uuid4().hex

    def tearDown(self):
        with GaussDB() as db:
            for table in ('wfs_run_history','wfs_run_summary','wfs_run_totals','wfs_notifications','wfs_alert_incidents','wfs_job_stats'):
                db.execute_sql(f'DELETE FROM {table} WHERE pid=?',params=(self.pid,))

    def test_journal_lookup_does_not_scan_history_and_locks_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(ops,'_directory',Path(directory)):
            run=ops.create_run(self.pid)
            self.assertFalse(ops.run_path(run).exists())
            with patch.object(Path,'glob',side_effect=AssertionError('full scan')):
                self.assertEqual(ops.list_runs(self.pid)[0]['run_id'],run)
                self.assertEqual(ops.read_run(run)['pid'],self.pid)
            self.assertEqual(len(ops._locks),256)

    def test_legacy_import_preserves_logs_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for i in range(10):
                identifier=uuid.uuid4().hex
                record={'run_id':identifier,'pid':self.pid,'status':'success','created_at':ops.now(),'state':0,'history_saved':True,'db_synced':True}
                (root/(identifier+'.json')).write_text(json.dumps(record))
                (root/(identifier+'.log')).write_text('legacy')
            imported=journal.import_legacy(root,ops.TERMINAL,3)
            self.assertLessEqual(len(imported),3)
            for record in imported:
                with patch.object(ops,'_directory',root):
                    self.assertEqual(ops.run_path(record['run_id'],'log').read_text(),'legacy')
            self.assertGreaterEqual(len(list(root.glob('*.json'))),7)

    def test_recovery_and_hourly_summary_exactly_once(self):
        identifier=ops.create_run(self.pid)
        record=ops.update_run(identifier,status='timed_out',state=-9,end_time=ops.now())
        ops.save_history(record);ops.save_history(ops.read_run(identifier))
        with GaussDB() as db:
            rows=db.execute_query_sql('SELECT status,executions FROM wfs_run_summary WHERE pid=?',params=(self.pid,))
            self.assertEqual(rows,[('timed_out',1)])
            self.assertEqual(db.execute_query_sql('SELECT failures FROM wfs_run_totals WHERE pid=?',params=(self.pid,))[0][0],1)

    def test_dashboard_counts_more_than_1000_records(self):
        stamp=dt.datetime.now().replace(minute=0,second=0,microsecond=0)
        with GaussDB() as db:
            db.begin_transaction()
            for i in range(1205):
                db.execute_sql(f'INSERT INTO wfs_run_history({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)',params=(uuid.uuid4().hex,self.pid,self.pid,'','test','task',1,'',stamp,stamp))
            db.set_commit()
        result=views._recent_run_stats()
        self.assertGreaterEqual(sum(item['failed'] for item in result['trend']),1205)
        run_summary.backfill(5000);run_summary.backfill(5000)
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT failures FROM wfs_run_totals WHERE pid=?',params=(self.pid,))[0][0],1205)

    def test_status_vocabulary_and_skip_history(self):
        self.assertEqual([state_status(value) for value in (0,-9,-15,-1,SKIPPED,MISSED,None)],['success','timed_out','cancelled','interrupted','skipped','missed','unknown'])
        run=ops.create_run(self.pid)
        ops.save_history(ops.update_run(run,status='skipped',state=SKIPPED,end_time=ops.now()))
        self.assertTrue(ops.read_run(run)['history_saved'])
        with GaussDB() as db:
            self.assertFalse(db.execute_query_sql('SELECT failures FROM wfs_run_totals WHERE pid=?',params=(self.pid,)))

    def test_alert_cooldown_recovery_and_timeout_never_resends(self):
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_job_stats(pid,task_name,email_receiver) VALUES(?,?,?)',params=(self.pid,self.pid,'test'))
            with patch.object(notifications,'get_runtime_env',return_value='production'):
                for state in (1,1,0):
                    record={'run_id':uuid.uuid4().hex,'pid':self.pid,'task_name':self.pid,'end_time':ops.now(),'state':state}
                    db.begin_transaction();notifications.enqueue_result(db,record,'test');db.set_commit()
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_notifications WHERE pid=?',params=(self.pid,))[0][0],2)
        with patch.object(notifications,'_resolve',return_value=['test@example.invalid']),patch.object(notifications,'_send',side_effect=TimeoutError('ambiguous')) as sender:
            notifications.process_batch();notifications.process_batch(recover=True)
            self.assertEqual(sender.call_count,2)
        with GaussDB() as db:
            self.assertEqual({row[0] for row in db.execute_query_sql('SELECT status FROM wfs_notifications WHERE pid=?',params=(self.pid,))},{'unknown'})

    def test_task_id_survives_category_and_folder_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);task=root/'old'/'task';task.mkdir(parents=True);(task/'main.py').write_text('pass')
            self.assertEqual(freeze(root),1)
            dest=root/'new'/'renamed';dest.parent.mkdir();task.rename(dest)
            spec=load_task_spec('new','renamed',dest,{})
            self.assertEqual(spec['pid'],'old__task');self.assertEqual(spec['group_name'],'new')

    def test_exact_planned_time_is_passed_to_job_runner(self):
        from app.bootstrap.scheduled_executor import run_with_times
        from apscheduler.events import EVENT_JOB_EXECUTED,EVENT_JOB_MISSED
        results=[]
        def execute_py(**kwargs): results.append(kwargs)
        now=dt.datetime.now(dt.timezone.utc)
        job=SimpleNamespace(func=execute_py,args=[],kwargs={},id=self.pid,_jobstore_alias='default',misfire_grace_time=5)
        events=run_with_times(job,[now-dt.timedelta(seconds=20),now],'test')
        self.assertEqual([event.code for event in events],[EVENT_JOB_MISSED,EVENT_JOB_EXECUTED])
        self.assertEqual(results[0]['scheduled_time'],now.astimezone().replace(tzinfo=None).isoformat(' '))

    def test_matrix_delta_reconciles_updates_removals_and_new_dates(self):
        from app.bootstrap import execution_matrix as matrix,snapshot_cache
        day=dt.date.today().isoformat()
        first={'date':day,'records':[{'key':'a','count':1},{'key':'b','count':1}],'active':[],'pending':[]}
        second={**first,'records':[{'key':'b','count':2},{'key':'c','count':1}]}
        with patch.object(matrix,'snapshot',return_value=first),patch.object(snapshot_cache,'cached',side_effect=lambda key,seconds,factory,**kwargs:factory()):
            initial=matrix.cached_snapshot(day)
        with patch.object(matrix,'snapshot',return_value=second),patch.object(snapshot_cache,'cached',side_effect=lambda key,seconds,factory,**kwargs:factory()):
            delta=matrix.cached_snapshot(day,initial['cursor'])
        self.assertTrue(delta['incremental']);self.assertEqual(delta['removed'],['a'])
        self.assertEqual(delta['records'],second['records'])

    def test_batch_preview_version_conflict_and_viewer_denial(self):
        from app.bootstrap.schedule_config import save_schedule
        pid='testJob__test_job1'
        save_schedule(pid,{'schedule_type':'every_hour','main_file':'main.py','enabled':False})
        client=create_app().test_client()
        login=client.post('/api/user/login',json={'username':'admin','password':'test-password'})
        headers={'X-CSRF-Token':login.json['data']['csrf_token']}
        self.assertEqual(client.post('/api/taskinfo/batch',json=['invalid'],headers=headers).status_code,400)
        preview=client.post('/api/taskinfo/batch',json={'ids':[pid],'action':'pause','preview':True},headers=headers)
        self.assertEqual(preview.status_code,200,preview.json)
        version=preview.json['data']['preview'][0]['version']
        save_schedule(pid,{'schedule_type':'every_hour','main_file':'main.py','enabled':False})
        conflict=client.post('/api/taskinfo/batch',json={'ids':[pid],'action':'pause','versions':{pid:version}},headers=headers)
        self.assertEqual(conflict.status_code,409)
        from app.bootstrap.permissions import allowed
        self.assertFalse(allowed('/api/taskinfo/batch','POST','viewer'))
        self.assertTrue(allowed('/api/taskinfo/batch','POST','operator'))

    @unittest.skipIf(os.name=='nt','Linux backup lease')
    def test_backup_restore_includes_index_and_nested_logs(self):
        from scripts.backup_local import backup
        from scripts.restore_local import restore
        run=ops.create_run(self.pid);log=ops.run_path(run,'log');log.write_text('restore proof')
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'backup.zip';destination=Path(directory)/'restored'
            backup(os.environ['WFS_LOCAL_DB_PATH'],os.environ['WFS_DATA_DIR'],output)
            restore(output,destination)
            with patch.object(ops,'_directory',destination/'data/executions'):
                self.assertEqual(ops.read_run(run)['pid'],self.pid)
                self.assertEqual(ops.run_path(run,'log').read_text(),'restore proof')
            with self.assertRaises(ValueError):restore(output,destination)
