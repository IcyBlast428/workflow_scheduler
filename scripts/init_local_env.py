"""Prepare isolated local database test configuration, without importing existing platform data."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.local_postgres import configuration
if __name__=='__main__':
    configuration()
    print('Fresh test configuration ready under data/gauss-dev')
