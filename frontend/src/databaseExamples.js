// Copy-only examples. Credentials are resolved server-side by the connection ID;
// no browser action executes these statements or receives database passwords.
export function databaseExamples({ kind = 'business', connectionId = 'business_db', dialect = 'postgresql' } = {}) {
  if (kind === 'platform') return platformExamples();
  // JSON string syntax is also a valid Python string literal for this ID. Never
  // interpolate the identifier as code, SQL, or a credential-bearing URL.
  const id = JSON.stringify(String(connectionId || 'business_db'));
  const clickhouse = dialect === 'clickhouse';
  const use = (body) => `from app.common.database import NewDB\n\nwith NewDB(${id}) as db:\n${indent(body)}`;
  const note = '仅在隔离的测试业务库运行写入示例，先创建 demo_db_usage 表；重复插入前请更换示例 ID。';
  const create = clickhouse
    ? 'CREATE TABLE IF NOT EXISTS demo_db_usage (id UInt64, status String) ENGINE = MergeTree ORDER BY id'
    : 'CREATE TABLE IF NOT EXISTS demo_db_usage (id INTEGER PRIMARY KEY, status VARCHAR(40))';
  const update = clickhouse
    ? "ALTER TABLE demo_db_usage UPDATE status = :status WHERE id = :id SETTINGS mutations_sync = 1"
    : 'UPDATE demo_db_usage SET status = :status WHERE id = :id';
  const remove = clickhouse
    ? 'ALTER TABLE demo_db_usage DELETE WHERE id = :id SETTINGS mutations_sync = 1'
    : 'DELETE FROM demo_db_usage WHERE id = :id';
  const examples = [
    {
      id: 'setup', title: '准备测试表', description: '一次性准备以下示例使用的独立表，不操作平台系统表。',
      code: use(`db.execute(${JSON.stringify(create)})`), note,
    },
    {
      id: 'query', title: '查询', description: '参数由驱动绑定；as_dict=True 返回字典列表。',
      code: use('rows = db.query(\n    "SELECT id, status FROM demo_db_usage WHERE id = ?",\n    (1,),\n    as_dict=True,\n)\nprint(rows)'),
      note: '值用参数传入，不使用字符串拼接。表名、列名不能作为值参数绑定，动态标识符必须使用白名单。',
    },
    {
      id: 'insert', title: '新增', description: '单条写入成功后自动提交。',
      code: use('affected = db.execute(\n    "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",\n    {"id": 1, "status": "pending"},\n)\nprint(affected)'),
      note: `${note} 返回值是驱动提供的影响行数，个别驱动可能返回 -1，不能把它当作失败。`,
    },
    {
      id: 'update', title: '修改', description: clickhouse ? 'ClickHouse 使用 ALTER TABLE mutation；等待本次 mutation 完成。' : '带条件更新，避免误改整表。',
      code: use(`db.execute(\n    ${JSON.stringify(update)},\n    {"id": 1, "status": "done"},\n)`),
      note: clickhouse ? 'ClickHouse mutation 会重写数据部分，可能耗时；不是普通事务，也无法回滚。mutations_sync=1 等待当前副本完成。' : note,
    },
    {
      id: 'delete', title: '删除', description: clickhouse ? '使用带条件的 ClickHouse 删除 mutation。' : '删除前确认筛选范围；这里仅删除示例记录 3。',
      code: use(`db.execute(\n    ${JSON.stringify(remove)},\n    {"id": 3},\n)`), note,
    },
    {
      id: 'batch', title: '批量写入', description: '使用 executemany，一次提交多行绑定参数。',
      code: use('rows = [\n    {"id": 2, "status": "pending"},\n    {"id": 3, "status": "pending"},\n]\ndb.executemany(\n    "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",\n    rows,\n)'),
      note: clickhouse ? 'ClickHouse 不支持回滚。大批量数据请分批处理，具体批次大小按行宽和生产监测调整。' : '大批量数据请分批处理；同一个显式 transaction() 中的多批写入会统一提交或回滚。',
    },
  ];
  if (!clickhouse) examples.push({
    id: 'transaction', title: '事务', description: '整段成功才提交，任意语句抛错则自动回滚。',
    code: use('with db.transaction():\n    db.execute(\n        "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n        ("processing", 1),\n    )\n    db.execute(\n        "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n        ("processing", 2),\n    )'),
    note: 'MySQL 表须使用支持事务的存储引擎。不要在事务内部吞掉异常，也不要在同步事务中调用 async_* 方法。DDL 的提交行为由具体数据库决定。',
  });
  examples.push({
    id: 'async', title: '异步读写', description: '独占线程完成每次数据库操作，等待 SQL 时不阻塞事件循环。',
    code: `import asyncio\nfrom app.common.database import NewDB\n\nasync def main():\n    async with NewDB(${id}) as db:\n        await db.async_execute(\n            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",\n            (101, "pending"),\n        )\n        await db.async_executemany(\n            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",\n            [(102, "pending"), (103, "pending")],\n        )\n        rows = await db.async_query(\n            "SELECT id, status FROM demo_db_usage WHERE id = ?",\n            (101,),\n            as_dict=True,\n        )\n        print(rows)\n\nif __name__ == "__main__":\n    asyncio.run(main())`,
    note: '每进程最多 4 个 SQL 工作线程、16 个待完成操作（含运行中），超额提交会报错。连接池限额仍生效；取消 await 不保证取消 SQL 或回滚，不能据此自动重试写入。已有事件循环中直接 await main()。',
  });
  if (!clickhouse) examples.push({
    id: 'async-transaction', title: '异步事务', description: '同步回调中的整段事务在同一个线程、同一连接执行。',
    code: `import asyncio\nfrom app.common.database import NewDB\n\ndef update_batch(tx):\n    # tx 是工作线程独占的 NewDB，回调中不能使用 await。\n    tx.execute(\n        "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n        ("done", 101),\n    )\n    tx.execute(\n        "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n        ("done", 102),\n    )\n    return tx.query(\n        "SELECT id, status FROM demo_db_usage WHERE id IN (?, ?)",\n        (101, 102),\n        as_dict=True,\n    )\n\nasync def main():\n    async with NewDB(${id}) as db:\n        rows = await db.async_transaction(update_batch)\n        print(rows)\n\nif __name__ == "__main__":\n    asyncio.run(main())`,
    note: '回调正常返回才提交，异常自动回滚。不要捕获外部 db 在回调中使用，不要返回连接或游标。运行中的回调即使 await 被取消，仍会继续执行并最终释放连接。',
  });
  return examples;
}

function indent(source) {
  return source.split('\n').map((line) => line ? `    ${line}` : '').join('\n');
}

function platformExamples() {
  const note = '仅供平台内部开发与维护。任务代码必须使用获得授权的 NewDB 业务连接，不得使用 GaussDB 访问平台库。写入示例请在隔离测试环境运行。';
  const use = (body) => `from app.bootstrap.database import GaussDB\n\nwith GaussDB() as db:\n${indent(body)}`;
  return [
    {
      id: 'setup', title: '准备测试表', description: '使用独立示例表，不修改任何 wfs_* 平台系统表。',
      code: use('db.execute_sql(\n    "CREATE TABLE IF NOT EXISTS demo_db_usage (id INTEGER PRIMARY KEY, status VARCHAR(40))"\n)'), note,
    },
    {
      id: 'query', title: '查询', description: 'return_json=True 返回字典列表，否则返回元组列表。',
      code: use('rows = db.execute_query_sql(\n    "SELECT id, status FROM demo_db_usage WHERE id = ?",\n    params=(1,),\n    return_json=True,\n)\nprint(rows)'), note,
    },
    {
      id: 'insert', title: '新增', description: '平台连接默认自动提交；execute_sql 不返回影响行数。',
      code: use('db.execute_sql(\n    "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",\n    params=(1, "pending"),\n)'), note,
    },
    {
      id: 'update', title: '修改', description: '通过参数绑定传递值，并明确更新条件。',
      code: use('db.execute_sql(\n    "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n    params=("done", 1),\n)'), note,
    },
    {
      id: 'delete', title: '删除', description: '先核对记录范围，再执行带条件的删除。',
      code: use('db.execute_sql("DELETE FROM demo_db_usage WHERE id = ?", params=(3,))'), note,
    },
    {
      id: 'batch', title: '同一事务多行写入', description: '平台内部接口没有 executemany；少量多行写入可在同一事务循环处理。',
      code: use('db.begin_transaction()\ntry:\n    for row in [(2, "pending"), (3, "pending")]:\n        db.execute_sql(\n            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",\n            params=row,\n        )\n    db.set_commit()\nexcept BaseException:\n    db.set_rollback()\n    raise'), note,
    },
    {
      id: 'transaction', title: '事务', description: '显式开始事务，成功提交，异常回滚。',
      code: use('db.begin_transaction()\ntry:\n    db.execute_sql(\n        "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n        params=("processing", 1),\n    )\n    db.execute_sql(\n        "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n        params=("processing", 2),\n    )\n    db.set_commit()\nexcept BaseException:\n    db.set_rollback()\n    raise'), note,
    },
    {
      id: 'async', title: '异步调用', description: '将连接创建、整段事务和关闭都放到同一个工作线程。',
      code: 'import asyncio\nfrom app.bootstrap.database import GaussDB\n\ndef update_and_read():\n    # 在工作线程中创建及关闭句柄，不传入外部连接。\n    with GaussDB() as db:\n        db.begin_transaction()\n        try:\n            db.execute_sql(\n                "UPDATE demo_db_usage SET status = ? WHERE id = ?",\n                params=("done", 1),\n            )\n            rows = db.execute_query_sql(\n                "SELECT id, status FROM demo_db_usage WHERE id = ?",\n                params=(1,),\n                return_json=True,\n            )\n            db.set_commit()\n            return rows\n        except BaseException:\n            db.set_rollback()\n            raise\n\nasync def main():\n    rows = await asyncio.to_thread(update_and_read)\n    print(rows)\n\nif __name__ == "__main__":\n    asyncio.run(main())',
      note: `${note} 这是同步驱动的线程卸载，并非原生异步驱动。取消 await 不会中止已开始的 SQL；批量异步调用请限制并发，避免占满平台连接池。`,
    },
  ];
}
