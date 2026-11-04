"""Read-only local readiness check using the deployed GaussDB configuration."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.accept_target import check
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:18008')
    args=parser.parse_args()
    print(json.dumps(check(args.url,database=True),ensure_ascii=False,indent=2))
