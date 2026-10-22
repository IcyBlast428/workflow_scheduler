"""先在管理员的任务业务数据库中保存 mysql_orders，再准备数据库依赖。"""
from app.common.database import NewDB


def main():
    # 只传连接标识；地址、密码和数据库类型均由管理员配置。
    with NewDB('mysql_orders') as db:
        print(db.query('SELECT 1 AS connection_ok', as_dict=True), flush=True)

        # 按实际表结构调整 SQL；参数单独传递，不要拼接到 SQL 中。
        orders = db.query(
            'SELECT id, status FROM orders WHERE status = :status ORDER BY id LIMIT 20',
            {'status': 'pending'},
            as_dict=True,
        )
        print(f"本批待处理订单：{len(orders)} 条", flush=True)
    # 离开 with 自动归还连接；不要输出账号、密码或整批业务数据。


if __name__ == '__main__':
    main()
