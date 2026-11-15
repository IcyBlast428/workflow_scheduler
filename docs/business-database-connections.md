# 统一业务数据库连接

平台数据库和业务数据库分别管理。平台数据库保存账户、调度、队列和执行元数据；业务数据库由任务通过连接标识访问。两者即使部署在同一台机器上，也应使用独立账号和权限。

## 平台连接与权限

在「左下角管理员菜单 → 平台设置 → 连接与依赖 → 数据库连接 → 平台数据库」选择「自定义连接」，即可在页面编辑地址、端口、库名、Schema、账号、密码、ODBC 驱动及连接池参数。只有内置管理员（`WFS_ADMIN_USERNAME`，默认 `admin`）可以测试和保存；其他管理员只读，非管理员不能访问。直接配置的业务连接管理继续沿用原有管理员权限；Nacos 来源的预览、测试和修改仅允许内置管理员。

平台连接保存前检查目标库结构，成功后加密保存为待生效配置，完整重启平台服务后生效。保存配置不会迁移已有数据，更换目标库前须先完成数据迁移和备份。平台连接不作为任务的业务连接开放。

Nacos 2.x 支持每库一份 JSON，在页面读取与版本校验回写，详见 [Nacos 配置管理](nacos-connections.md)。完整 CRUD、事务和异步示例见 [数据库使用说明](database-usage.md)。业务 `NewDB` 的可复制示例已集中到「左下角管理员菜单 → 任务示例与文档 → 任务中的统一用法」；平台内部 `GaussDB` 示例仍保留在「平台设置 → 连接与依赖 → 数据库连接 → 平台数据库」中。示例页面不会执行 SQL。

## 管理员配置

1. 在「左下角管理员菜单 → 平台设置 → 连接与依赖 → 数据库连接 → 业务数据库」新增连接，选择数据库类型，填写地址、端口、数据库名称和账号。
2. 对 GaussDB/DWS 填写 Web 和任务服务器上已经安装的 ODBC 驱动名称。页面分别显示 Python 驱动与系统驱动状态；页面不会自动安装软件或上传运行任意驱动代码。
3. 测试连接并保存。密码加密存储，读取接口不返回原文；编辑时密码留空表示保留。
4. 在任务的「连接授权」中选择允许访问的连接标识。保存后下一次任务执行使用新的配置；已经运行的任务使用启动时冻结的配置。

停用、归档和删除沿用原有使用关系检查。删除前必须停用、解除任务授权/声明/测试映射，并输入连接标识。编辑连接名称不会改变代码使用的标识。

## 数据库类型

| 类型 | Python 驱动 | 额外准备 | 事务 |
| --- | --- | --- | --- |
| MySQL / PolarDB / MariaDB | PyMySQL | 与具体产品兼容的 SQL | 支持 |
| PostgreSQL | psycopg | PostgreSQL 协议与版本验证 | 支持 |
| GaussDB / DWS | pyodbc | 厂商 ODBC 驱动，默认名称 DWS | 支持普通文本 SQL 事务；不提供 ORM/模式反射 |
| ClickHouse | clickhouse-connect | 与服务端兼容的 HTTP/HTTPS 端口 | 不支持本接口事务回滚 |

SQL 方言仍由实际数据库决定。NewDB 统一连接管理、参数传递和事务入口，不会把任意 MySQL SQL 自动转换为 PostgreSQL SQL。

同一种类型的新数据库，只需在页面新增连接。增加当前目录以外的**新数据库引擎类型**，需要先加入经过验证的后端适配器和驱动，再由页面配置实例；不能靠填写任意 Python 模块或 URL 直接执行代码。

TLS 选项随类型显示：MySQL、PostgreSQL 和 ClickHouse 的证书校验模式需要各运行环境可读取的 CA 文件。DWS ODBC 的主机名校验能力受具体厂商版本限制，当前仅提供关闭 TLS 或仅加密，不能把后者视为已校验证书。

## 任务代码

```python
from app.common.database import NewDB

with NewDB("reports") as db:
    rows = db.query(
        "SELECT order_id, amount FROM orders WHERE business_date = ?",
        ("2026-11-15",),
        as_dict=True,
    )
    with db.transaction():
        db.execute("UPDATE audit SET processed = ? WHERE id = ?", (1, 10))
        db.executemany(
            "INSERT INTO result(id, amount) VALUES (:id, :amount)",
            [{"id": row["order_id"], "amount": row["amount"]} for row in rows],
        )
```

`query` 返回结果，`execute` 返回影响行数，`executemany` 批量执行，`transaction` 在异常时回滚。使用参数绑定，不拼接业务值。旧的 `execute_query_sql`、`execute_single_sql` 等方法继续兼容。一个 NewDB 实例不能跨线程或进程使用，多线程任务应在各线程分别创建实例。

### 发布规范

新的上传、环境准备和正常发布会检查任务 Python 文件。直接导入原生数据库驱动、直接创建 SQLAlchemy 引擎或访问平台 `GaussDB` 会被拒绝，并显示文件、行号和 NewDB 迁移提示。依赖清单仍可以声明目标数据库驱动，因为 NewDB 内部需要它。

已发布版本和历史回滚保留兼容。重新发布旧代码时应迁移到 NewDB。需要新增适配器的任务还应重新准备环境和 SDK 快照，已冻结的旧 SDK 不会自动变化。

该检查是可信任务代码的维护规范，不是安全沙箱：动态导入、第三方库内部行为或任意网络客户端仍需要代码审核；运行不可信代码还需要操作系统和网络隔离。

## 连接池

新连接默认常驻上限 1、临时额外上限 1、回收 600 秒、等待 10 秒；既有连接保留原参数。串行任务从这个小池开始；需要同时持有多个连接的任务，应按实际并发扩大。

连接按需创建，池大小不是预先创建的连接数。每次执行是独立任务进程，连接池只能复用这次执行内部的连接，不能跨执行、跨进程共用。总连接预算需要累加所有活跃任务、平台和其他应用。

管理接口的 `business_pools` 仅描述处理本次请求的 Web 进程中的池，包含使用中/空闲数量、创建数、等待耗时和超时计数；`business_pool_scope=current_web_process`。没有条目不表示所有任务都没有连接，不能用它替代数据库端全局连接监控。

## 验证边界

仓库测试覆盖 PostgreSQL 的真实连接复用、并发、超时、参数、事务与授权，以及各驱动的 URL/TLS 参数契约和发布规范。GaussDB/DWS、ClickHouse 的真实连接、事务和查询性能仍应使用目标服务端和系统驱动验收，页面「测试连接」也只验证连接与版本查询，不代表业务 SQL 全部兼容。

适配器依据：[SQLAlchemy 连接池](https://docs.sqlalchemy.org/en/20/core/pooling.html)、[DWS ODBC 数据源参数](https://support.huaweicloud.com/intl/en-us/devg-dws/dws_04_0119.html)。
