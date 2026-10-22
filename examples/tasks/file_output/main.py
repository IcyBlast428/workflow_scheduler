"""发布后的代码目录只读；输出写入平台提供的任务数据目录。"""
import csv
import os
from pathlib import Path
from uuid import uuid4


def main():
    output_dir = Path(os.environ['WFS_TASK_DATA_DIR'])
    output_dir.mkdir(parents=True, exist_ok=True)
    # 同一任务可以并发运行，使用独立文件名避免互相覆盖。
    output = output_dir / f'report-{uuid4().hex}.csv'
    with output.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['名称', '数量'])
        writer.writerow(['示例', 100])
    print(f"报表已生成：{output.name}", flush=True)


if __name__ == '__main__':
    main()
