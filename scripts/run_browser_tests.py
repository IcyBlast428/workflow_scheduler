"""Run isolated browser regression with this interpreter and an available browser."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
environment=dict(os.environ,WFS_BROWSER_PYTHON=sys.executable)
if os.name=='nt' and not environment.get('WFS_BROWSER_EXECUTABLE'):
    edge=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'
    if edge.is_file():environment['WFS_BROWSER_EXECUTABLE']=str(edge)
raise SystemExit(subprocess.call(['npm.cmd' if os.name=='nt' else 'npm','run','test:e2e','--',*sys.argv[1:]],cwd=ROOT/'frontend',env=environment))
