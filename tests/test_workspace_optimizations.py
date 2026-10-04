import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import test_local_integration  # Isolated SQLite fixture, never the local service.
from app.bootstrap.timebase import business_now, business_time, instant_iso
from app.api.task.views import _build_task_log_filters
from app.api.operations import _business_rows
from app.bootstrap.database import GaussDB
from app.bootstrap import version_storage, attention


class WorkspaceOptimizations(unittest.TestCase):
    def test_aware_instants_normalize_without_reinterpreting_legacy_times(self):
        value=dt.datetime(2026,10,4,18,tzinfo=dt.timezone.utc)
        self.assertEqual(business_time(value),dt.datetime(2026,10,5,2))
        self.assertEqual(instant_iso(value),'2026-10-05T02:00:00+08:00')
        legacy=dt.datetime(2026,10,4,9)
        self.assertEqual(business_time(legacy),legacy)
        self.assertIsNone(business_now().tzinfo)
        rows = [{'created_at': value, 'actor': 'admin'}, {'created_at': legacy}, {'created_at':None}]
        serialized = _business_rows(rows, 'created_at')
        self.assertEqual(serialized[0]['created_at'], '2026-10-05 02:00:00')
        self.assertEqual(serialized[1]['created_at'], '2026-10-04 09:00:00')
        self.assertIsNone(serialized[2]['created_at'])
        self.assertEqual(rows[0]['created_at'],value)

    def test_name_search_treats_sql_wildcards_as_literal_text(self):
        pid='filter-'+uuid.uuid4().hex
        now=business_now()
        with GaussDB() as db:
            try:
                for suffix,name in [('one','日报_100%'),('two','日报X1000')]:
                    db.execute_sql('INSERT INTO wfs_run_history(id,pid,taskname,state,start_time,end_time) VALUES(?,?,?,?,?,?)',params=(pid+suffix,pid,name,0,now,now))
                clauses,params=_build_task_log_filters(pid=pid,taskname='_100%')
                rows=db.execute_query_sql('SELECT taskname FROM wfs_run_history WHERE '+' AND '.join(clauses),params=tuple(params))
                self.assertEqual(rows,[('日报_100%',)])
            finally: db.execute_sql('DELETE FROM wfs_run_history WHERE pid=?',params=(pid,))

    def test_retention_preview_protects_current_preparing_and_execution_references(self):
        pid='storage-'+uuid.uuid4().hex; versions=[uuid.uuid4().hex for _ in range(23)]
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,{'WFS_TASK_RELEASE_DIR':temporary}):
            records=[]
            for index,version in enumerate(versions):
                path=Path(temporary)/pid/'releases'/version;path.mkdir(parents=True);(path/'code.py').write_bytes(b'code')
                records.append((json.dumps({'pid':pid,'version':version,'status':'preparing' if index==21 else 'applied' if index==22 else 'ready'}),))
            class DB:
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def execute_query_sql(self,sql): return records if 'wfs_task_releases' in sql else [(json.dumps({'pid':pid,'code_version':{'task_release':versions[22]}}),)]
            with patch.object(version_storage,'registry',return_value={pid:{'task_name':'日报','active_version':versions[20]}}),patch.object(version_storage,'GaussDB',DB):
                result=version_storage.snapshot(20)
            self.assertEqual(result['candidate_bytes'],0)
            self.assertIn('当前使用',result['versions'][20]['protected'])
            self.assertIn('正在准备',result['versions'][21]['protected'])
            self.assertIn('执行记录引用',result['versions'][22]['protected'])
            self.assertIn('可回退的已发布版本',result['versions'][22]['protected'])
            self.assertTrue((Path(temporary)/pid/'releases'/versions[22]/'code.py').exists())

    def test_attention_excludes_private_maintenance_details_for_viewers(self):
        with patch.object(attention,'discover_task_specs',return_value=[]),patch.object(attention.operations,'service_state',return_value={'ready':True,'heartbeat':business_now().isoformat()}):
            result=attention.snapshot(admin=False)
        self.assertTrue(result['scheduler']['healthy'])
        self.assertEqual(result['timezone'],'Asia/Shanghai')
        self.assertFalse(any(item['key'].startswith(('alerts','journal','disk')) for item in result['issues']))
