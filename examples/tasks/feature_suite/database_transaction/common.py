"""读取平台上下文；只在本次输出与此任务数据目录写文件。"""
import datetime as dt
import json
import os
from pathlib import Path

def context():
    params=json.loads(os.environ.get('WFS_PARAMETERS_JSON','{}'))
    day=os.environ.get('WFS_BUSINESS_DATE') or params.get('business_date') or dt.date.today().isoformat()
    day=dt.date.fromisoformat(day).isoformat()
    output=Path(os.environ['WFS_OUTPUT_DIR']);output.mkdir(parents=True,exist_ok=True)
    data=Path(os.environ['WFS_TASK_DATA_DIR']);data.mkdir(parents=True,exist_ok=True)
    return params,day,output,data

def write_json(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
