"""Two-table transaction on an explicitly authorized business database."""
from app.common.database import NewDB
from common import context,write_json

def main():
    params,day,output,data=context()
    with NewDB(params.get('connection_id','demo_business')) as db:
        with db.transaction():
            db.execute('DELETE FROM demo_item WHERE business_date=?',(day,))
            db.execute('DELETE FROM demo_batch WHERE business_date=?',(day,))
            db.execute('INSERT INTO demo_batch(business_date,status) VALUES(?,?)',(day,'done'))
            db.executemany('INSERT INTO demo_item(business_date,item_id,amount) VALUES(?,?,?)',[(day,1,100),(day,2,250)])
            if params.get('simulate_rollback',False):raise RuntimeError('Transaction rollback demonstration')
        rows=db.query('SELECT item_id,amount FROM demo_item WHERE business_date=? ORDER BY item_id',(day,))
        write_json(output/'transaction.json',{'business_date':day,'rows':[list(row) for row in rows]})
        print('事务已提交：',day,'行数',len(rows),flush=True)
if __name__=='__main__':main()
