"""Bounded, restartable summary backfill. Does not archive or delete history."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.bootstrap.run_summary import backfill
from app.bootstrap import journal, operations


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size',type=int,default=500)
    parser.add_argument('--max-batches',type=int,default=100)
    parser.add_argument('--import-legacy',action='store_true')
    args=parser.parse_args()
    if not 1<=args.batch_size<=5000 or not 1<=args.max_batches<=10000:
        parser.error('batch-size: 1..5000; max-batches: 1..10000')
    total=0
    for _ in range(args.max_batches):
        count=backfill(args.batch_size)
        total+=count
        if count<args.batch_size:
            break
    if args.import_legacy:
        # Import only while the scheduler is stopped; its exclusive lease is authoritative.
        import fcntl
        directory=operations._directory
        directory.mkdir(parents=True,exist_ok=True)
        with (directory.parent/'.scheduler.lock').open('a') as lease:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            for _ in range(args.max_batches):
                journal.import_legacy(directory,operations.TERMINAL,args.batch_size)
    print('Summary rows processed:',total)
