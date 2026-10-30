"""Burst admission, durable recovery, bounded waiting, and real launch spacing."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_local_integration
from app.bootstrap import admission,execution_requests as queue,operational_policy as policy,dispatch_control as control,core
from app.bootstrap.global_vars import RunningState
from app.bootstrap.timebase import business_now

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'WFS_DATA_DIR':str(self.root)})
        self.env.start()
        self.reset=patch.object(control,'_next_start',0);self.reset.start()
    def tearDown(self):
        self.reset.stop();self.env.stop();self.temp.cleanup()
    def configure(self,**values):
        return policy.save('dispatch','',{**policy.load('dispatch'),**values},'admin')
    def job(self,pid='task',grace=600):
        return SimpleNamespace(id=pid,func=core.execute_py,args=[str(self.root/'main.py'),pid,pid,'',0,'group','folder','',1],
                               kwargs={'limits':{'_schedule_revision':3}},misfire_grace_time=grace)
    def test_simultaneous_firings_are_bounded_durable_and_deduplicated(self):
        self.configure(max_pending=30)
        planned=business_now()
        from app.bootstrap.scheduled_executor import ScheduledExecutor
        executor=ScheduledExecutor(max_workers=1)
        try:
            for n in range(100):executor.submit_job(self.job(str(n)),[planned])
            for n in range(100):executor.submit_job(self.job(str(n)),[planned])
        finally:executor.shutdown()
        snapshot=queue.snapshot();self.assertEqual(len(snapshot),100)
        self.assertEqual(sum(r['status']=='pending' for r in snapshot),30)
        self.assertEqual(sum(r['status']=='rejected' for r in snapshot),70)
        self.assertEqual(queue.queue_status()['counts']['pending'],30)
    def test_per_task_bound_and_manual_bound_are_enforced(self):
        self.configure(max_pending_per_task=2)
        for n in range(3):queue.enqueue_scheduled(self.job(),business_now()+dt.timedelta(seconds=n))
        self.assertEqual(sum(r['status']=='pending' for r in queue.snapshot()),2)
        with self.assertRaises(ValueError):queue.enqueue('task','manual',{},'admin')
    def test_stagger_is_stable_opt_in_and_preserves_planned_time(self):
        planned=business_now();job=self.job()
        key=queue.enqueue_scheduled(job,planned);row=queue.snapshot()[0]
        self.assertEqual(row['due_at'],str(planned))
        policy.save('task','task',{**policy.load('task','task'),'stagger_seconds':60},'admin')
        first=planned+dt.timedelta(minutes=1);queue.enqueue_scheduled(job,first)
        second=first+dt.timedelta(minutes=1);queue.enqueue_scheduled(job,second)
        rows=[r for r in queue.snapshot() if r['id']!=key]
        offsets=[(dt.datetime.fromisoformat(r['due_at'])-dt.datetime.fromisoformat(json.loads(r['context'])['scheduled_time'])).total_seconds() for r in rows]
        self.assertEqual(offsets[0],offsets[1]);self.assertTrue(0<=offsets[0]<=60)
        for r in rows:self.assertEqual((dt.datetime.fromisoformat(r['expires_at'])-dt.datetime.fromisoformat(json.loads(r['context'])['scheduled_time'])).total_seconds(),600)
    def test_expiry_runs_during_maintenance_and_never_dispatches(self):
        planned=business_now()-dt.timedelta(seconds=20)
        queue.enqueue_scheduled(self.job(grace=10),planned)
        key=queue.enqueue('pending','manual',{},'admin')
        with admission.store() as db:db.execute("UPDATE work_requests SET expires_at='2000-01-01' WHERE id=?",(key,))
        admission.set_maintenance(True,0,'pause','admin')
        with patch.object(core,'call_task_once') as submit:queue.dispatch();submit.assert_not_called()
        self.assertEqual({r['status'] for r in queue.snapshot()},{'expired'})
        queue.enqueue_scheduled(self.job('during-maintenance'),business_now())
        self.assertEqual(next(r for r in queue.snapshot() if r['pid']=='during-maintenance')['status'],'cancelled')
    def test_recovery_never_replays_ambiguous_dispatch_and_resumes_pending(self):
        one=queue.enqueue('one','manual',{},'admin');queue.enqueue('two','manual',{},'admin')
        with admission.store() as db:db.execute("UPDATE work_requests SET status='dispatching' WHERE id=?",(one,))
        with patch.object(core,'call_task_once',return_value='run-id') as submit:
            queue.dispatch(recover=True);queue.dispatch();self.assertEqual(submit.call_count,1)
            self.assertEqual(submit.call_args.args[0],'two')
        self.assertEqual({r['status'] for r in queue.snapshot()},{'unknown','accepted'})
    def test_blocked_task_does_not_starve_another_task_or_reset_deadline(self):
        queue.enqueue('blocked','manual',{},'admin');queue.enqueue('other','manual',{},'admin')
        expiry=next(r['expires_at'] for r in queue.snapshot() if r['pid']=='blocked')
        def submit(pid,**kwargs):
            if pid=='blocked':raise admission.CapacityUnavailable('等待名额')
            return 'run'
        with patch.object(core,'call_task_once',side_effect=submit):queue.dispatch()
        rows={r['pid']:r for r in queue.snapshot()}
        self.assertEqual(rows['blocked']['status'],'pending');self.assertEqual(rows['other']['status'],'accepted')
        self.assertEqual(rows['blocked']['expires_at'],expiry)
    def test_launch_interval_is_atomic_across_competing_workers(self):
        self.configure(start_interval_ms=1000)
        results=[]
        with patch.object(control.time,'monotonic',return_value=100):
            workers=[threading.Thread(target=lambda:results.append(control.reserve_launch())) for _ in range(20)]
            for worker in workers:worker.start()
            for worker in workers:worker.join()
        self.assertEqual(sum(results),1)
        with patch.object(control.time,'monotonic',return_value=100.999):self.assertFalse(control.reserve_launch())
        with patch.object(control.time,'monotonic',return_value=101):self.assertTrue(control.reserve_launch())
    def test_load_protection_uses_sustained_threshold_and_hysteresis(self):
        self.configure(load_protection=True)
        with patch.object(control,'_high_samples',0),patch.object(control,'_low_samples',0),patch.object(control,'_blocked',False):
            with patch.object(control,'_measure',return_value=(95,50)):
                control.sample();control.sample();self.assertFalse(control._blocked)
                control.sample();self.assertTrue(control._blocked);self.assertFalse(control.reserve_launch())
            with patch.object(control,'_measure',return_value=(80,50)):
                for _ in range(3):control.sample()
                self.assertTrue(control._blocked)
            with patch.object(control,'_measure',return_value=(30,50)):
                control.sample();control.sample();self.assertTrue(control._blocked)
                control.sample();self.assertFalse(control._blocked);self.assertTrue(control.reserve_launch())
            with patch.object(control,'_sample_at',0):self.assertFalse(control.reserve_launch())
    def test_lower_concurrency_drains_without_stopping_existing_runs(self):
        state=RunningState();self.configure(max_active=2)
        a=state.claim('a');b=state.claim('b');self.assertIsNotNone(b)
        self.configure(max_active=1);self.assertIsNone(state.claim('c'));self.assertEqual(state.count(),2)
        state.remove(a);self.assertIsNone(state.claim('c'));state.remove(b);self.assertIsNotNone(state.claim('c'))
    def test_expired_launch_and_cancel_never_consume_a_start(self):
        reservation=object()
        with patch.object(control,'reserve_launch') as launch:
            with self.assertRaises(control.LaunchExpired):control.wait_for_launch(reservation,'2000-01-01')
            launch.assert_not_called()
    def test_legacy_queue_migration_preserves_existing_pending_requests(self):
        with admission.store() as db:
            db.execute("CREATE TABLE work_requests(id TEXT PRIMARY KEY,pid TEXT,kind TEXT,status TEXT,payload TEXT,created_at TEXT,due_at TEXT,run_id TEXT,message TEXT)")
            db.execute("INSERT INTO work_requests VALUES('old-request','task','manual','pending','{}','2026-01-01','2026-01-01','','')")
        row=queue.snapshot()[0]
        self.assertEqual(row['id'],'old-request');self.assertEqual(row['status'],'pending');self.assertEqual(row['expires_at'],'')

    def test_queue_filters_before_pagination_and_reports_full_waiting_totals(self):
        from app.bootstrap import task_loader
        created=str(business_now()-dt.timedelta(seconds=125))
        with admission.store() as db:
            queue.table(db)
            for n in range(130):
                db.execute("INSERT INTO work_requests(id,pid,kind,status,payload,created_at,due_at) VALUES(?,?,?,?,?,?,?)",
                           (f'q{n:03}',f'task{n:03}','scheduled','pending' if n<60 else 'expired','{}',created,created))
        with patch.object(task_loader,'discover_task_specs',return_value=[{'pid':'task129','task_name':'日报核对'}]):
            value=queue.queue_status('expired','日报',include_names=True)
            self.assertEqual(value['total'],1);self.assertEqual(value['items'][0]['pid'],'task129')
            self.assertEqual(value['items'][0]['task_name'],'日报核对')
            self.assertEqual(value['counts']['pending'],60);self.assertGreaterEqual(value['oldest_wait_seconds'],125)
            pages=[queue.queue_status('pending',page=n,include_names=True) for n in (1,2,3)]
            ids=[row['id'] for page in pages for row in page['items']]
            self.assertEqual(len(ids),60);self.assertEqual(len(set(ids)),60)
            self.assertEqual(queue.queue_status(query="%' OR 1=1 --",include_names=True)['total'],0)
            self.assertEqual(queue.queue_status('pending',page=99,include_names=True)['page'],3)
        with self.assertRaises(ValueError):queue.queue_status('invalid')
        with self.assertRaises(ValueError):queue.queue_status(page=0)

    def test_policy_rejects_invalid_limits_and_stale_updates(self):
        for field,value in [('max_active',21),('max_pending',0),('max_wait_seconds',0),('start_interval_ms',0),('load_protection',1)]:
            with self.assertRaises(ValueError):self.configure(**{field:value})
        old=policy.load('dispatch');self.configure(max_active=3)
        with self.assertRaises(RuntimeError):policy.save('dispatch','',old,'admin')

class QueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_operational_workflows as fixture
        self.fixture=fixture.OperationalTests();self.fixture.setUp()
        self.reset=patch.object(control,'_next_start',0);self.reset.start()
    def tearDown(self):self.reset.stop();self.fixture.tearDown()
    def scheduled(self):
        from app.extensions import scheduler
        from app.bootstrap.schedule_config import save_schedule
        data=self.fixture.ready(self.fixture.new());self.fixture.activate(data)
        save_schedule(data['pid'],{'schedule_type':'every_hour','main_file':'main.py','enabled':True})
        core.aps_start(task_pid=data['pid'])
        return data,scheduler.get_job(data['pid'])
    def test_scheduled_execution_retains_version_time_parameters_and_source(self):
        from app.bootstrap import operations,task_packages
        data,job=self.scheduled();pid=data['pid'];planned=business_now()-dt.timedelta(seconds=2)
        queue.enqueue_scheduled(job,planned)
        context=json.loads(queue.snapshot(pid)[0]['context']);self.assertEqual(context['version'],data['version'])
        from test_task_packages import archive
        replacement=self.fixture.ready(task_packages.stage(archive({'main.py':'print("NEW_RELEASE")'}),{'pid':pid},'admin'))
        self.fixture.activate(replacement)
        queue.dispatch();self.fixture.run_pending(pid)
        row=queue.snapshot(pid)[0];record=operations.read_run(row['run_id'])
        self.assertEqual(record['status'],'success',record['reason']);self.assertEqual(record['source'],'scheduled')
        self.assertEqual(record['scheduled_time'],str(planned));self.assertEqual(record['code_version']['task_release'],data['version'])
        self.assertGreaterEqual(record['start_delay_seconds'],2)
    def test_real_burst_executes_all_without_exceeding_capacity_or_start_rate(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.extensions import scheduler
        from app.bootstrap import operations
        from app.bootstrap.global_vars import runnings
        from app.bootstrap.scheduled_executor import ScheduledExecutor
        policy.save('dispatch','',{**policy.load('dispatch'),'max_active':3,'start_interval_ms':150},'admin')
        script=self.fixture.root/'burst.py';script.write_text('import time\ntime.sleep(0.25)\nprint("BURST_OK")')
        specs=[dict(pid='burst_'+str(n),main_file_path=str(script),task_name='Burst',dir_name='',
                    group_name='burst',folder_name='test',timeout_seconds=10,python_executable='',max_instances=1,
                    schedule_enabled=True,config_record={'version':1},schedule_form={}) for n in range(12)]
        executor=ScheduledExecutor(max_workers=1);futures=[];planned=business_now()
        for spec in specs:
            job=SimpleNamespace(func=core.execute_py,args=[str(script),spec['pid'],'Burst','',10,'burst','test','',1],
                                kwargs={'limits':{'_schedule_revision':1}},misfire_grace_time=60)
            executor.submit_job(job,[planned])
        executor.shutdown()
        try:
            with patch.object(core,'discover_task_specs',return_value=specs),ThreadPoolExecutor(max_workers=3) as pool:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    queue.dispatch()
                    self.assertLessEqual(runnings.count(),3)
                    for job in scheduler.get_jobs():
                        if job.id.startswith('manual_burst_'):
                            scheduler.remove_job(job.id)
                            futures.append(pool.submit(core.execute_manual,*job.args,**job.kwargs))
                    if len(futures)==12 and all(f.done() for f in futures):break
                    time.sleep(.05)
                self.assertEqual(len(futures),12)
                for future in futures:self.assertEqual(future.result(timeout=5),0)
            records=[operations.read_run(row['run_id']) for row in queue.snapshot()]
            self.assertEqual(len(records),12)
            self.assertTrue(all(row['status']=='success' for row in records))
            times=sorted(dt.datetime.fromisoformat(row['start_time']) for row in records)
            self.assertTrue(all((b-a).total_seconds()>=.13 for a,b in zip(times,times[1:])),times)
            self.assertEqual(runnings.count(),0)
        finally:
            for job in scheduler.get_jobs():
                if job.id.startswith('manual_burst_'):scheduler.remove_job(job.id)

    def test_disabling_schedule_cancels_pending_plan_without_execution(self):
        from app.bootstrap.schedule_config import set_schedule_enabled
        data,job=self.scheduled();queue.enqueue_scheduled(job,business_now())
        set_schedule_enabled(data['pid'],False)
        queue.dispatch();row=queue.snapshot(data['pid'])[0]
        self.assertEqual(row['status'],'cancelled');self.assertFalse(row['run_id'])
        with admission.store() as db:self.assertFalse(db.execute('SELECT 1 FROM receipts').fetchone())

if __name__=='__main__':unittest.main()
