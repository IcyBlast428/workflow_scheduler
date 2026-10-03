"""Release control-flow tests with fake external services; no systemd mutation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipIf(os.name == 'nt', 'Linux deployment shell test')
class ReleaseTests(unittest.TestCase):
    def test_build_failure_health_failure_and_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, binaries, fixture = root/'source',root/'bin',root/'fixture'
            for directory in (source,binaries,fixture/'app/config/driver/dws_odbc/etc',fixture/'app/jobs'):
                directory.mkdir(parents=True)
            (fixture/'app/config/driver/dws_odbc/etc/odbcinst.ini').write_text('/data/wfs/current/driver')
            def stub(name, body):
                path = binaries/name
                path.write_text('#!/bin/bash\n' + body + '\n'); path.chmod(0o755)
            stub('git', 'if [[ "$*" == *archive* ]]; then tar -C "$TEST_FIXTURE" -cf - .; elif [[ "$*" == *--show-toplevel* ]]; then echo "$TEST_SOURCE"; else echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; fi')
            stub('id','exit 0')
            stub('chown','exit 0')
            stub('chmod','exit 0')
            stub('npm','[[ "$TEST_FAILURE" != build ]]')
            stub('sleep','exit 0')
            stub('curl','[[ "$TEST_FAILURE" != health ]]')
            stub('systemctl','echo "$*" >> "$TEST_ACTIONS"')
            stub('python3', 'mkdir -p "$3/bin"; printf "#!/bin/bash\\nexit 0\\n" > "$3/bin/python"; /bin/chmod +x "$3/bin/python"')
            env_file = root/'wfs.env'; env_file.write_text('WFS_ENV=production\n')
            script = Path(__file__).resolve().parents[1]/'scripts/deploy_release.sh'
            # The harness removes the root gate and redirects /etc to a private fixture.
            harness = root/'deploy.sh'
            content = script.read_text().replace("[[ $EUID == 0 ]] || { echo 'Run as root to switch and restart systemd services.' >&2; exit 2; }", ':')
            harness.write_text(content.replace('/etc/wfs/wfs.env',str(env_file)))
            for failure in ('build','health','none'):
                with self.subTest(failure=failure):
                    base = root/f'deployment-{failure}'
                    old = base/'releases/old'; old.mkdir(parents=True)
                    (base/'current').symlink_to(old)
                    actions = root/f'{failure}.actions'
                    environment = dict(os.environ,PATH=str(binaries)+':'+os.environ['PATH'],TEST_FIXTURE=str(fixture),TEST_SOURCE=str(source),TEST_FAILURE=failure,TEST_ACTIONS=str(actions))
                    result = subprocess.run(['bash',str(harness),'test-ref',str(base)],env=environment,capture_output=True,text=True,timeout=20)
                    if failure == 'none':
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertEqual((base/'current').resolve().name,'a'*40)
                        self.assertTrue((base/'shared/data').is_dir())
                    else:
                        self.assertNotEqual(result.returncode,0)
                        self.assertEqual((base/'current').resolve(),old)
                    if failure == 'health':
                        self.assertEqual(actions.read_text().splitlines(),['restart wfs-scheduler wfs','restart wfs-scheduler wfs'])
                    elif failure == 'build':
                        self.assertFalse(actions.exists())
