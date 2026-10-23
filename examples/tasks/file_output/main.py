"""每次执行的 CSV、JSON 和日志写入 WFS_OUTPUT_DIR，可在线查看与下载。"""
import csv
import os
from pathlib import Path
import json


def main():
    output_dir = Path(os.environ['WFS_OUTPUT_DIR'])
    output_dir.mkdir(parents=True, exist_ok=True)
    # 每个执行编号有独立目录，可以使用稳定文件名。
    output = output_dir / 'report.csv'
    with output.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['名称', '数量'])
        writer.writerow(['示例', 100])
    summary = {'run_id': os.environ['WFS_RUN_ID'], 'total': 100}
    (output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / 'report.log').write_text('报表生成成功\n', encoding='utf-8')
    print(f"报表已生成：{output.name}", flush=True)


if __name__ == '__main__':
    main()
