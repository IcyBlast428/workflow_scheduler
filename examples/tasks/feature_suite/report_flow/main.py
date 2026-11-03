"""多文件流程、参数、静态资源、异常分支与 CSV/JSON 输出。"""
import csv
import json
from pathlib import Path
from common import context,write_json
from transform import summarize

def main():
    params,day,output,data=context()
    rows=json.loads((Path(__file__).parent/'resources/orders.json').read_text(encoding='utf-8'))
    selected=summarize(rows,str(params.get('region','CN')))
    with (output/'report.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=['id','region','amount']);writer.writeheader();writer.writerows(selected)
    result={'business_date':day,'region':params.get('region','CN'),'count':len(selected),'amount':sum(row['amount'] for row in selected)}
    write_json(output/'summary.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
