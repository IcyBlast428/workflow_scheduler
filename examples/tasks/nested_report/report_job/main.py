import csv
import json
import os
from pathlib import Path
from .helpers import total


def main():
    root = Path(os.environ['WFS_TASK_ROOT'])
    rows = json.loads((root / 'resources' / 'input.json').read_text(encoding='utf-8'))
    output = Path(os.environ['WFS_OUTPUT_DIR']) / 'reports'
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'details.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['name', 'amount'])
        writer.writeheader()
        writer.writerows(rows)
    summary = {'total': total(rows), 'rows': len(rows), 'run_id': os.environ['WFS_RUN_ID']}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'report.log').write_text('test_job2：多层目录任务执行成功\n', encoding='utf-8')
    print(f"test_job2：共 {len(rows)} 行，合计 {summary['total']}，输出已保存。", flush=True)


if __name__ == '__main__':
    main()
