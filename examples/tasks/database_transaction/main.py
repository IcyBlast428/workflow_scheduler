"""演示用表 task_demo_items(id 主键, status) 需由管理员预先创建。"""
from app.common.database import NewDB


def main():
    # 适用于 MySQL、PostgreSQL 兼容库和 SQLite；ClickHouse 不支持此事务入口。
    with NewDB('mysql_orders') as db:
        with db.transaction():
            count = db.executemany(
                'UPDATE task_demo_items SET status = :done WHERE id = :id AND status = :pending',
                [
                    {'id': 1, 'done': 'done', 'pending': 'pending'},
                    {'id': 2, 'done': 'done', 'pending': 'pending'},
                ],
            )
        # 正常离开事务才提交；任何异常都会回滚整批，不要吞掉异常。
        print(f"已提交，本批影响行数：{count}", flush=True)
    # WHERE status = 'pending' 避免重复处理已完成记录。


if __name__ == '__main__':
    main()
