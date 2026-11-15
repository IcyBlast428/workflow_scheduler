"""Encrypted bootstrap evidence must survive backup without being applied on restore."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile
from cryptography.fernet import Fernet
from scripts.backup_bootstrap import collect, receipt_plan
from scripts.backup_platform import bundle
from scripts.restore_platform import restore


@unittest.skipIf(os.name == 'nt', 'Backup uses the Linux scheduler lease')
class PlatformConfigBackupTests(unittest.TestCase):
    def test_custom_pending_and_active_are_distinct_encrypted_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data, jobs = root / 'data', root / 'jobs'
            data.mkdir(); jobs.mkdir()
            key = Fernet.generate_key()
            pending, active = root / 'outside-private.enc', root / 'runtime.enc'
            cipher = Fernet(key)
            pending_bytes = cipher.encrypt(b'{"host":"new-target","password":"secret-new"}')
            active_bytes = cipher.encrypt(b'{"host":"old-target","password":"secret-old"}')
            pending.write_bytes(pending_bytes); active.write_bytes(active_bytes)
            def dump(command, **kwargs):
                Path(command[command.index('-f') + 1]).write_bytes(b'old-target dump fixture')
            archive = root / 'backup.zip'
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': str(pending),
                                         'WFS_PLATFORM_ACTIVE_CONFIG_FILE': str(active)}), \
                 patch('scripts.backup_platform.subprocess.run', side_effect=dump), \
                 patch('scripts.backup_receipt.record'):
                bundle(data, jobs, archive, 'old-db', 'wfs', 'owner')
            with zipfile.ZipFile(archive) as source:
                manifest = json.loads(source.read('manifest.json'))
                self.assertEqual(manifest['database'], 'old-db')
                self.assertFalse(manifest['platform_configuration']['keys_included'])
                self.assertFalse(manifest['platform_configuration']['automatic_restore'])
                self.assertEqual(source.read('bootstrap/platform-connection.enc'), pending_bytes)
                self.assertEqual(source.read('bootstrap/platform-active.enc'), active_bytes)
                self.assertNotIn(str(pending), source.read('manifest.json').decode())
                self.assertFalse(any('secret' in item or '.env' in item for item in source.namelist()))
                self.assertNotIn(key, b''.join(source.read(item) for item in source.namelist()))
            destination = restore(archive, root / 'restored')
            self.assertEqual((destination / 'bootstrap/platform-connection.enc').read_bytes(), pending_bytes)
            self.assertFalse((destination / 'data/platform-connection.enc').exists())
            receipt = json.loads((destination / 'restore-receipt.json').read_text())
            self.assertFalse(receipt['platform_configuration_applied'])
            self.assertEqual((destination / 'bootstrap/platform-active.enc').stat().st_mode & 0o777, 0o600)

    def test_pending_without_active_never_writes_a_database_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data, jobs = root / 'data', root / 'jobs'
            data.mkdir(); jobs.mkdir()
            (data / 'platform-connection.enc').write_bytes(Fernet(Fernet.generate_key()).encrypt(b'pending'))
            def dump(command, **kwargs):
                Path(command[command.index('-f') + 1]).write_bytes(b'dump')
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': '', 'WFS_PLATFORM_ACTIVE_CONFIG_FILE': ''}), \
                 patch('scripts.backup_platform.subprocess.run', side_effect=dump), \
                 patch('scripts.backup_receipt.record') as record:
                output = bundle(data, jobs, root / 'backup.zip', 'old-db', 'wfs', 'owner')
                record.assert_not_called()
            with zipfile.ZipFile(output) as archive:
                receipt = json.loads(archive.read('manifest.json'))['backup_receipt']
                self.assertFalse(receipt['written'])
                self.assertEqual(receipt['reason'], 'pending_configuration_is_not_active_evidence')

    def test_receipt_requires_matching_active_host_port_database_and_schema(self):
        from app.bootstrap import platform_config
        from app.bootstrap.database import GaussDB
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'WFS_CONNECTIONS_KEY': 'backup-test-key'}):
            root = Path(folder)
            active, pending = root / 'active.enc', root / 'pending.enc'
            options = {**platform_config.defaults(), 'source': 'direct', 'revision': 1,
                       'host': 'db.example', 'port': 8000, 'database': 'old_db', 'schema': 'wfs',
                       'user': 'owner', 'password': 'secret'}
            cipher = platform_config._cipher()
            active.write_bytes(cipher.encrypt(json.dumps(options).encode()))
            pending.write_bytes(cipher.encrypt(json.dumps({**options, 'database': 'new_db'}).encode()))
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': str(pending),
                                         'WFS_PLATFORM_ACTIVE_CONFIG_FILE': str(active)}):
                files, metadata = collect(root)
                target = dict(host='db.example', port=8000, database='old_db', schema='wfs')
                receipt, frozen = receipt_plan(files, metadata, **target)
                self.assertTrue(receipt['write_requested'])
                self.assertEqual(frozen['database'], 'old_db')
                for key, value in [('host', 'another.example'), ('port', 5432),
                                   ('database', 'new_db'), ('schema', 'other')]:
                    with self.subTest(field=key):
                        receipt, frozen = receipt_plan(files, metadata, **{**target, key: value})
                        self.assertFalse(receipt['written'])
                        self.assertIsNone(frozen)
                receipt, frozen = receipt_plan(files, metadata, container='some-container', **target)
                self.assertFalse(receipt['write_requested'])
                # A service profile is resolved read-only, checked, then frozen as
                # direct options so receipt recording cannot resolve a new target.
                service = {**options, 'source': 'service', 'db_id': 'old_wfs'}
                active.write_bytes(cipher.encrypt(json.dumps(service).encode()))
                files, metadata = collect(root)
                resolved = dict(host='db.example', port=8000, db='old_db', user='owner', password='secret')
                with patch.object(GaussDB, '_GaussDB__get_db_config', return_value=resolved):
                    receipt, frozen = receipt_plan(files, metadata, **target)
                self.assertTrue(receipt['write_requested'])
                self.assertEqual(frozen['source'], 'direct')
                self.assertEqual(frozen['database'], 'old_db')

    def test_legacy_service_receipt_also_verifies_the_dump_endpoint(self):
        from app.bootstrap.database import GaussDB
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': '', 'WFS_PLATFORM_ACTIVE_CONFIG_FILE': ''}):
            files, metadata = collect(Path(folder))
            resolved = dict(host='legacy.example', port=8000, db='legacy', user='owner', password='secret')
            target = dict(host='legacy.example', port=8000, database='legacy', schema='wfs')
            with patch('app.bootstrap.database._split_db_id', return_value=('legacy', 'wfs')), \
                 patch.object(GaussDB, '_GaussDB__get_db_config', return_value=resolved):
                receipt, frozen = receipt_plan(files, metadata, **target)
                self.assertTrue(receipt['write_requested'])
                self.assertEqual(receipt['reason'], 'service_target_verified')
                self.assertEqual(frozen['source'], 'direct')
                self.assertEqual(frozen['host'], 'legacy.example')
                for key, value in [('host', 'other.example'), ('port', 5432),
                                   ('database', 'other'), ('schema', 'other')]:
                    with self.subTest(field=key):
                        receipt, frozen = receipt_plan(files, metadata, **{**target, key: value})
                        self.assertFalse(receipt['write_requested'])
                        self.assertIsNone(frozen)
            with patch.object(GaussDB, '_GaussDB__get_db_config', side_effect=RuntimeError('unavailable')):
                receipt, frozen = receipt_plan(files, metadata, **target)
                self.assertFalse(receipt['written'])
                self.assertIsNone(frozen)

    def test_direct_script_entry_resolves_service_target_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data, jobs = root / 'data', root / 'jobs'
            data.mkdir(); jobs.mkdir()
            vendor = root / 'vendor-dump'
            vendor.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                              'Path(sys.argv[sys.argv.index("-f") + 1]).write_bytes(b"dump fixture")\n')
            vendor.chmod(0o700)
            environment = dict(os.environ)
            environment.pop('PYTHONPATH', None)
            environment.update(WFS_PLATFORM_CONFIG_FILE='', WFS_PLATFORM_ACTIVE_CONFIG_FILE='')
            archive = root / 'backup.zip'
            script = Path(__file__).resolve().parents[1] / 'scripts/backup_platform.py'
            result = subprocess.run([sys.executable, str(script), '--data', str(data), '--tasks', str(jobs),
                                     '--output', str(archive), '--database', 'different_from_test_database',
                                     '--schema', 'wfs', '--user', 'owner', '--tool', str(vendor)],
                                    env=environment, cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(archive) as source:
                receipt = json.loads(source.read('manifest.json'))['backup_receipt']
                self.assertFalse(receipt['write_requested'])
                self.assertEqual(receipt['reason'], 'active_configuration_does_not_match_dump_target')

    def test_unavailable_active_snapshot_is_not_claimed_as_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'platform-connection.enc').write_bytes(Fernet(Fernet.generate_key()).encrypt(b'pending'))
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': '',
                                         'WFS_PLATFORM_ACTIVE_CONFIG_FILE': str(root / 'removed.enc')}):
                files, manifest = collect(root)
            self.assertTrue(manifest['pending']['included'])
            self.assertFalse(manifest['active']['included'])
            self.assertEqual(list(files), ['bootstrap/platform-connection.enc'])

    def test_explicit_missing_plaintext_or_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'custom.enc'
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': str(config), 'WFS_PLATFORM_ACTIVE_CONFIG_FILE': ''}):
                with self.assertRaises(ValueError): collect(root)
                config.write_text('PASSWORD=do-not-copy')
                with self.assertRaises(ValueError): collect(root)
                config.unlink(); config.symlink_to(root / 'outside')
                with self.assertRaises(ValueError): collect(root)

    def test_restore_rejects_tampered_configuration_before_creating_destination(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'bad.zip'
            dump = b'dump'
            manifest = {'format': 'wfs-platform-1', 'dump_sha256': hashlib.sha256(dump).hexdigest(),
                        'platform_configuration': {'pending': {'included': True,
                            'archive_path': 'bootstrap/platform-connection.enc', 'sha256': '0' * 64},
                            'active': {'included': False}}}
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('manifest.json', json.dumps(manifest))
                output.writestr('database.dump', dump)
                output.writestr('bootstrap/platform-connection.enc', b'changed')
            with self.assertRaisesRegex(ValueError, '校验失败'):
                restore(archive, root / 'restored')
            self.assertFalse((root / 'restored').exists())

    def test_nacos_bootstrap_is_encrypted_separate_evidence_and_old_manifests_still_verify(self):
        from scripts.backup_bootstrap import verify, write
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            custom = root / 'custom-nacos.enc'
            encrypted = Fernet(Fernet.generate_key()).encrypt(b'{"password":"nacos-secret"}')
            custom.write_bytes(encrypted)
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': '', 'WFS_PLATFORM_ACTIVE_CONFIG_FILE': '',
                                         'WFS_NACOS_CONFIG_FILE': str(custom)}):
                files, metadata = collect(root)
            self.assertEqual(files['bootstrap/nacos-connection.enc'], encrypted)
            self.assertTrue(metadata['nacos']['included'])
            self.assertNotIn(str(custom), json.dumps(metadata))
            self.assertNotIn('nacos-secret', json.dumps(metadata))
            archive = root / 'bootstrap.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                write(output, files)
            with zipfile.ZipFile(archive) as source:
                verify(source, {'platform_configuration': metadata})
                legacy = {key: value for key, value in metadata.items() if key != 'nacos'}
                verify(source, {'platform_configuration': legacy})
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': '', 'WFS_PLATFORM_ACTIVE_CONFIG_FILE': '',
                                         'WFS_NACOS_CONFIG_FILE': str(root / 'missing.enc')}):
                with self.assertRaises(ValueError):
                    collect(root)

    def test_nacos_receipt_uses_only_frozen_startup_credentials(self):
        from app.bootstrap import platform_config
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'WFS_CONNECTIONS_KEY': 'backup-test-key'}):
            root = Path(folder)
            active = root / 'active.enc'
            target = dict(host='original.example', port=8000, database='original', schema='wfs')
            resolved = {**target, 'user': 'owner', 'password': 'original-password'}
            options = {**platform_config.defaults(), 'source': 'nacos', 'revision': 1,
                       'nacos': {'data_id': 'platform.json'}, 'nacos_md5': 'a' * 32,
                       '_nacos_resolved': resolved}
            cipher = platform_config._cipher()
            active.write_bytes(cipher.encrypt(json.dumps(options).encode()))
            with patch.dict(os.environ, {'WFS_PLATFORM_CONFIG_FILE': '', 'WFS_PLATFORM_ACTIVE_CONFIG_FILE': str(active),
                                         'WFS_NACOS_CONFIG_FILE': ''}), \
                 patch('app.common.nacos.Nacos.read_document', side_effect=AssertionError('must not re-read Nacos')):
                files, metadata = collect(root)
                receipt, frozen = receipt_plan(files, metadata, **target)
                self.assertTrue(receipt['write_requested'])
                self.assertEqual(frozen['source'], 'direct')
                self.assertEqual(frozen['password'], 'original-password')
                self.assertEqual(frozen['host'], 'original.example')
                options.pop('_nacos_resolved')
                active.write_bytes(cipher.encrypt(json.dumps(options).encode()))
                files, metadata = collect(root)
                receipt, frozen = receipt_plan(files, metadata, **target)
                self.assertFalse(receipt['write_requested'])
                self.assertIsNone(frozen)
                self.assertEqual(receipt['reason'], 'nacos_configuration_has_no_frozen_active_evidence')
