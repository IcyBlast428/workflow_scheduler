"""仅操作任务专属的 SQLite 演示库，真实业务库请使用 NewDB 连接授权。"""
import sqlite3
from pathlib import Path
from common import context,write_json

def main():
    params,day,output,data=context()
    with sqlite3.connect(data/'demo.sqlite3') as db:
        db.executescript((Path(__file__).parent/'ddl/schema.sql').read_text(encoding='utf-8'))
        with db:
            db.execute('INSERT INTO demo_batch(business_date,status) VALUES(?,?) ON CONFLICT(business_date) DO UPDATE SET status=excluded.status',(day,'done'))
            for identifier,amount in [(1,100),(2,250)]:
                db.execute('INSERT INTO demo_item(business_date,item_id,amount) VALUES(?,?,?) ON CONFLICT(business_date,item_id) DO UPDATE SET amount=excluded.amount',(day,identifier,amount))
            if params.get('simulate_rollback',False):raise RuntimeError('演示异常：事务内的数据修改将回滚。')
        rows=db.execute('SELECT item_id,amount FROM demo_item WHERE business_date=? ORDER BY item_id',(day,)).fetchall()
        write_json(output/'transaction.json',{'business_date':day,'rows':rows})
        print('事务已提交：',day,'行数',len(rows),flush=True)
if __name__=='__main__':main()
