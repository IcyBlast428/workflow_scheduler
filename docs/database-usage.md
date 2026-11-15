# 数据库连接与代码用法

业务任务一律通过 `from app.common.database import NewDB` 获取平台授权的业务连接。任务只填写连接标识，例如 `orders`；地址、账号、密码、连接池以及 Nacos 配置由平台管理。未授权或禁用的连接会拒绝使用，没有旧配置文件或直连驱动的自动回退。

平台内部状态数据库继续使用 GaussDB/DWS，由 `GaussDB` 管理。本文件末尾的 `GaussDB` 示例仅供平台内部开发和维护，不是任务接入平台数据库的入口。不要在业务任务中导入平台库或自行创建驱动连接。

业务 `NewDB` 的可复制示例位于「左下角管理员菜单 → 任务示例与文档 → 任务中的统一用法」，包含增删改查、批量、事务和异步调用。平台内部 `GaussDB` 示例仍位于「左下角管理员菜单 → 平台设置 → 连接与依赖 → 数据库连接 → 平台数据库 → 平台数据库开发示例」。

两处示例页面都只提供查看与复制，不执行 SQL。以下写入示例请只在隔离测试库运行，先创建测试表；不要直接修改生产表或 `wfs_*` 系统表。

## 业务连接：同步增删改查

在平台新增并测试连接，再将其授权给任务。示例将连接标识写为 `orders`，请替换成该任务实际获准使用的标识。若配置来源为 Nacos，仍然使用相同标识，不在任务代码中保存 Nacos 凭据。

MySQL、PostgreSQL、GaussDB/DWS 可在测试库准备一张表：

```python
from app.common.database import NewDB

with NewDB("orders") as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS demo_db_usage (
            id INTEGER PRIMARY KEY,
            status VARCHAR(40)
        )
    """)
```

`with NewDB(...)` 管理连接生命周期，不代表多条 SQL 自动成为同一个事务。单次写入默认提交；如果需要多条语句一起提交，应显式使用 `transaction()`。

```python
from app.common.database import NewDB

with NewDB("orders") as db:
    # 新增：命名参数由驱动绑定，不通过字符串拼接值。
    affected = db.execute(
        "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",
        {"id": 1, "status": "pending"},
    )

    # 查询：也支持 ? 和元组参数。as_dict=False 时返回元组列表。
    rows = db.query(
        "SELECT id, status FROM demo_db_usage WHERE id = ?",
        (1,),
        as_dict=True,
    )
    print(rows)  # [{"id": 1, "status": "pending"}]

    # 修改：始终检查 WHERE 条件。
    db.execute(
        "UPDATE demo_db_usage SET status = :status WHERE id = :id",
        {"id": 1, "status": "done"},
    )

    # 删除：先核对目标记录范围。
    db.execute("DELETE FROM demo_db_usage WHERE id = ?", (1,))
```

`query()` 返回已读取的数据，可以在上下文退出后继续使用。`execute()`、`executemany()` 返回驱动的影响行数，某些驱动返回 `-1` 表示无法给出准确数值，不代表执行失败。发生失败时通过异常报告。参数只能绑定值，不能把表名、列名当作值绑定；动态标识符必须经过白名单校验。

统一接口不翻译数据库方言；函数、分页、类型、DDL、ClickHouse mutation 等语法仍以目标数据库为准。重复运行新增示例前，请更换记录 ID 或清理测试记录。

## 批量写入与事务

```python
from app.common.database import NewDB

with NewDB("orders") as db:
    # 支持字典列表，也支持与 ? 配套的元组列表。空列表直接返回 0。
    db.executemany(
        "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",
        [{"id": 10, "status": "pending"}, {"id": 11, "status": "pending"}],
    )

    # 正常结束统一提交；任何语句抛异常，整段自动回滚。
    with db.transaction():
        db.execute(
            "UPDATE demo_db_usage SET status = ? WHERE id = ?",
            ("done", 10),
        )
        db.execute(
            "UPDATE demo_db_usage SET status = ? WHERE id = ?",
            ("done", 11),
        )
```

不要在事务内部吞掉异常后正常退出，否则上下文会按成功路径提交。无需手动提交或回滚；不支持嵌套事务。MySQL 需要支持事务的存储引擎；DDL 隐式提交等行为以数据库自身为准。大批数据应分批处理，批次大小根据行宽、运行时间和数据库负载监测调整。

连接池在同一个任务进程内复用；不同任务进程的池相互独立。`close()` 或上下文退出会归还连接并回滚未提交工作，不会销毁整个池。不要让一个同步句柄跨线程或跨进程使用。

## 异步查询、写入和事务

已发布任务使用发布时冻结的 SDK。需要使用本次新增的异步接口时，请重新准备任务环境并发布包含新版 SDK 的版本；仅重启平台不会改写旧版本快照。

四类业务连接统一使用同步驱动。`async_*` 将数据库操作放到工作线程，等待 SQL 时不阻塞事件循环；它不是原生异步驱动或 SQLAlchemy `AsyncEngine`。

每次异步操作都在工作线程中创建、使用、关闭独立句柄，使用当前 `NewDB` 已获得授权的配置快照，不把外部同步连接传到其他线程，不在每次操作时重新读取 Nacos。需要采用更新后的配置时，应新建 `NewDB` 句柄；任务的运行时连接授权仍按任务启动时的快照处理。

```python
import asyncio
from app.common.database import NewDB

async def main():
    async with NewDB("orders") as db:
        await db.async_execute(
            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
            (101, "pending"),
        )
        await db.async_executemany(
            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
            [(102, "pending"), (103, "pending")],
        )
        rows = await db.async_query(
            "SELECT id, status FROM demo_db_usage WHERE id = ?",
            (101,),
            as_dict=True,
        )
        print(rows)

if __name__ == "__main__":
    asyncio.run(main())
```

已有事件循环的调用方应直接 `await main()`，不要再次调用 `asyncio.run()`。`NewDB(...)` 本身仍同步解析连接配置；异步能力覆盖 SQL 操作，不把同步构造函数变成异步配置客户端。

多条独立的 `await db.async_execute(...)` 各自提交，不属于同一事务。要保证原子性，用 `async_transaction(work)`；`work` 必须是同步函数，接收工作线程独占的 `NewDB`，在函数内使用同步方法：

```python
import asyncio
from app.common.database import NewDB

def finish_batch(tx):
    tx.execute(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        ("done", 101),
    )
    tx.execute(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        ("done", 102),
    )
    return tx.query(
        "SELECT id, status FROM demo_db_usage WHERE id IN (?, ?)",
        (101, 102),
        as_dict=True,
    )

async def main():
    async with NewDB("orders") as db:
        rows = await db.async_transaction(finish_batch)
        print(rows)

if __name__ == "__main__":
    asyncio.run(main())
```

回调正常返回则提交，异常则回滚。不要捕获外层 `db` 在回调中使用，不要把回调定义成 `async def`，也不要返回连接、游标或待等待对象。在同步 `transaction()` 内调用 `async_*` 会明确拒绝，避免误以为工作线程的语句加入了外部事务。

### 并发与取消

- 每进程最多 4 个异步 SQL 工作线程、16 个待完成操作，后者包含正在运行的操作。超出预算会抛出 `AsyncDatabaseBusyError`（`RuntimeError` 子类），不会无限排队。实际并行连接数仍受每个连接的连接池限制。
- 需要批量异步访问时，调用方应限制同时提交数量，例如使用 `asyncio.Semaphore(2)`，根据业务库负载逐步调整。不要为每行数据创建一个不受限的异步任务。
- `asyncio` 超时或取消等待不等于数据库取消或事务回滚。已开始的 SQL/事务可能继续运行和提交，工作线程最终仍会归还连接；尚未开始的排队操作可能被取消。不要根据等待超时直接重试写入，应使用业务唯一键/幂等标识查询结果后再决定。
- `async_close()` 只关闭当前线程的同步句柄；工作线程各自负责关闭。它不会取消或等待所有尚未完成的 SQL。正常代码应先等待自己创建的所有操作，再退出上下文。
- 不自动重试写入；断线和执行错误直接传播给调用方。

已经发布的任务可能使用冻结的公共 SDK；要在这些任务中使用新增异步接口，需要重新准备并发布包含当前 SDK 的任务版本。

旧异步名字仍可使用：`async_insert_many` 对应 `async_executemany`，`async_execute_single_sql` 对应 `async_execute`，`async_query_sql` 对应 `async_query`，`async_query_sql_return_json` 返回字典列表。查询及单条写入都支持 `params`；`get_async_engine()` 明确不提供原生异步引擎，请使用上述方法。

## ClickHouse 差异

ClickHouse 可以使用同步/异步查询及写入，但不支持此接口的事务回滚；`transaction()`、`async_transaction()` 会拒绝执行，不能用它们假装获得原子性。

```python
from app.common.database import NewDB

with NewDB("clickhouse_reports") as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS demo_db_usage (
            id UInt64, status String
        ) ENGINE = MergeTree ORDER BY id
    """)
    db.execute(
        "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",
        {"id": 1, "status": "pending"},
    )
    db.execute(
        "ALTER TABLE demo_db_usage UPDATE status = :status WHERE id = :id SETTINGS mutations_sync = 1",
        {"id": 1, "status": "done"},
    )
    db.execute(
        "ALTER TABLE demo_db_usage DELETE WHERE id = :id SETTINGS mutations_sync = 1",
        {"id": 1},
    )
```

修改与删除使用 mutation，可能重写数据部分并耗时；`mutations_sync=1` 等待当前副本完成，不代表所有副本完成，也不提供事务回滚。优先根据实际分析型负载设计追加写入和分区治理。

## 平台内部连接：GaussDB

仅供平台维护代码使用。平台仍是 GaussDB/DWS 类型，连接地址、账号、池及配置来源由管理员管理；业务任务不能通过这一类取得平台数据权限。

```python
from app.bootstrap.database import GaussDB

with GaussDB() as db:
    # 以下表只允许在隔离的测试平台库创建和使用。
    db.execute_sql("""
        CREATE TABLE IF NOT EXISTS demo_db_usage (
            id INTEGER PRIMARY KEY, status VARCHAR(40)
        )
    """)
    db.execute_sql(
        "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
        params=(1, "pending"),
    )
    rows = db.execute_query_sql(
        "SELECT id, status FROM demo_db_usage WHERE id = ?",
        params=(1,),
        return_json=True,
    )
    db.execute_sql(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        params=("done", 1),
    )
    db.execute_sql("DELETE FROM demo_db_usage WHERE id = ?", params=(1,))
```

`execute_query_sql` 默认返回元组列表，`return_json=True` 返回字典列表；`execute_sql` 不返回影响行数。默认自动提交；多条写入需显式事务：

```python
from app.bootstrap.database import GaussDB

with GaussDB() as db:
    db.begin_transaction()
    try:
        # 平台内部接口没有 executemany，这里对少量记录在同一事务循环。
        for row in [(2, "pending"), (3, "pending")]:
            db.execute_sql(
                "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
                params=row,
            )
        db.set_commit()
    except BaseException:
        db.set_rollback()
        raise
```

平台内部异步调用把整个连接生命周期和事务放到 `asyncio.to_thread` 的同一个同步回调，绝不能在外层创建连接、逐条交给不同线程：

```python
import asyncio
from app.bootstrap.database import GaussDB

def update_and_read():
    with GaussDB() as db:
        db.begin_transaction()
        try:
            db.execute_sql(
                "UPDATE demo_db_usage SET status = ? WHERE id = ?",
                params=("done", 2),
            )
            rows = db.execute_query_sql(
                "SELECT id, status FROM demo_db_usage WHERE id = ?",
                params=(2,),
                return_json=True,
            )
            db.set_commit()
            return rows
        except BaseException:
            db.set_rollback()
            raise

async def main():
    print(await asyncio.to_thread(update_and_read))

if __name__ == "__main__":
    asyncio.run(main())
```

这是同步驱动线程卸载。批量调用需自行限制并发，以免占满平台连接池；取消等待同样不会终止已经开始的 SQL。平台连接变更的生效方式以管理页面提示为准，不应通过长时间保留旧句柄来绕过重新加载。
