"""Release ordering and recovery with fake external tools; never mutates systemd."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipIf(os.name == 'nt', 'Linux deployment shell test')
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.binaries, fixture = self.root/'source', self.root/'bin', self.root/'fixture'
        for directory in (self.source, self.binaries, fixture/'app/config/driver/dws_odbc/etc', fixture/'app/jobs'):
            directory.mkdir(parents=True)
        (fixture/'app/config/driver/dws_odbc/etc/odbcinst.ini').write_text('/data/wfs/current/driver')
        def stub(name, body):
            path = self.binaries/name
            path.write_text('#!/bin/bash\n' + body + '\n'); path.chmod(0o755)
        stub('git', 'if [[ "$*" == *archive* ]]; then tar -C "$TEST_FIXTURE" -cf - .; elif [[ "$*" == *--show-toplevel* ]]; then echo "$TEST_SOURCE"; else echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; fi')
        stub('id', 'exit 0'); stub('chown', 'exit 0'); stub('chmod', 'exit 0')
        stub('npm', '[[ "$TEST_FAILURE" != build ]]')
        stub('sleep', 'exit 0'); stub('curl', '[[ "$TEST_FAILURE" != health ]]')
        stub('systemctl', '''if [[ "$1" == show ]]; then
    if [[ "$*" == *LoadState* ]]; then echo loaded
    elif [[ "$TEST_ACTIVE" == true ]]; then echo active
    elif [[ "$TEST_ACTIVE" == false ]]; then echo inactive
    else echo "$TEST_ACTIVE"; fi
elif [[ "$1" == is-active ]]; then [[ "$TEST_ACTIVE" == true ]]
else echo "$*" >> "$TEST_ACTIONS"; fi''')
        stub('python3.12', '''if [[ "$1" == -c ]]; then echo 3.12; exit 0; fi
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'SCRIPT'
#!/bin/bash
echo "$*" >> "$TEST_PYTHON_ACTIONS"
if [[ "$TEST_FAILURE" == migrate && "$*" == *scripts/migrate.py* ]]; then exit 1; fi
exit 0
SCRIPT
/bin/chmod +x "$3/bin/python"''')
        self.config = self.root/'wfs.env'; self.config.write_text('WFS_ENV=production\n')
        original = Path(__file__).resolve().parents[1]/'scripts/deploy_release.sh'
        self.script = self.root/'deploy.sh'
        self.script.write_text(original.read_text().replace("[[ $EUID == 0 ]] || { echo 'Run as root to switch and restart systemd services.' >&2; exit 2; }", ':'))
        self.environment = dict(os.environ, PATH=str(self.binaries)+':'+os.environ['PATH'], TEST_FIXTURE=str(fixture),
            TEST_SOURCE=str(self.source), TEST_FAILURE='none', TEST_ACTIVE='false',
            TEST_ACTIONS=str(self.root/'actions'), TEST_PYTHON_ACTIONS=str(self.root/'python-actions'),
            WFS_DEPLOY_CONFIG=str(self.config))

    def deployment(self, name):
        base = self.root/name
        old = base/'releases/old'; old.mkdir(parents=True)
        (base/'current').symlink_to(old)
        return base, old

    def invoke(self, base, mode=None, **environment):
        command = ['bash', str(self.script)] + ([mode] if mode else []) + ['test-ref', str(base)]
        return subprocess.run(command, env={**self.environment, **environment}, capture_output=True, text=True, timeout=20)

    def actions(self):
        path = self.root/'actions'
        return path.read_text().splitlines() if path.exists() else []

    def test_build_failure_health_failure_and_success(self):
        for failure in ('build', 'health', 'none'):
            with self.subTest(failure=failure):
                (self.root/'actions').unlink(missing_ok=True)
                base, old = self.deployment(failure)
                result = self.invoke(base, TEST_FAILURE=failure)
                if failure == 'none':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((base/'current').resolve().name, 'a'*40)
                    self.assertTrue((base/'shared/data').is_dir())
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual((base/'current').resolve(), old)
                if failure == 'health':
                    self.assertEqual(self.actions(), ['start wfs-scheduler.service wfs.service',
                        'stop wfs.service wfs-scheduler.service', 'start wfs-scheduler.service wfs.service'])
                elif failure == 'build':
                    self.assertFalse(self.actions())

    def test_prepare_is_safe_while_live_and_activate_requires_stopped_services(self):
        base, old = self.deployment('phases')
        result = self.invoke(base, '--prepare', TEST_ACTIVE='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((base/'current').resolve(), old)
        self.assertFalse(self.actions())
        self.assertNotIn('scripts/migrate.py', (self.root/'python-actions').read_text())
        for state in ('true', 'activating', 'deactivating'):
            result = self.invoke(base, '--activate', TEST_ACTIVE=state)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.actions())
            self.assertNotIn('scripts/migrate.py', (self.root/'python-actions').read_text())
        result = self.invoke(base, '--activate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scripts/migrate.py', (self.root/'python-actions').read_text())

    def test_migration_failure_keeps_previous_release_without_starting_services(self):
        base, old = self.deployment('migration')
        result = self.invoke(base, TEST_FAILURE='migrate')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((base/'current').resolve(), old)
        self.assertFalse(self.actions())

    def test_activation_rejects_unprepared_release(self):
        base, old = self.deployment('unprepared')
        (base/'releases'/('a'*40)).mkdir()
        result = self.invoke(base, '--activate')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((base/'current').resolve(), old)
        self.assertFalse(self.actions())


if __name__ == '__main__':
    unittest.main()
