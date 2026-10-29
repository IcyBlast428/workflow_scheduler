"""Operational policies, dispatch crash recovery, grants and publication gates."""
import datetime as dt
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
import test_task_packages as fixture
from app.bootstrap import admission,operational_policy as policy,execution_requests as requests
from app.bootstrap import task_packages as packages,core,task_loader,operations
from app.bootstrap.database import GaussDB
from app.extensions import scheduler

class OperationalTests(unittest.TestCase):
    new=fixture.PackageTests.new
    ready=fixture.PackageTests.ready
    activate=fixture.PackageTests.activate
    def setUp(self):
        fixture.PackageTests.setUp(self)
        self.environment=patch.dict(os.environ,{'WFS_DATA_DIR':str(self.root/'data')})
        self.environment.start()
    def tearDown(self):
        self.environment.stop()
        fixture.PackageTests.tearDown(self)
    def configure(self,pid,**values):
        return policy.save('task',pid,{**policy.load('task',pid),**values},'admin')
    def run_pending(self,pid):
        job=next(j for j in scheduler.get_jobs() if j.id.startswith('manual_'+pid+'_'))
        scheduler.remove_job(job.id)
        return core.execute_manual(*job.args,**job.kwargs)

    def test_policy_rejects_unsafe_retry_invalid_windows_and_stale_edits(self):
        with self.assertRaises(ValueError): self.configure('task',retry_enabled=True,retry_limit=1)
        saved=self.configure('task',idempotent=True,retry_enabled=True,retry_limit=1)
        with self.assertRaises(RuntimeError): policy.save('task','task',{**saved,'revision':0},'admin')
        with self.assertRaises(ValueError): self.configure('task',retry_limit=4)
        with self.assertRaises(ValueError): self.configure('task',parameters={'bad-key':1})
        with self.assertRaises(ValueError): policy.save('release','',{**policy.load('release'),'window_start':'25:00'},'admin')
        self.assertFalse(policy.load('task','other')['retry_enabled'])

    def test_failed_script_retries_once_with_pinned_version_and_parameters(self):
        code="import os,sys\nfrom pathlib import Path\nflag=Path(os.environ['WFS_TASK_DATA_DIR'])/'once'\nif not flag.exists():\n flag.write_text('started');sys.exit(1)\nprint('RETRY_OK')\n"
        data=self.ready(self.new({'main.py':code}));self.activate(data);pid=data['pid']
        self.configure(pid,idempotent=True,retry_enabled=True,retry_limit=1,parameters={'country':'CN'})
        spec=task_loader.discover_task_specs()[0]
        core.execute_py(spec['main_file_path'],pid,python_executable=spec['python_executable'])
        queued=requests.snapshot(pid);self.assertEqual(len(queued),1)
        context=json.loads(queued[0]['context']);self.assertEqual(context['version'],data['version']);self.assertEqual(context['retry_attempt'],1)
        with admission.store() as db: db.execute("UPDATE work_requests SET due_at='2000-01-01' WHERE id=?",(queued[0]['id'],))
        requests.dispatch();self.run_pending(pid)
        accepted=requests.snapshot(pid)[0];record=operations.read_run(accepted['run_id'])
        self.assertEqual(record['status'],'success',record['reason']);self.assertEqual(record['source'],'retry')
        self.assertEqual(record['parameters'],{'country':'CN'});self.assertEqual(len(requests.snapshot(pid)),1)

    def test_timeouts_and_unknown_dispatch_do_not_automatically_replay(self):
        self.configure('task',idempotent=True,retry_enabled=True,retry_limit=3)
        for status in ('timed_out','cancelled','interrupted','skipped'):
            requests.retry_result({'pid':'task','run_id':'f'*32,'status':status})
        self.assertEqual(requests.snapshot(),[])
        identifier=requests.enqueue('task','manual',{},'admin')
        with patch.object(core,'call_task_once',side_effect=RuntimeError('uncertain')) as submit:
            requests.dispatch();requests.dispatch();self.assertEqual(submit.call_count,1)
        self.assertEqual(requests.snapshot()[0]['status'],'unknown')
        with admission.store() as db: db.execute("UPDATE work_requests SET status='dispatching' WHERE id=?",(identifier,))
        requests.dispatch(recover=True);self.assertEqual(requests.snapshot()[0]['status'],'unknown')

    def test_capacity_deferral_keeps_request_pending_and_safe_to_dispatch(self):
        identifier=requests.enqueue('task','manual',{},'admin')
        with patch.object(core,'call_task_once',side_effect=admission.CapacityUnavailable('capacity')):
            requests.dispatch()
        self.assertEqual(requests.snapshot()[0]['status'],'pending')
        with admission.store() as db:
            self.assertFalse(db.execute('SELECT 1 FROM receipts').fetchone())
            db.execute("UPDATE work_requests SET due_at='2000-01-01' WHERE id=?",(identifier,))
        with patch.object(core,'call_task_once',return_value='a'*32) as submit:
            requests.dispatch();requests.dispatch();self.assertEqual(submit.call_count,1)
        self.assertEqual(requests.snapshot()[0]['status'],'accepted')

    def test_sdk_wheel_is_repeatable_and_excludes_platform_config(self):
        import zipfile
        from scripts.build_task_sdk import build
        first=build('1.0.0',self.root/'sdk-one');second=build('1.0.0',self.root/'sdk-two')
        self.assertEqual(first.read_bytes(),second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            names=archive.namelist()
            self.assertIn('app/common/database.py',names)
            self.assertFalse(any('/config/' in name or '/jobs/' in name for name in names))
            self.assertIn(b'Version: 1.0.0',archive.read('workflow_scheduler_task_sdk-1.0.0.dist-info/METADATA'))

    def test_backfill_requires_explicit_idempotence_and_valid_business_date(self):
        with self.assertRaises(ValueError): requests.enqueue('task','backfill',{'business_date':'2026-01-01'},'admin')
        self.configure('task',idempotent=True)
        with self.assertRaises(ValueError): requests.enqueue('task','backfill',{'business_date':'2999-01-01'},'admin')
        identifier=requests.enqueue('task','backfill',{'business_date':'2026-01-01'},'admin')
        requests.cancel(identifier);self.assertEqual(requests.snapshot()[0]['status'],'cancelled')
        with self.assertRaises(RuntimeError):requests.cancel(identifier)

    def test_maintenance_preserves_pending_requests_and_policy_disable_cancels_retry(self):
        self.configure('task',idempotent=True,retry_enabled=True,retry_limit=1)
        identifier=requests.enqueue('task','retry',{'retry_attempt':1},'admin')
        state=admission.set_maintenance(True,0,'upgrade','admin');requests.dispatch()
        self.assertEqual(requests.snapshot()[0]['status'],'pending')
        admission.set_maintenance(False,state['revision'],'','admin');self.configure('task',retry_enabled=False)
        with patch.object(core,'call_task_once') as submit: requests.dispatch();submit.assert_not_called()
        self.assertEqual(requests.snapshot()[0]['status'],'unknown')

    def test_trial_executes_candidate_without_changing_publication_or_statistics(self):
        data=self.ready(self.new({'main.py':'import os\nassert os.environ["WFS_EXECUTION_SOURCE"]=="trial"\nprint("TRIAL_OK")'}));self.activate(data);pid=data['pid']
        with GaussDB() as db: before=db.execute_query_sql('SELECT last_status,failed_times FROM wfs_job_stats WHERE pid=?',params=(pid,))
        identifier=requests.enqueue(pid,'trial',{'version':data['version']},'admin');requests.dispatch();self.run_pending(pid)
        row=requests.snapshot(pid)[0];record=operations.read_run(row['run_id'])
        self.assertEqual(record['status'],'success',record['reason']);self.assertEqual(record['source'],'trial')
        self.assertEqual(packages.task(pid)['active_version'],data['version'])
        with GaussDB() as db:
            self.assertEqual(db.execute_query_sql('SELECT last_status,failed_times FROM wfs_job_stats WHERE pid=?',params=(pid,)),before)
            self.assertEqual(db.execute_query_sql('SELECT COUNT(*) FROM wfs_run_history WHERE id=?',params=(row['run_id'],))[0][0],0)
        from app.bootstrap.release_controls import trial_evidence
        self.assertTrue(trial_evidence(pid,data['version'])['passed'])

    def test_ci_trial_and_release_window_gates_are_server_enforced(self):
        data=self.ready(self.new());pid=data['pid']
        p=policy.save('release','',{**policy.load('release'),'require_trial':True},'admin')
        with self.assertRaises(packages.PackageError):self.activate(data)
        p=policy.save('release','',{**p,'require_trial':False,'require_ci':True,'required_jobs':['tests']},'admin')
        from app.bootstrap import release_controls
        with patch.object(release_controls,'evidence',return_value={'status':'success','jobs':[]}):
            with self.assertRaises(packages.PackageError):self.activate(data)
        with patch.object(release_controls,'evidence',return_value={'status':'success','jobs':[{'name':'tests','status':'success'}]}):self.activate(data)
        with patch.object(policy,'in_window',return_value=False):
            with self.assertRaises(packages.PackageError):self.activate(data)

    def test_first_release_can_trial_before_publication_and_then_pass_gate(self):
        data=self.ready(self.new({'main.py':'print("FIRST_TRIAL_OK")'}));pid=data['pid']
        self.assertFalse(packages.task(pid)['active_version'])
        response=self.client.get('/api/admin/operational/policy/task?pid='+pid)
        self.assertEqual(response.status_code,200,response.json)
        policy.save('release','',{**policy.load('release'),'require_trial':True},'admin')
        response=self.client.post('/api/admin/operational/requests?pid='+pid,headers=self.headers,
                    json={'kind':'trial','request_id':'first_candidate_trial','context':{'version':data['version']}})
        self.assertEqual(response.status_code,200,response.json)
        requests.dispatch();self.run_pending(pid)
        self.assertEqual(operations.read_run(requests.snapshot(pid)[0]['run_id'])['status'],'success')
        self.assertFalse(packages.task(pid)['active_version'])
        self.activate(data)
        self.assertEqual(packages.task(pid)['active_version'],data['version'])

    def test_policy_changes_during_ci_validation_block_activation(self):
        from app.bootstrap import release_controls
        data=self.ready(self.new())
        policy.save('release','',{**policy.load('release'),'require_ci':True},'admin')
        def changed(_):
            policy.save('release','',{**policy.load('release'),'require_trial':True},'admin')
            return {'status':'success','jobs':[]}
        with patch.object(release_controls,'evidence',side_effect=changed):
            with self.assertRaises(packages.PackageError):self.activate(data)
        self.assertFalse(packages.task(data['pid'])['active_version'])

    def test_shared_sdk_is_frozen_and_tampering_blocks_publication(self):
        data=self.ready(self.new());root=packages.release_dir(data['pid'],data['version'])
        self.assertTrue(data['shared_sdk_sha256'])
        self.assertFalse((root/'shared-sdk/app/config').exists())
        source=root/'shared-sdk/app/common/database.py';source.write_text('changed')
        with self.assertRaises(packages.PackageError):self.activate(data)

    def test_group_quota_reserves_capacity_for_other_groups(self):
        from app.bootstrap.global_vars import RunningState
        policy.save('groups','',{'revision':0,'quotas':{'reports':1}},'admin')
        state=RunningState();one=state.claim('one',3,'reports');self.assertIsNotNone(one)
        self.assertIsNone(state.claim('two',3,'reports'));self.assertIsNotNone(state.claim('three',3,'checks'))
        self.assertIn('分组',state.capacity_reason('two',3,'reports'))
        state.remove(one);self.assertIsNotNone(state.claim('two',3,'reports'))

    def test_connection_lifecycle_guards_declarations_revisions_and_platform(self):
        from app.bootstrap import connection_settings as settings,connection_lifecycle as lifecycle
        profile=settings.save(settings.validate({'id':'reports','dialect':'sqlite','database':'report.sqlite3','name':'报表库','environment':'test'}))
        data=self.ready(self.new());pid=data['pid']
        self.configure(pid,declared_connections=['reports'])
        self.assertEqual(lifecycle.usage('reports')[0]['pid'],pid)
        lifecycle.change('reports','disable',profile['revision'],'','admin')
        with self.assertRaises(PermissionError):settings.business_profile('reports')
        with self.assertRaises(ValueError):lifecycle.change('reports','delete',2,'reports','admin')
        self.configure(pid,declared_connections=[])
        lifecycle.change('reports','delete',2,'reports','admin');self.assertNotIn('reports',settings.profiles())
        with self.assertRaises(ValueError):lifecycle.change('platform','disable',1,'','admin')

    def test_task_maintainer_cannot_escape_assigned_tasks_or_become_admin(self):
        from app.bootstrap import task_access
        data=self.ready(self.new());self.activate(data);pid=data['pid']
        with GaussDB() as db:db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)',params=('owner',generate_password_hash('owner-password'),'maintainer'))
        task_access.save('owner',{'revision':0,'tasks':[pid],'groups':[],'capabilities':['run','publish']},'admin')
        client=self.app.test_client();login=client.post('/api/user/login',json={'username':'owner','password':'owner-password'})
        headers={'X-CSRF-Token':login.json['data']['csrf_token']}
        with patch('app.api.task.views.call_task_once',return_value='f'*32):
            self.assertEqual(client.post('/api/taskinfo/call_task?pid='+pid,headers=headers,json={'request_id':'assigned_request_123'}).status_code,200)
            self.assertEqual(client.post('/api/taskinfo/call_task?pid=other',headers=headers,json={}).status_code,403)
        self.assertEqual(client.get('/api/taskinfo/source?pid='+pid).status_code,403)
        self.assertEqual(client.get('/api/taskinfo/packages?pid='+pid).status_code,200)
        self.assertEqual(client.get('/api/taskinfo/packages').status_code,403)
        self.assertEqual(client.get('/api/admin/operational/policy/release').status_code,403)
        self.assertEqual(client.post('/api/admin/task-access?username=owner',headers=headers,json={}).status_code,403)

    def test_notification_resolution_is_audited_without_resending(self):
        from app.bootstrap.timebase import business_now
        with GaussDB() as db:db.execute_sql("INSERT INTO wfs_notifications(id,pid,channel,status,attempts,created_at,due_at,payload,message,kind,incident) VALUES(?,?,?,'unknown',1,?,?,?,'','failure','incident')",params=('notification-id','task','email',business_now(),business_now(),'{}'))
        result=self.client.post('/api/admin/operational/notifications',headers=self.headers,json={'id':'notification-id','outcome':'confirmed_sent','note':'已核对网关记录'})
        self.assertEqual(result.status_code,200,result.json)
        with GaussDB() as db:self.assertEqual(db.execute_query_sql('SELECT status,attempts FROM wfs_notifications WHERE id=?',params=('notification-id',))[0],('resolved_sent',1))
        self.assertEqual(admission.policy('notification:notification-id',{})['actor'],'admin')
        self.assertEqual(admission.policy('notification:notification-id',{})['transport_status'],'unknown')

    def test_webhook_requires_token_project_and_deduplicates_without_cookie(self):
        from app.bootstrap import gitlab_webhook,gitlab_updates
        body={'project':{'id':1,'path_with_namespace':'team/project'}}
        config={'enabled':True,'project':'team/project'}
        token='a'*40
        with patch.dict(os.environ,{'WFS_GITLAB_WEBHOOK_TOKEN':token}),patch.object(gitlab_updates,'configuration',return_value=config):
            with self.assertRaises(PermissionError):gitlab_webhook.receive('wrong','Push Hook','event-12345678',body)
            self.assertTrue(gitlab_webhook.receive(token,'Push Hook','event-12345678',body))
            self.assertFalse(gitlab_webhook.receive(token,'Push Hook','event-12345678',body))
            with self.assertRaises(ValueError):gitlab_webhook.receive(token,'Push Hook','event-23456789',{'project':{'id':2}})
            response=self.app.test_client().post('/api/integrations/gitlab/webhook',headers={'X-Gitlab-Token':token,'X-Gitlab-Event':'Push Hook','X-Gitlab-Event-UUID':'event-34567890'},json=body)
            self.assertEqual(response.status_code,202,response.json)
        with patch.object(gitlab_updates,'request_scan',return_value=False):self.assertFalse(gitlab_webhook.request_pending())
        self.assertTrue(admission.policy('gitlab-hook-pending',{}))
        with patch.object(gitlab_updates,'request_scan',return_value=True):self.assertTrue(gitlab_webhook.request_pending())
        self.assertFalse(admission.policy('gitlab-hook-pending',{}))

    def test_pending_trial_version_is_protected_even_outside_recent_versions(self):
        from app.bootstrap.version_storage import snapshot
        pid='pending-task';version='a'*32
        requests.enqueue(pid,'trial',{'version':version},'admin')
        fake=[(json.dumps({'pid':pid,'version':f'{n:032x}','status':'ready'}),) for n in range(20)]
        fake.append((json.dumps({'pid':pid,'version':version,'status':'ready'}),))
        with patch('app.bootstrap.version_storage.registry',return_value={}):
            with patch.object(GaussDB,'execute_query_sql',side_effect=[fake,[]]):
                with patch('app.bootstrap.version_storage.release_dir',return_value=self.root):result=snapshot()
        target=next(v for v in result['versions'] if v['version']==version)
        self.assertFalse(target['candidate']);self.assertIn('执行记录引用',target['protected'])

    def test_cleanup_refuses_unflushed_execution_journal(self):
        from app.bootstrap import journal,version_cleanup
        admission.set_maintenance(True,0,'cleanup','admin')
        journal.write(self.root/'data/executions',{'run_id':'a'*32,'pid':'task','status':'failed','created_at':'2026-01-01','db_synced':False},operations.TERMINAL)
        with self.assertRaisesRegex(RuntimeError,'补写'):version_cleanup.execute({},'admin')

    def test_cleanup_requires_maintenance_complete_plan_and_preserves_protected_versions(self):
        from app.bootstrap import version_cleanup
        with self.assertRaises(RuntimeError):version_cleanup.execute({},'admin')
        admission.set_maintenance(True,0,'cleanup','admin')
        data=self.ready(self.new());root=packages.release_dir(data['pid'],data['version'])
        candidate={'pid':data['pid'],'version':data['version'],'bytes':10}
        sample={'keep':20,'candidates':[candidate],'fingerprint':'fixed','truncated':False,'bytes':10,'confirm':'清理 1 个未引用版本'}
        with patch.object(version_cleanup,'plan',return_value=sample):
            with self.assertRaises(RuntimeError):version_cleanup.execute({'fingerprint':'old','confirm':sample['confirm']},'admin')
            value=version_cleanup.execute({'fingerprint':'fixed','confirm':sample['confirm']},'admin')
        self.assertEqual(len(value['cleaned']),1);self.assertFalse(root.exists())
        self.assertEqual(packages.release(data['pid'],data['version'])['status'],'cleaned')

if __name__=='__main__':unittest.main()
