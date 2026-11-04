"""Real local PostgreSQL state checks and two safe, disabled-schedule demos."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.local_postgres import environment


def main():
    environment()
    from app import create_app
    app=create_app()
    from app.bootstrap import admission, connection_settings, task_publishing, journal
    from app.bootstrap.database import GaussDB
    from app.common.database import NewDB
    with GaussDB() as db:
        assert db.execute_query_sql("SELECT '?' AS literal, '100%' AS percent, ? AS bound",params=('中文%?',))[0]==('?', '100%', '中文%?')
    key='pg-acceptance:'+uuid.uuid4().hex
    with admission.store() as db: db.execute('INSERT INTO settings VALUES(?,?)',(key,'0'))
    def increment(_):
        with admission.store() as db:
            db.execute('BEGIN IMMEDIATE')
            value=int(db.execute('SELECT payload FROM settings WHERE key=?',(key,)).fetchone()[0])
            time.sleep(.1)
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,str(value+1)))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor: list(executor.map(increment,range(2)))
        assert admission.policy(key,None)==2
        try:
            with admission.store() as db:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,'99'))
                raise RuntimeError('rollback probe')
        except RuntimeError: pass
        assert admission.policy(key,None)==2
    finally:
        with admission.store() as db: db.execute('DELETE FROM settings WHERE key=?',(key,))
    print('REAL_POSTGRES_LOCK_AND_ROLLBACK_OK',flush=True)
    import os
    previous=connection_settings.profiles().get('pg_local',{})
    profile=connection_settings.validate(dict(id='pg_local',dialect='postgresql',host='127.0.0.1',port=15432,
        database='wfstest',user='wfstest',password=os.environ['WFS_DB_PASSWORD'],tls='disabled',revision=previous.get('revision',0)))
    connection_settings.save(profile)
    assert connection_settings.business_profile('pg_local')['password']==os.environ['WFS_DB_PASSWORD']
    with NewDB('pg_local') as db:
        assert db.query('SELECT 42')[0][0]==42
    print('ENCRYPTED_CONNECTION_AND_NEWDB_OK',flush=True)
    # Persist Nexus settings without contacting the private repository.
    repository=task_publishing.repository()
    task_publishing.save_repository(dict(repository,mode='offline',revision=repository['revision']))
    assert task_publishing.repository()['mode']=='offline'
    print('PUBLISHING_SETTINGS_OK',flush=True)
    run=uuid.uuid4().hex
    record=dict(run_id=run,pid='pg-recovery-probe',status='success',created_at='2030-01-01 00:00:00',db_synced=True,history_saved=True)
    from unittest.mock import patch
    from app.bootstrap import auxiliary_store
    directory=Path(os.environ['WFS_DATA_DIR'])/'acceptance-recovery'
    with patch.object(auxiliary_store,'gauss_store',side_effect=RuntimeError('Simulated connection outage')):
        journal.write(directory,record,{'success'})
        assert journal.read(directory,run)['status']=='success'
    journal.import_legacy(directory,{'success'},100)
    assert not (directory/(run+'.json')).exists()
    assert journal.read(directory,run)['status']=='success'
    with journal.connection(directory) as db: db.execute('DELETE FROM journal WHERE run_id=?',(run,))
    print('RECOVERY_SPOOL_TO_REAL_POSTGRES_OK',flush=True)
    from scripts.migrate_legacy_tasks import migrate_task
    from app.bootstrap import task_packages as packages
    from app.bootstrap.schedule_config import save_schedule
    examples=[('pg_output_demo','文件输出示例','file_output','main.py'),
              ('pg_nested_demo','多层目录示例','nested_report','report_job/main.py')]
    for pid,name,folder,entry in examples:
        if packages.registry().get(pid,{}).get('active_version'): continue
        migrate_task(dict(pid=pid,group_name='PostgreSQL验收',folder_name=folder,task_name=name,
                          task_dir=ROOT/'examples/tasks'/folder,main_file=entry),'local-postgres-acceptance')
        save_schedule(pid,dict(schedule_type='every_hour',main_file=entry,enabled=False,task_name=name,max_instances=1,timeout_seconds=30))
        print('DEMO_PUBLISHED',pid,flush=True)
    assert not list(Path(os.environ['WFS_DATA_DIR']).rglob('*.sqlite3'))
    with GaussDB() as db:
        count=db.execute_query_sql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='wfs'")[0][0]
        assert count==32
    print('REAL_POSTGRES_ACCEPTANCE_OK: 32 tables; no SQLite state files',flush=True)


if __name__=='__main__': main()
