"""Operational snapshots invalidate across processes without caching credentials."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import test_local_integration
from app.bootstrap import admission, operational_policy


class PolicyCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment=patch.dict(os.environ,{'WFS_DATA_DIR':self.directory.name})
        environment.start();self.addCleanup(environment.stop)
        admission.clear_policy_cache()
        self.addCleanup(admission.clear_policy_cache)

    def test_repeated_concurrent_policy_reads_share_one_query_and_return_copies(self):
        with patch.object(admission,'_read_policy',wraps=admission._read_policy) as read:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                values=list(executor.map(lambda _:operational_policy.load('dispatch'),range(80)))
            self.assertEqual(read.call_count,1)
            values[0]['max_active']=99
            self.assertEqual(operational_policy.load('dispatch')['max_active'],4)

    def test_slow_query_does_not_block_other_policies_or_publish_after_invalidation(self):
        started=threading.Event();release=threading.Event()
        def read(key):
            if key=='task:slow':
                started.set()
                self.assertTrue(release.wait(5))
            return {'revision':0}
        with patch.object(admission,'_read_policy',side_effect=read):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                slow=executor.submit(operational_policy.load,'task','slow')
                try:
                    self.assertTrue(started.wait(2))
                    fast=executor.submit(operational_policy.load,'dispatch')
                    self.assertEqual(fast.result(timeout=2)['revision'],0)
                    admission.clear_policy_cache()
                finally:
                    release.set()
                slow.result(timeout=2)
            self.assertEqual(len(admission._policy_cache),0)

    def test_successful_save_invalidates_another_process_immediately(self):
        with patch.object(admission.time,'monotonic',return_value=100):
            self.assertEqual(operational_policy.load('dispatch')['max_active'],4)
            script=("from app.bootstrap import operational_policy as p; "
                    "p.save('dispatch','',{**p.load('dispatch'),'max_active':2},'other-process')")
            result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(operational_policy.load('dispatch')['max_active'],2)
            self.assertTrue((Path(self.directory.name)/'policy-cache.version').is_file())

    def test_marker_read_failure_bypasses_cache(self):
        operational_policy.load('dispatch')
        with patch.object(admission,'_policy_version',return_value=None),patch.object(admission,'_read_policy',wraps=admission._read_policy) as read:
            operational_policy.load('dispatch');operational_policy.load('dispatch')
            self.assertEqual(read.call_count,2)

    def test_external_updates_expire_and_authorization_is_never_cached(self):
        with patch.object(admission.time,'monotonic',return_value=100):
            operational_policy.load('dispatch')
        with patch.object(admission.time,'monotonic',return_value=106),patch.object(admission,'_read_policy',wraps=admission._read_policy) as read:
            operational_policy.load('dispatch')
            admission.grant('task');admission.grant('task')
            self.assertEqual(read.call_count,3)

    def test_failed_query_is_not_cached_and_cache_is_bounded(self):
        with patch.object(admission,'_read_policy',side_effect=[RuntimeError('offline'),None]) as read:
            with self.assertRaises(RuntimeError):operational_policy.load('dispatch')
            self.assertEqual(operational_policy.load('dispatch')['max_active'],4)
            self.assertEqual(read.call_count,2)
        with patch.object(admission,'_POLICY_CACHE_LIMIT',3),patch.object(admission,'_read_policy',return_value=None):
            for n in range(10):operational_policy.load('task',str(n))
            self.assertEqual(len(admission._policy_cache),3)


if __name__=='__main__':unittest.main()
