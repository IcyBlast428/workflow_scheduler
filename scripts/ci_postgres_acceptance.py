"""Run the backend suite with an explicitly disposable CI database."""
import os
import runpy
from pathlib import Path
if os.environ.get('WFS_CI_POSTGRES')!='true' or os.environ.get('PGDATABASE')!='wfstest':
    raise SystemExit('Only the disposable CI database is accepted')
runpy.run_path(str(Path(__file__).with_name('test_backend.py')),run_name='__main__')
