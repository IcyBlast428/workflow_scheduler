"""Exercise production state SQL through a transactional DB-API emulator.

These tests do not claim to validate a real GaussDB/DWS driver or deployment.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

import test_local_integration
from app.bootstrap import auxiliary_store as state, admission, task_publishing, gitlab_updates, connection_settings, journal
from app.bootstrap import database


class Cursor:
    def __init__(self, cursor): self.cursor=cursor
    def execute(self, sql, params=()):
        if sql.startswith('LOCK TABLE '): return self
        self.cursor.execute(sql,params);return self
    def __getattr__(self,name): return getattr(self.cursor,name)


class Connection:
    def __init__(self, connection): self.connection=connection
    def cursor(self): return Cursor(self.connection.cursor())
    def __getattr__(self,name): return getattr(self.connection,name)


class GaussStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.sql_path=self.root/'db-api-emulator.db'
        connect=sqlite3.connect
        with closing(connect(self.sql_path)) as db:
            db.executescript((Path(__file__).resolve().parents[1]/'migrations/008_gauss_state.sql').read_text())
            db.commit()
        self.original=database.GaussDB
        owner=self
        class Gauss:
            dialect='GaussDB/DWS'
            def __init__(self):
                self.raw=connect(owner.sql_path, timeout=10)
                self.conn=Connection(self.raw);self.cursor=self.conn.cursor()
            def begin_transaction(self): self.raw.execute('BEGIN')
            def __enter__(self): return self
            def __exit__(self,*args): self.raw.close()
        def factory(*args,**kwargs):
            if kwargs.get('managed') is False: return Gauss()
            return self.original(*args,**kwargs)
        for patcher in [patch.dict(os.environ,{'WFS_STATE_BACKEND':'gauss','WFS_DATA_DIR':str(self.root/'data')}),
                        patch.object(database,'GaussDB',side_effect=factory),
                        patch.object(sqlite3,'connect',side_effect=AssertionError('Production code opened SQLite'))]:
            patcher.start();self.addCleanup(patcher.stop)

    def test_configuration_ciphertext_and_namespaces(self):
        repository=task_publishing.repository()
        saved=task_publishing.save_repository(dict(repository,mode='nexus',username='reader',password='private-password'))
        self.assertEqual(task_publishing.repository()['password'],'private-password')
        with task_publishing.store() as db:
            self.assertNotIn(b'private-password',db.execute("SELECT payload FROM settings WHERE name='repository'").fetchone()[0])
        self.assertFalse(admission.maintenance()['enabled'])
        admission.set_maintenance(True,0,'maintenance','admin')
        self.assertTrue(admission.maintenance()['enabled'])
        self.assertEqual(task_publishing.repository()['revision'], saved['revision'])
        self.assertFalse(connection_settings.profiles())
        self.assertIsNone(connection_settings.active_platform())
        self.assertFalse(gitlab_updates.configuration()['enabled'])
        from scripts.backup_receipt import record
        archive=self.root/'backup.zip';archive.write_bytes(b'backup-evidence')
        record(self.root/'data',archive)
        self.assertEqual(admission.policy('backup:last',{})['bytes'],15)
        with gitlab_updates.store() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)',('one',))
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)',('two',))
            self.assertEqual(db.execute('SELECT payload FROM snapshot WHERE id=1').fetchone()[0],'two')
        self.assertFalse(list(self.root.rglob('*.sqlite3')))

    def test_rollback_and_request_deduplication(self):
        with self.assertRaises(RuntimeError), admission.store() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('rolled-back','{}'))
            raise RuntimeError('abort')
        self.assertIsNone(admission.policy('rolled-back',None))
        called=[]
        def submit(): called.append(True);return uuid.uuid4().hex
        key=uuid.uuid4().hex
        first=admission.manual_request('admin','task',key,submit)
        second=admission.manual_request('admin','task',key,submit)
        self.assertEqual(first['run_id'],second['run_id'])
        self.assertEqual(len(called),1)
        from app.bootstrap.execution_requests import table
        with admission.store() as db:
            table(db)
            self.assertIn('expires_at',[row[1] for row in db.execute('PRAGMA table_info(work_requests)')])

    def test_tags_ddl_and_execution_queue_use_gauss_tables(self):
        from app.bootstrap import task_schema, execution_requests
        task_schema._put('tags:task',0,{'tags':['测试']},'admin')
        self.assertEqual(task_schema.tags_all()['task']['tags'],['测试'])
        task_schema._put('ddl:task',0,{'content':'CREATE TABLE demo(id int);'},'admin')
        with admission.store() as db:
            self.assertEqual(db.execute('SELECT revision FROM ddl_history WHERE pid=?',('task',)).fetchone()[0],1)
        identifier=execution_requests.enqueue('task','manual',{},'admin')
        with admission.store() as db:
            self.assertEqual(db.execute('SELECT status FROM work_requests WHERE id=?',(identifier,)).fetchone()[0],'pending')
        self.assertFalse(list(self.root.rglob('*.sqlite3')))

    def test_journal_upsert_failure_spool_and_recovery(self):
        directory=self.root/'data/executions'
        record=dict(run_id=uuid.uuid4().hex,pid='task',status='running',created_at='2030-01-01 00:00:00',db_synced=False)
        journal.write(directory,record,{'success'})
        self.assertFalse((directory/(record['run_id']+'.json')).exists())
        record['status']='success';record['history_saved']=True;record['db_synced']=True
        with patch.object(state,'gauss_store',side_effect=RuntimeError('Database unavailable')):
            journal.write(directory,record,{'success'})
            self.assertEqual(journal.read(directory,record['run_id'])['status'],'success')
            self.assertEqual(len(journal.pending(directory,10)),1)
            self.assertGreaterEqual(journal.health(directory)['pending_writes'],1)
        self.assertTrue((directory/(record['run_id']+'.json')).exists())
        journal.import_legacy(directory,{'success'},100)
        self.assertFalse((directory/(record['run_id']+'.json')).exists())
        self.assertEqual(journal.read(directory,record['run_id'])['status'],'success')
        self.assertEqual(len(journal.recent(directory,'task')),1)
        self.assertEqual(journal.active(directory),[])
        self.assertFalse(list(self.root.rglob('*.sqlite3')))

    def test_transient_reader_does_not_fail_recovery_update(self):
        from app.bootstrap.recovery_files import open_shared_read
        import threading
        directory=self.root/'data/executions'
        record=dict(run_id=uuid.uuid4().hex,pid='task',status='running',created_at='2030-01-01',db_synced=False)
        journal._spool(directory,record)
        reader=open_shared_read(directory/(record['run_id']+'.json'))
        self.assertEqual(json.load(reader)['status'],'running')
        release=threading.Timer(.1,reader.close);release.start()
        try:
            record['status']='success'
            journal.write(directory,record,{'success'})
        finally:
            release.join();reader.close()
        self.assertFalse((directory/(record['run_id']+'.json')).exists())
        self.assertEqual(journal.read(directory,record['run_id'])['status'],'success')
