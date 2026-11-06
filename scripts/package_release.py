"""Package the current working tree, prebuilt UI and deployment guides without local state."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {'app', 'frontend', 'scripts', 'deploy', 'docs', 'schema', 'examples', 'tests', '.github'}
SOURCE_FILES = {'README.md', 'START-HERE.md', 'DATABASE.md', 'deploy.sh', 'run.py', 'run.sh', 'run.bat',
                'gunicorn.conf.py', 'backend_dev_runner.py', 'requirements.txt', 'requirements-test.txt',
                'requirements-databases.txt', 'requirements-linux-py312.lock', '.gitattributes', '.gitignore',
                '.gitlab-ci.yml', 'wfs.service', 'wfs-scheduler.service'}
BLOCKED = {'node_modules', '__pycache__', '.git', '.venv', 'test-results', 'playwright-report', '.pytest_cache'}


def permitted(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and '\\' not in name
            and not BLOCKED.intersection(path.parts)
            and not path.name.startswith('.env') and path.name != 'runtime.env'
            and path.suffix not in ('.pyc', '.pyo', '.log', '.zip')
            and (path.parts[0] in SOURCE_DIRS or name in SOURCE_FILES)
            and not name.startswith('app/jobs/'))


def sanitize(name, blob):
    if name == 'app/config/database/db_nacos_conf.py':
        return b'# Optional legacy integration template; no credentials are distributed.\ndb_nacos_conf_dic = {"prom": {"tenant": "", "data_id": "", "group": "", "user_name": "", "password": ""}}\n'
    if name in ('app/config/wop/development.py', 'app/config/wop/production.py'):
        tree = ast.parse(blob.decode('utf-8-sig'))
        result = '# Optional integration templates; fill locally only if needed.\n'
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Dict):
                values = ast.literal_eval(node.value)
                result += node.targets[0].id + ' = ' + repr({key:'' for key in values}) + '\n'
        return result.encode()
    if name in ('app/config/production.ini', 'app/config/development.ini'):
        return re.sub(r'(?m)^(pull_api_url|admin_password_cipher|admin_token|mpcm_access_token)=.*$', r'\1=', blob.decode('utf-8-sig')).encode()
    return blob


def collect(root=ROOT):
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode('utf-8').split('\0')
    payload, sanitized = {}, []
    for name in sorted(set(filter(None, names))):
        path = root/name
        if not permitted(name) or not path.exists():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Refusing symlink or external source: ' + name)
        original = path.read_bytes()
        blob = sanitize(name, original)
        if name == 'app/config/driver/dws_odbc/etc/odbc.ini':
            blob = (root/'deploy/root-test/odbc/odbc.ini').read_bytes()
        if name == 'app/config/driver/dws_odbc/etc/odbcinst.ini':
            blob = (root/'deploy/root-test/odbc/odbcinst.ini').read_bytes()
        if blob != original:
            sanitized.append(name)
        if path.suffix in ('.sh', '.service', '.py', '.md', '.ini', '.sql', '.example'):
            blob = blob.replace(b'\r\n', b'\n')
        payload[name] = blob
    for required in ('START-HERE.md', 'deploy.sh', 'scripts/deploy.py', 'schema/gauss.sql',
                     'app/dist/index.html', 'app/dist/.vite/manifest.json', 'requirements-linux-py312.lock'):
        if required not in payload:
            raise ValueError('Missing required file: ' + required)
    # Catch a mismatched HTML/manifest/chunk bundle before handing off the ZIP.
    manifest = json.loads(payload['app/dist/.vite/manifest.json'])
    for item in manifest.values():
        for name in [item['file'], *item.get('css', []), *item.get('assets', [])]:
            if 'app/dist/' + name not in payload:
                raise ValueError('Missing built frontend asset: ' + name)
    return payload, sanitized


def package(output, root=ROOT):
    payload, sanitized = collect(root)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root))
    metadata = {'base_revision':revision, 'working_tree_changes':dirty,
                'created_at':datetime.now(timezone.utc).isoformat(),
                'kind':'root-gaussdb-working-tree-with-prebuilt-ui', 'includes_dependency_wheels':False,
                'sanitized_templates':sanitized,
                'files':[{'path':name, 'size':len(blob), 'sha256':hashlib.sha256(blob).hexdigest()}
                         for name, blob in sorted(payload.items())]}
    payload['PACKAGE-MANIFEST.json'] = (json.dumps(metadata, ensure_ascii=False, indent=2)+'\n').encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of an older deliverable.
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, blob in sorted(payload.items()):
            info = zipfile.ZipInfo('workflow_scheduler/' + name)
            info.create_system = 3
            executable = name.endswith('.sh') or '/dws_odbc/bin/' in name
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, blob)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP integrity check failed')
        for item in metadata['files']:
            if hashlib.sha256(archive.read('workflow_scheduler/'+item['path'])).hexdigest() != item['sha256']:
                raise ValueError('Package checksum failed: ' + item['path'])
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n', encoding='ascii')
    return {'path':str(output.resolve()), 'bytes':output.stat().st_size, 'files':len(payload),
            'sha256':digest, 'base_revision':revision, 'working_tree_changes':dirty}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.output), ensure_ascii=False, indent=2))
