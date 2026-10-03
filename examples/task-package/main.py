"""Small multi-file package example: no network or third-party dependencies."""
import os
from pathlib import Path
from helpers import report_message

if __name__ == '__main__':
    data = Path(os.environ['WFS_TASK_DATA_DIR'])
    text = report_message()
    (data / 'last-result.txt').write_text(text, encoding='utf-8')
    print(text, flush=True)
