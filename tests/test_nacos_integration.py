"""Nacos admin routes and resolved task/platform snapshots against local HTTP."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_local_integration as shared
from nacos_fixture import NacosFixture
from app import create_app
from app.bootstrap import connection_settings as business, platform_config, nacos_config
from app.bootstrap.database import GaussDB
from app.common.nacos import Nacos
from app.settings import AUTH_ADMIN_PASSWORD_HASH


class NacosIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        env = patch.dict(os.environ, {'WFS_NACOS_CONFIG_FILE': str(root/'nacos.enc'),
            'WFS_PLATFORM_CONFIG_FILE': str(root/'platform.enc')})
        env.start(); self.addCleanup(env.stop)
        self.remote = self.enterContext(NacosFixture())
        nacos_config.save(nacos_config.validate({**nacos_config.defaults(), **self.remote.config}))
        Nacos.clear_cache(); self.addCleanup(Nacos.clear_cache)
        platform_config._after_fork(); self.addCleanup(platform_config._after_fork)
        self.binding = dict(namespace='production', group='databases', data_id='orders.json', password_encoding='plain')
        self.document = dict(host='db.internal', port=5432, db='orders', user='reader', password='remote-private', extra={'keep': 42})
        self.md5 = self.remote.put(self.binding, self.document)
        self.app = create_app(); self.app.testing = True
        self.client, self.headers = self.login()

    def login(self, username='admin'):
        client = self.app.test_client()
        login = client.post('/api/user/login', json=dict(username=username,password='test-password'))
        self.assertEqual(login.status_code, 200, login.json)
        return client, {'X-CSRF-Token':login.json['data']['csrf_token']}

    def form(self, **updates):
        return {**dict(id='orders', dialect='postgresql', source='nacos', revision=0,
            host=self.document['host'], port=5432, database='orders', user='reader',
            password='', nacos=self.binding, nacos_md5=self.md5, tls='disabled',
            nacos_settings_token=nacos_config.version_token()), **updates}

    def post(self, path, form):
        return self.client.post('/api/admin/'+path, json=form, headers=self.headers)

    def test_settings_preview_csrf_and_redaction(self):
        listing = self.client.get('/api/admin/nacos')
        self.assertTrue(listing.json['data']['can_edit'])
        self.assertNotIn(self.remote.password, listing.get_data(as_text=True))
        denied = self.client.post('/api/admin/nacos/preview', json={'binding':self.binding})
        self.assertEqual(denied.status_code,403)
        before = self.remote.calls['publish']
        result = self.post('nacos/preview', {'binding':self.binding})
        self.assertEqual(result.status_code,200,result.json)
        data=result.json['data']
        self.assertEqual(data['md5'], self.md5)
        self.assertTrue(data['profile']['password_set'])
        self.assertNotIn('password',data['profile']);self.assertNotIn('extra',data['profile'])
        self.assertNotIn('remote-private',result.get_data(as_text=True))
        self.assertEqual(self.remote.calls['publish'],before)

    def test_business_save_retains_remote_password_preserves_unknown_and_refreshes_next_task(self):
        from app.bootstrap.admission import connection_environment
        with patch.object(business,'probe_business',return_value={'ready':True}) as probe:
            result=self.post('database-connections/save',self.form(host='updated.internal'))
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(probe.call_args.args[0]['password'],'remote-private')
        self.assertTrue(result.json['data']['nacos_synced'])
        self.assertEqual(json.loads(next(iter(self.remote.documents.values())))['extra'],{'keep':42})
        self.assertNotIn('remote-private',result.get_data(as_text=True))
        with patch('app.bootstrap.admission.grant',return_value={'connections':['orders']}):
            first=json.loads(connection_environment('task'))
            self.remote.put(self.binding,{**self.document,'password':'rotated-private'})
            second=json.loads(connection_environment('task'))
        self.assertEqual(first['orders']['password'],'remote-private')
        self.assertEqual(second['orders']['password'],'rotated-private')
        with patch.dict(os.environ,{'WFS_TASK_CONNECTIONS_JSON':json.dumps(first)}),patch('app.bootstrap.nacos_bindings.read') as read:
            self.assertEqual(business.business_profile('orders')['password'],'remote-private')
            read.assert_not_called()
        self.remote.get_status=500
        with self.assertRaises(RuntimeError):business.business_profile('orders')

    def test_stale_preview_and_failed_probe_never_publish(self):
        self.remote.put(self.binding,{**self.document,'password':'externally-edited'})
        with patch.object(business,'probe_business') as probe:
            response=self.post('database-connections/save',self.form())
        self.assertEqual(response.status_code,409,response.json);probe.assert_not_called()
        self.assertEqual(self.remote.calls['publish'],0)
        self.md5=self.remote.put(self.binding,self.document)
        with patch.object(business,'probe_business',side_effect=ValueError('测试未通过')):
            response=self.post('database-connections/save',self.form())
        self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.remote.calls['publish'],0)

    def test_readonly_test_and_partial_save_failure_are_explicit(self):
        with patch.object(business,'probe_business',return_value={'ready':True}):
            response=self.post('database-connections/test',self.form())
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(self.remote.calls['publish'],0)
            with patch.object(business,'save',side_effect=OSError('private-error')):
                response=self.post('database-connections/save',self.form(host='confirmed.internal'))
        self.assertEqual(response.status_code,503,response.json)
        self.assertIn('Nacos 已更新',response.json['message'])
        self.assertNotIn('private-error',response.get_data(as_text=True))
        self.assertEqual(self.remote.calls['publish'],1)
        self.assertEqual(business.profiles(),{})

    def test_other_admin_cannot_read_remote_or_modify_existing_nacos_as_direct(self):
        with patch.object(business,'probe_business',return_value={'ready':True}):
            response=self.post('database-connections/save',self.form())
        self.assertEqual(response.status_code,200,response.json)
        with GaussDB() as db:
            db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)',params=('other-admin',AUTH_ADMIN_PASSWORD_HASH,'admin'))
        client,headers=self.login('other-admin')
        self.assertFalse(client.get('/api/admin/nacos').json['data']['can_edit'])
        before=dict(self.remote.calls)
        for route,form in [('nacos/preview',{'binding':self.binding}),('nacos/test',{}),('nacos/save',{}),
                           ('database-connections/save',self.form(source='direct',revision=1,password='spoof')),
                           ('platform-database/save',{})]:
            response=client.post('/api/admin/'+route,json=form,headers=headers)
            self.assertEqual(response.status_code,403,response.json)
        self.assertEqual(self.remote.calls,before)

    def test_platform_pending_nacos_and_replacement_workers_pin_actual_credentials(self):
        from app.api import platform_database as api
        form={**platform_config.saved(), **self.form(), 'schema':'wfs', 'driver':'DWS'}
        with patch.object(api,'probe',return_value={'ready':True}):
            result=self.post('platform-database/save',form)
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(result.json['data']['restart_required'])
        self.assertNotIn('remote-private',json.dumps(platform_config.snapshot()))
        environment={**os.environ,'WFS_POSTGRES_TEST':'false','WFS_ENV':'production'}
        with platform_config.frozen_service_config(self.directory.name,environment) as frozen:
            snapshot=platform_config.saved(frozen)
            self.assertEqual(snapshot['_nacos_resolved']['password'],'remote-private')
            self.remote.put(self.binding,{**self.document,'password':'next-start-password'})
            before=self.remote.calls['get']
            with patch.dict(os.environ,{'WFS_POSTGRES_TEST':'false','WFS_PLATFORM_ACTIVE_CONFIG_FILE':frozen}):
                for _ in range(2):
                    platform_config._after_fork()
                    active=platform_config.active()
                    self.assertEqual(active['_nacos_resolved']['password'],'remote-private')
                    self.assertNotIn('_nacos_resolved',platform_config.public(active))
            self.assertEqual(self.remote.calls['get'],before)
        with platform_config.frozen_service_config(self.directory.name,environment) as frozen:
            self.assertEqual(platform_config.saved(frozen)['_nacos_resolved']['password'],'next-start-password')

    def test_legacy_service_nacos_base64_also_freezes_at_start(self):
        legacy={'namespace':'','group':'gauss','data_id':'gauss.wfsscheduler.wfs.json'}
        self.remote.put(legacy,{**self.document,'password':base64.b64encode(b'legacy-password').decode()})
        environment={**os.environ,'WFS_POSTGRES_TEST':'false','WFS_ENV':'production','WFS_DB_ID':'wfsscheduler_wfs'}
        value=platform_config.resolve_startup(platform_config.defaults(environment),environment)
        self.assertEqual(value['_nacos_resolved']['password'],'legacy-password')
        self.assertEqual(value['_nacos_resolved']['schema'],'wfs')
        self.assertNotIn('_nacos_resolved',platform_config.public(value))

    def test_nacos_resolved_newdb_connects_to_real_isolated_postgres(self):
        from app.common.database import NewDB
        from app.bootstrap.database import _split_db_id, DEFAULT_DB_ID
        reader=object.__new__(GaussDB);reader.current_env='development'
        name,schema=_split_db_id(os.environ.get('WFS_DB_ID',DEFAULT_DB_ID))
        config=reader._GaussDB__get_db_config(name,schema)
        document={key:config[key] for key in ('host','port','db','user','password')}
        self.md5=self.remote.put(self.binding,document)
        form=self.form(host=config['host'],port=int(config['port']),database=config['db'],user=config['user'])
        response=self.post('database-connections/save',form)
        self.assertEqual(response.status_code,200,response.json)
        from app.bootstrap.admission import connection_environment
        with patch('app.bootstrap.admission.grant',return_value={'connections':['orders']}):
            payload=connection_environment('task')
        with patch.dict(os.environ,{'WFS_TASK_CONNECTIONS_JSON':payload}):
            with NewDB('orders') as db:
                self.assertEqual(db.query('SELECT ? + ?', (2,3)),[(5,)])

    def test_empty_remote_secret_never_falls_back_to_saved_password(self):
        with patch.object(business,'probe_business',return_value={'ready':True}):
            response=self.post('database-connections/save',self.form())
        self.assertEqual(response.status_code,200,response.json)
        changed=self.remote.put(self.binding,{**self.document,'password':''})
        with self.assertRaisesRegex(ValueError,'密码不能为空'):
            business.business_profile('orders')
        response=self.post('database-connections/save',self.form(revision=1,nacos_md5=changed))
        self.assertEqual(response.status_code,400,response.json)
        staged={**platform_config.defaults(), **self.form(nacos_md5=changed),
                'schema':'wfs','password':'old-local-password'}
        environment={**os.environ,'WFS_POSTGRES_TEST':'false'}
        with self.assertRaisesRegex(ValueError,'密码不能为空'):
            platform_config.resolve_startup(staged,environment)
        from app.bootstrap.nacos_bindings import read
        with self.assertRaisesRegex(ValueError,'密码不能为空'):
            read({**self.binding,'password_encoding':'base64'},force_refresh=True)

    def test_global_nacos_change_before_save_rejects_even_identical_remote_document(self):
        form=self.form()
        with NacosFixture() as other:
            other.put(self.binding,self.document)
            nacos_config.save(nacos_config.validate({**nacos_config.saved(), **other.config}))
            with patch.object(business,'probe_business') as probe:
                result=self.post('database-connections/save',form)
            self.assertEqual(result.status_code,409,result.json);probe.assert_not_called()
            self.assertEqual(other.calls['publish'],0)
            self.assertEqual(self.remote.calls['publish'],0)

    def test_global_nacos_change_during_probe_never_sends_secret_to_new_endpoint(self):
        form=self.form(host='pending-edit.internal')
        with NacosFixture() as other:
            other.put(self.binding,self.document)
            def probe(_):
                nacos_config.save(nacos_config.validate({**nacos_config.saved(), **other.config}))
                return {'ready':True}
            with patch.object(business,'probe_business',side_effect=probe):
                result=self.post('database-connections/save',form)
            self.assertEqual(result.status_code,409,result.json)
            self.assertEqual(other.calls,{'login':0,'get':0,'publish':0})
            self.assertEqual(self.remote.calls['publish'],0)
