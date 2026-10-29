"""Disposable browser regression server; never reads .env.local or existing data."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='wfs-browser-')
root = Path(temporary.name)
os.environ.update(WFS_ENV='development', WFS_ENABLE_SCHEDULER='true', WFS_DEV_RUN_ALL='true',
                  WFS_LOCAL_DB_PATH=str(root/'database.sqlite3'),WFS_DATA_DIR=str(root/'data'),
                  WFS_LOG_DIR=str(root/'logs'),WFS_SECRET_KEY='disposable-browser-test-key',
                  WFS_SCHEDULER_CONTROL_URL='',WFS_COOKIE_SECURE='false',
                  WFS_SESSION_COOKIE_NAME='wfs_browser_acceptance_session')
from werkzeug.security import generate_password_hash
os.environ['WFS_ADMIN_PASSWORD_HASH'] = generate_password_hash('browser-test-password')
from app.bootstrap import global_vars
global_vars.TASK_DIR = root/'jobs'
task = global_vars.TASK_DIR/'acceptance'/'slow'
task.mkdir(parents=True)
(task/'main.py').write_text('import time\nprint("浏览器回归开始", flush=True)\ntime.sleep(10)\nprint("浏览器回归完成", flush=True)\n',encoding='utf-8')
(task/'README.md').write_text('隔离的浏览器回归任务。', encoding='utf-8')
output_task = global_vars.TASK_DIR/'acceptance'/'outputs'
(output_task/'src/report_job').mkdir(parents=True)
(output_task/'resources').mkdir()
(output_task/'main.py').write_text('raise RuntimeError("Choose src/report_job/main.py")\n')
(output_task/'src/report_job/__init__.py').write_text('')
(output_task/'src/report_job/helpers.py').write_text('value=42\n')
(output_task/'resources/input.txt').write_text('INPUT_OK')
(output_task/'src/report_job/main.py').write_text('''from .helpers import value
import csv, json, os
from pathlib import Path
root=Path(os.environ['WFS_TASK_ROOT'])
assert (root/'resources/input.txt').read_text() == 'INPUT_OK'
out=Path(os.environ['WFS_OUTPUT_DIR'])/'reports'
out.mkdir()
with (out/'result.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['name','amount']);writer.writerow(['a,b',value])
(out/'summary.json').write_text(json.dumps({'value':value,'run_id':os.environ['WFS_RUN_ID']}))
(out/'report.log').write_text('<script>window.outputXss=true</script>')
print('ARTIFACT_RUN_OK',flush=True)
''', encoding='utf-8')
if os.environ.get('WFS_BROWSER_FLOW_FIXTURE') == '1':
    import shutil
    shutil.copytree(ROOT/'examples/task-flow',global_vars.TASK_DIR/'acceptance'/'flow')
from app import create_app
from app.bootstrap.core import aps_start
from app.bootstrap.schedule_config import save_schedule
from app.extensions import scheduler
app = create_app()
from app.bootstrap.database import GaussDB
with GaussDB() as db:
    for username,role in [('browser-viewer','viewer'), ('browser-operator','operator'), ('browser-maintainer','maintainer')]:
        db.execute_sql('INSERT INTO wfs_users(username,password_hash,role,enabled) VALUES(?,?,?,1)',
                       params=(username,os.environ['WFS_ADMIN_PASSWORD_HASH'],role))
if scheduler.get_job('MAIN_TASK_JOB'):
    scheduler.remove_job('MAIN_TASK_JOB')
from scripts.migrate_legacy_tasks import legacy_specs, migrate_task
for fixture_spec in legacy_specs(global_vars.TASK_DIR):
    if fixture_spec['pid'] == 'acceptance__outputs':
        fixture_spec.update(task_name='目录与输出验收', main_file='src/report_job/main.py')
    migrate_task(fixture_spec, actor='browser-fixture')
save_schedule('acceptance__slow',{'schedule_type':'every_hour','main_file':'main.py','enabled':False})
from app.bootstrap.task_access import save as save_access
save_access('browser-maintainer',{'revision':0,'tasks':['acceptance__slow'],'groups':[],'capabilities':['run','schedule','view_code']},'browser-fixture')
if os.environ.get('WFS_BROWSER_FLOW_FIXTURE') == '1':
    save_schedule('acceptance__flow',{'schedule_type':'every_hour','main_file':'main.py','enabled':False})
aps_start()
if os.environ.get('WFS_BROWSER_GITLAB_FIXTURE') == '1':
    sys.path.insert(0, str(ROOT / 'tests'))
    from gitlab_fixture import serve, TOKEN, A
    from app.bootstrap import gitlab_updates
    fixture_server, fixture_url, fixture_calls = serve()
    gitlab_updates.save_configuration({**gitlab_updates.DEFAULTS, 'enabled': True,
        'url': fixture_url, 'allow_http': True, 'project': 'team/project', 'token': TOKEN,
        'platform_commit': A, 'tasks': [{'pid': 'acceptance__slow', 'path': 'app/jobs/acceptance/slow', 'commit': A}]})
    gitlab_updates.request_scan(force=True)
    import time
    deadline = time.monotonic() + 10
    while gitlab_updates.state('admin')['scanning'] and time.monotonic() < deadline:
        time.sleep(.05)
    initial_repository = dict(fixture_server.repository)
    @app.post('/api/admin/fixture/gitlab')
    def fixture_change():
        from flask import request
        action = request.get_json()['action']
        if action == 'update':
            fixture_server.repository['app/jobs/acceptance/git_new/helper.py'] = b'value="GITLAB_V2"\n'
            fixture_server.head = 'd' * 40
        elif action == 'delete':
            fixture_server.repository = {p:c for p,c in fixture_server.repository.items() if not p.startswith('app/jobs/acceptance/git_new/')}
            fixture_server.head = 'e' * 40
        elif action == 'reset':
            fixture_server.repository = dict(initial_repository)
            fixture_server.head = 'b' * 40
        else:
            return {}, 400
        import json
        snapshot = gitlab_updates.scan(gitlab_updates.configuration())
        with gitlab_updates.store() as db:
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(snapshot),))
        return {'code':20000, 'data':{}}
app.run(host='127.0.0.1',port=19008,debug=False,threaded=True)
