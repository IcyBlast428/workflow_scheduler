import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest.mock import patch
import zipfile
from scripts.backup_local import backup
from scripts.backup_platform import bundle
from scripts.restore_local import restore


@unittest.skipIf(os.name == 'nt', 'Linux backup lease and interpreter mode')
class ManagedBackupTests(unittest.TestCase):
    def test_local_and_platform_restore_managed_code_data_and_interpreter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data'
            releases = root / 'custom-releases'
            version = releases / 'job/releases/v1'
            (version / 'code').mkdir(parents=True)
            (version / 'code/main.py').write_text('print("managed restore proof")')
            (version / '.release.json').write_text('{}')
            python = version / 'environment-proof/bin/python'
            venv.EnvBuilder(with_pip=False).create(python.parent.parent)
            output = data / 'task-data/job/output.txt'
            output.parent.mkdir(parents=True)
            output.write_text('persistent output')
            database = root / 'local.sqlite3'
            with sqlite3.connect(database) as connection:
                connection.execute('CREATE TABLE proof(value TEXT)')
            jobs = root / 'jobs'
            jobs.mkdir()
            def dump(command, **kwargs):
                Path(command[command.index('-f') + 1]).write_bytes(b'database fixture')
            for kind in ('local', 'platform'):
                archive = root / (kind + '.zip')
                if kind == 'local':
                    backup(database, data, archive, releases)
                else:
                    with patch('scripts.backup_platform.subprocess.run', side_effect=dump):
                        bundle(data, jobs, archive, 'test', 'test', 'test', releases=releases)
                target = restore(archive, root / kind)
                restored = target / 'data/task-packages/job/releases/v1'
                self.assertEqual((target / 'data/task-data/job/output.txt').read_text(), 'persistent output')
                self.assertTrue((restored / '.release.json').is_file())
                interpreter = restored / 'environment-proof/bin/python'
                self.assertFalse(interpreter.is_symlink())
                result = subprocess.run([str(interpreter), str(restored / 'code/main.py')], capture_output=True, text=True, check=True)
                self.assertIn('managed restore proof', result.stdout)
                self.assertTrue((interpreter.parent.parent / 'lib64').is_dir())

    def test_backup_refuses_external_business_data_links(self):
        from scripts.backup_files import add_task_storage
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data/task-data/job'
            data.mkdir(parents=True)
            secret = root / 'outside'
            secret.write_text('not backup data')
            (data / 'external').symlink_to(secret)
            with zipfile.ZipFile(root / 'proof.zip', 'w') as archive:
                with self.assertRaises(ValueError):
                    add_task_storage(archive, root / 'data')
