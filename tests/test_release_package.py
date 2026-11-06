import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import package_release as package


class ReleasePackageTests(unittest.TestCase):
    def test_local_secrets_and_runtime_files_are_excluded(self):
        for name in ('data/environment.json', '.env.local', 'deploy/root-test/runtime.env',
                     'frontend/node_modules/dep.js', 'app/__pycache__/test.pyc',
                     'frontend/test-results/output.png', '../app/run.py', 'app/jobs/private/main.py'):
            self.assertFalse(package.permitted(name), name)
        self.assertTrue(package.permitted('app/dist/static/index-new.js'))
        self.assertTrue(package.permitted('scripts/deploy.py'))

    def test_legacy_templates_do_not_distribute_old_accounts(self):
        text = package.sanitize('app/config/database/db_nacos_conf.py', b'password=secret')
        self.assertNotIn(b'secret', text)
        text = package.sanitize('app/config/wop/production.py', b"profile = {'name':'someone','email':'person@example.com'}")
        self.assertNotIn(b'someone', text)
        self.assertNotIn(b'person@example.com', text)

    def test_snapshot_is_complete_verified_and_never_overwrites(self):
        payload = {'START-HERE.md':b'guide', 'scripts/deploy.py':b'print(1)', 'deploy.sh':b'#!/bin/bash\n'}
        with tempfile.TemporaryDirectory() as directory, patch.object(package, 'collect', return_value=(payload, [])), \
             patch.object(package.subprocess, 'check_output', side_effect=['a'*40+'\n', b' M modified', 'a'*40+'\n', b' M modified']):
            target = Path(directory)/'release.zip'
            result = package.package(target)
            self.assertTrue(result['working_tree_changes'])
            with zipfile.ZipFile(target) as archive:
                manifest = json.loads(archive.read('workflow_scheduler/PACKAGE-MANIFEST.json'))
                for entry in manifest['files']:
                    self.assertEqual(hashlib.sha256(archive.read('workflow_scheduler/'+entry['path'])).hexdigest(), entry['sha256'])
                self.assertEqual(archive.getinfo('workflow_scheduler/deploy.sh').external_attr >> 16 & 0o777, 0o755)
            self.assertEqual(result['sha256'], target.with_suffix('.zip.sha256').read_text().split()[0])
            with self.assertRaises(FileExistsError): package.package(target)


if __name__ == '__main__':
    unittest.main()
