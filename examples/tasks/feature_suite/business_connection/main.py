"""需先配置业务测试连接 demo_business；不在代码中保存密码。"""
import json
import os
from pathlib import Path
from app.common.database import NewDB

def main():
    params=json.loads(os.environ.get('WFS_PARAMETERS_JSON','{}'))
    key=params.get('connection','demo_business')
    # 此模板只读取示例表，DDL 需由业务测试库管理员事先执行。
    with NewDB(key) as db:
        rows=db.query('SELECT business_date,total FROM demo_task_metrics WHERE business_date = :day',{'day':os.environ.get('WFS_BUSINESS_DATE') or params.get('business_date','2026-01-05')},as_dict=True)
    (Path(os.environ['WFS_OUTPUT_DIR'])/'query.json').write_text(json.dumps(rows,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    print('查询结果行数：',len(rows),flush=True)
if __name__=='__main__':main()
