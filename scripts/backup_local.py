"""GaussDB platform backup entry point. See backup_platform.py for arguments."""
import runpy
from pathlib import Path
if __name__=='__main__':runpy.run_path(str(Path(__file__).with_name('backup_platform.py')),run_name='__main__')
