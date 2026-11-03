"""Execute bundled examples against temporary outputs and a private SQLite file."""
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]/'examples/tasks/feature_suite'
class FeatureExamples(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def run_example(self,name,params=None,day='2026-01-05',source='manual',success=True):
  output=self.root/name/'out';data=self.root/name/'data';output.mkdir(parents=True,exist_ok=True);data.mkdir(exist_ok=True)
  env=dict(os.environ,WFS_OUTPUT_DIR=str(output),WFS_TASK_DATA_DIR=str(data),WFS_BUSINESS_DATE=day,WFS_EXECUTION_SOURCE=source,WFS_PARAMETERS_JSON=json.dumps(params or {}))
  result=subprocess.run([sys.executable,str(ROOT/name/'main.py')],env=env,capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode==0,success,result.stderr)
  return output,data
 def test_report_filters_and_uses_bundled_module_and_resource(self):
  out,_=self.run_example('report_flow',{'region':'CN'})
  report=json.loads((out/'summary.json').read_text());self.assertEqual(report['count'],1);self.assertEqual(report['amount'],100)
  self.assertTrue((out/'report.csv').exists())
 def test_transaction_is_repeatable_and_rolls_back_changes(self):
  _,data=self.run_example('sqlite_transaction');self.run_example('sqlite_transaction')
  self.run_example('sqlite_transaction',{'simulate_rollback':True},day='2026-01-06',success=False)
  with sqlite3.connect(data/'demo.sqlite3') as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM demo_item').fetchone()[0],2)
   self.assertEqual(db.execute("SELECT COUNT(*) FROM demo_batch WHERE business_date='2026-01-06'").fetchone()[0],0)
 def test_failure_retry_and_trial_paths(self):
  self.run_example('retry_once',success=False)
  out,_=self.run_example('retry_once',source='retry');self.assertTrue(json.loads((out/'retry-result.json').read_text())['success'])
  self.run_example('retry_once',source='trial')
 def test_backfill_targets_business_date_and_replaces_same_day(self):
  _,data=self.run_example('business_backfill');first=(data/'daily/2026-01-05.json').read_bytes()
  self.run_example('business_backfill');self.assertEqual(first,(data/'daily/2026-01-05.json').read_bytes())
  self.run_example('business_backfill',day='2026-01-06');self.assertEqual(len(list((data/'daily').glob('*.json'))),2)
 def test_queue_observer_finishes_with_progress_and_output(self):
  out,_=self.run_example('queue_observer',{'seconds':1});self.assertTrue(json.loads((out/'progress.json').read_text())['done'])
if __name__=='__main__':unittest.main()
