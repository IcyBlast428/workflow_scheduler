"""GaussDB archive extraction entry point; database restoration is performed by the DBA."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.restore_platform import restore
if __name__=='__main__':
    import runpy
    from pathlib import Path
    runpy.run_path(str(Path(__file__).with_name('restore_platform.py')),run_name='__main__')
