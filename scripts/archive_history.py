"""Manual bounded archive job. Preview by default; no production credentials in code."""
import argparse
import datetime as dt
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.bootstrap.database import GaussDB
from app.bootstrap.history import archive_batch


def main():
    parser = argparse.ArgumentParser(description='Archive task history, retaining at least 90 days online.')
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--batch-size', type=int, default=200)
    parser.add_argument('--max-batches', type=int, default=50)
    parser.add_argument('--apply', action='store_true', help='Copy, verify and move source records transactionally.')
    args = parser.parse_args()
    if args.days < 90 or not 1 <= args.batch_size <= 1000 or not 1 <= args.max_batches <= 10000:
        parser.error('days >= 90; batch-size 1..1000; max-batches 1..10000')
    cutoff = dt.datetime.now()-dt.timedelta(days=args.days)
    if not args.apply:
        with GaussDB() as db:
            sample = db.execute_query_sql('SELECT id,end_time FROM wfs_run_history WHERE end_time < ? ORDER BY end_time,id LIMIT ?', params=(cutoff,args.batch_size))
        print(f'Preview only: cutoff={cutoff}; eligible sample={len(sample)} (not a total); no records moved.')
        return
    total = 0
    for _ in range(args.max_batches):
        moved = archive_batch(cutoff, args.batch_size)
        total += moved
        print(f'Committed archive batch={moved}; total={total}', flush=True)
        if moved < args.batch_size:
            break
        time.sleep(0.1)
    print('Complete. Archived records remain queryable by task/date; rerun to continue remaining batches.')


if __name__ == '__main__':
    main()
