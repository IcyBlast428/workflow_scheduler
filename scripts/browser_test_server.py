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
from app import create_app
from app.bootstrap.core import aps_start
from app.bootstrap.schedule_config import save_schedule
from app.extensions import scheduler
app = create_app()
if scheduler.get_job('MAIN_TASK_JOB'):
    scheduler.remove_job('MAIN_TASK_JOB')
save_schedule('acceptance__slow',{'schedule_type':'every_hour','main_file':'main.py','enabled':False})
aps_start()
app.run(host='127.0.0.1',port=19008,debug=False,threaded=True)
