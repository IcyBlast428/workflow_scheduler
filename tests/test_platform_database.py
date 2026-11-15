"""Platform pool limits, staged bootstrap configuration and admin boundaries."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_local_integration
from app.bootstrap import platform_config as config, platform_pool as pools
from app.bootstrap.database import GaussDB


class FakeCursor:
    def __init__(self, connection):
        self.connection=connection
    def execute(self, sql, params=None):
        self.connection.statements.append(sql)
        if self.connection.broken:
            raise OSError('disconnected')
        return self
    def close(self): pass


class FakeConnection:
    def __init__(self):
        self.autocommit=True;self.closed=False;self.broken=False
        self.rollbacks=0;self.statements=[]
    def cursor(self):return FakeCursor(self)
    def rollback(self):
        self.rollbacks+=1
        if self.broken:raise OSError('disconnected')
    def close(self):self.closed=True


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        environment=patch.dict(os.environ,{'WFS_DATA_DIR':self.temp.name,'WFS_ENABLE_SCHEDULER':'false'})
        environment.start();self.addCleanup(environment.stop)
        pools.dispose();self.addCleanup(pools.dispose)
        self.settings={**config.defaults(),'web_pool_size':1,'web_max_overflow':0,'pool_timeout':.05}
        self.created=[]
    def create(self):
        connection=FakeConnection();self.created.append(connection);return connection
    def borrow(self):return pools.acquire(['fake','secret-identity'],self.create,self.settings)

    def test_reuses_connection_rolls_back_and_respects_hard_limit(self):
        one=self.borrow();one.raw.autocommit=False
        with self.assertRaisesRegex(RuntimeError,'连接池已满'):self.borrow()
        self.assertEqual(len(self.created),1)
        raw=one.raw;one.close()
        self.assertGreaterEqual(raw.rollbacks,1)
        two=self.borrow()
        self.assertIs(two.raw,raw);self.assertTrue(raw.autocommit)
        two.close();two.close()
        stats=pools._payload()['pools'][0]
        self.assertEqual(stats['timeouts'],1);self.assertEqual(stats['limit'],1)
        self.assertEqual(stats['in_use'],0);self.assertEqual(stats['waiting'],0)

    def test_waiter_gets_returned_connection_and_overflow_is_bounded(self):
        self.settings.update(pool_timeout=1,web_max_overflow=1)
        first=self.borrow();second=self.borrow()
        started=threading.Event()
        def waiting():
            started.set();return self.borrow()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(waiting);self.assertTrue(started.wait(1))
            time.sleep(.03);self.assertFalse(future.done())
            raw=first.raw;first.close();third=future.result(timeout=2)
            self.assertIs(third.raw,raw)
            third.close();second.close()
        self.assertEqual(len(self.created),2)
        self.assertEqual(pools._payload()['pools'][0]['in_use'],0)

    def test_broken_idle_connection_is_replaced_before_user_work(self):
        first=self.borrow();old=first.raw;first.close();old.broken=True
        second=self.borrow()
        self.assertIsNot(second.raw,old);self.assertTrue(old.closed)
        self.assertEqual(pools._payload()['pools'][0]['reconnects'],1)
        second.close()

    def test_checkout_failure_releases_capacity_and_does_not_loop_forever(self):
        def broken():
            raw=self.create();raw.broken=True;return raw
        with self.assertRaises(OSError):pools.acquire(['broken'],broken,self.settings)
        self.assertEqual(len(self.created),2)
        stats=pools._payload()['pools'][0]
        self.assertEqual(stats['in_use'],0);self.assertEqual(stats['waiting'],0)
        self.assertTrue(all(raw.closed for raw in self.created))

    def test_concurrent_flushes_are_atomic_and_clean_old_snapshots(self):
        lease=self.borrow();lease.close()
        directory=pools._directory()
        old=directory/'123-aaaaaaaaaaaa.json';old.write_text('{}')
        os.utime(old,(time.time()-180,time.time()-180))
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(lambda _:pools._flush(force=True),range(40)))
        files=list(directory.glob('*.json'))
        self.assertEqual(len(files),1);self.assertFalse(old.exists())
        payload=json.loads(files[0].read_text());self.assertEqual(payload['pid'],os.getpid())
        self.assertNotIn('secret-identity',files[0].read_text())
        self.assertEqual(list(directory.glob('*.tmp')),[])

    def test_diagnostics_rejects_bad_snapshots_and_strips_unexpected_fields(self):
        lease=self.borrow();lease.close()
        value=pools._payload();value.update(pid=os.getpid()+100000,password='never-return')
        value['pools'][0]['password']='never-return'
        directory=pools._directory()
        (directory/'98765-aaaaaaaaaaaa.json').write_text(json.dumps(value))
        (directory/'98766-bbbbbbbbbbbb.json').write_text(json.dumps({**value,'at':float('nan')}))
        with patch('app.bootstrap.runtime_metrics.snapshot',return_value={}):
            result=pools.diagnostics()
        self.assertEqual(len(result['processes']),2)
        self.assertNotIn('never-return',json.dumps(result))


class PlatformConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'platform-connection.enc'
        self.environment=patch.dict(os.environ,{'WFS_PLATFORM_CONFIG_FILE':str(self.path),'WFS_DATA_DIR':self.temp.name,
            'WFS_SECRET_KEY':'platform-config-test-key','WFS_CONNECTIONS_KEY':'platform-connections-test-key',
            'WFS_DB_DRIVER':'DWS','WFS_DB_ID':'platform_wfs','WFS_POSTGRES_TEST':'false'})
        self.environment.start();self.addCleanup(self.environment.stop)
        config._after_fork();self.addCleanup(config._after_fork)
    def form(self,**values):
        return config.validate({**config.saved(),**values})

    def test_save_is_encrypted_redacted_and_requires_compare_and_swap(self):
        first=config.active()
        form=self.form(source='direct',host='127.0.0.1',database='platform',user='operator',password='never-show-password')
        saved=config.save(form)
        self.assertNotIn('password',saved);self.assertTrue(saved['password_set'])
        self.assertNotIn(b'never-show-password',self.path.read_bytes())
        self.assertEqual(config.active(),first)
        self.assertTrue(config.snapshot()['restart_required'])
        with self.assertRaises(RuntimeError):config.save(form)
        if os.name!='nt':self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_saved_query_timeout_overrides_bootstrap_environment(self):
        with patch.dict(os.environ,{'WFS_DB_QUERY_TIMEOUT_SECONDS':'10'}):
            config.save(self.form(query_timeout=27))
            config._after_fork()
            self.assertEqual(config.active()['query_timeout'],27)
            fake=FakeConnection()
            with patch('app.bootstrap.database.pyodbc.connect',return_value=fake),patch.object(GaussDB,'_GaussDB__get_db_config',return_value=dict(host='localhost',port=8000,db='platform',schema='wfs',user='u',password='p')):
                with GaussDB(pooled=False):pass
            self.assertIn('SET statement_timeout = 27000',fake.statements)

    def test_service_snapshot_pins_replacement_workers_until_complete_restart(self):
        environment=dict(os.environ)
        with config.frozen_service_config(self.temp.name,environment) as frozen:
            config.save(self.form(query_timeout=27))
            script='from app.bootstrap.platform_config import active; print(active()["revision"])'
            child={**environment,'WFS_PLATFORM_ACTIVE_CONFIG_FILE':frozen}
            for _ in range(2):
                result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=child,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'0')
            self.assertTrue(Path(frozen).is_file())
        self.assertFalse(Path(frozen).exists())
        with config.frozen_service_config(self.temp.name,environment) as restarted:
            with patch.dict(os.environ,{'WFS_PLATFORM_ACTIVE_CONFIG_FILE':restarted}):
                config._after_fork();self.assertEqual(config.active()['revision'],1)

    def test_failed_startup_snapshot_leaves_staged_configuration_untouched(self):
        config.save(self.form(query_timeout=12));before=self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'startup'):
            with config.frozen_service_config(self.temp.name,dict(os.environ)) as frozen:
                raise RuntimeError('startup failed')
        self.assertFalse(Path(frozen).exists());self.assertEqual(self.path.read_bytes(),before)

    def test_invalid_config_or_key_never_silently_falls_back(self):
        config.save(self.form())
        with patch.dict(os.environ,{'WFS_CONNECTIONS_KEY':'wrong-key'}),self.assertRaises(ValueError):config.saved()
        for change in ({'host':'server;UID=other','source':'direct'}, {'web_pool_size':0}, {'pool_timeout':True}, {'schema':'wfs;drop','source':'direct'}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.form(**change)


class PlatformDatabaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'WFS_PLATFORM_CONFIG_FILE':str(Path(self.temp.name)/'platform.enc'),'WFS_DATA_DIR':self.temp.name})
        env.start();self.addCleanup(env.stop)
        pools.dispose();self.addCleanup(pools.dispose)
        config._after_fork();self.addCleanup(config._after_fork)

    def test_real_connection_reuse_rolls_back_uncommitted_transaction(self):
        with GaussDB() as first:
            pid=first.execute_query_sql('SELECT pg_backend_pid()')[0][0]
            first.begin_transaction()
            first.execute_sql("INSERT INTO wfs_state_admission_settings(key,payload) VALUES('pool-rollback','{}')")
        with GaussDB() as second:
            self.assertEqual(second.execute_query_sql('SELECT pg_backend_pid()')[0][0],pid)
            self.assertFalse(second.execute_query_sql("SELECT 1 FROM wfs_state_admission_settings WHERE key='pool-rollback'"))

    def test_single_connection_pool_supports_parallel_admission_without_nested_borrow(self):
        from app.bootstrap import admission, execution_requests
        from types import SimpleNamespace
        from app.bootstrap.timebase import business_now
        settings={**config.defaults(),'web_pool_size':1,'web_max_overflow':0,'pool_timeout':2}
        with patch.object(config,'active',return_value=settings):
            def enqueue(n):
                admission.clear_policy_cache()
                job=SimpleNamespace(args=['/missing',str(n),'task'],kwargs={},misfire_grace_time=600)
                return execution_requests.enqueue_scheduled(job,business_now())
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                self.assertEqual(len(list(executor.map(enqueue,range(16)))),16)
            admission.clear_policy_cache()
            for n in range(5):
                result=admission.manual_request('admin','task','test-pool-request-'+str(n),lambda:'run')
                self.assertEqual(result['run_id'],'run')
        self.assertTrue(all(p['timeouts']==0 for p in pools._payload()['pools']))

    def test_probe_only_reads_schema_and_masks_driver_secrets(self):
        from app.api.platform_database import probe
        from unittest.mock import MagicMock
        db=MagicMock()
        db.execute_query_sql.side_effect=lambda sql:[(1,)] if 'wfs_schema_version' in sql else []
        with patch('app.bootstrap.database.GaussDB') as factory:
            factory.return_value.__enter__.return_value=db
            self.assertTrue(probe(config.defaults())['ready'])
            self.assertFalse(factory.call_args.kwargs['pooled'])
        db.execute_sql.assert_not_called()
        self.assertTrue(all(call.args[0].startswith('SELECT') for call in db.execute_query_sql.call_args_list))
        with patch('app.bootstrap.database.GaussDB',side_effect=RuntimeError('PWD=private-secret')):
            with self.assertRaises(ValueError) as caught:probe(config.defaults())
        self.assertNotIn('private-secret',str(caught.exception))

    def test_admin_route_checks_auth_csrf_and_redacts_staged_secret(self):
        from app import create_app
        from app.api import platform_database as api
        from app.bootstrap.permissions import allowed
        app=create_app();client=app.test_client()
        path='/api/admin/platform-database'
        self.assertEqual(client.get(path).status_code,401)
        for role in ('viewer','operator','maintainer'):
            self.assertFalse(allowed(path,'GET',role))
        login=client.post('/api/user/login',json={'username':'admin','password':'test-password'})
        csrf={'X-CSRF-Token':login.json['data']['csrf_token']}
        form={**config.saved(),'source':'direct','host':'127.0.0.1','database':'platform','user':'operator','password':'secret-in-form','driver':'DWS'}
        self.assertEqual(client.post(path+'/save',json=form).status_code,403)
        with patch.object(api,'probe',return_value={'ready':True}),patch('app.bootstrap.operations.audit'):
            response=client.post(path+'/save',json=form,headers=csrf)
            self.assertEqual(response.status_code,200,response.json)
            self.assertNotIn('secret-in-form',response.get_data(as_text=True))
            self.assertEqual(client.post(path+'/save',json=form,headers=csrf).status_code,409)
        result=client.get(path)
        self.assertEqual(result.status_code,200,result.json)
        self.assertNotIn('secret-in-form',result.get_data(as_text=True))
        self.assertTrue(result.json['data']['restart_required'])


if __name__=='__main__':unittest.main()
