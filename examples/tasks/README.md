# 任务编写示例

任务发布页的示例直接读取这里的源码，避免展示内容与实际文件不一致。每个子目录的 `main.py` 是独立示例入口，不是一个需要整体上传的任务。

- `hello/`：标准库入门，上传 ZIP 根目录的 main.py 即可，无需依赖文件。
- `database_query/`：通过 `NewDB('mysql_orders')` 查询。需要管理员配置业务连接，准备 `orders(id, status)` 表；只有 SELECT 1 的连通性检查不需要业务表。
- `database_transaction/`：演示表 `task_demo_items(id 主键, status)` 上的事务批量更新。先在演示业务库插入 id=1、2 且 status='pending' 的两行。失败时自动回滚，重复运行不会再次更新已完成的两行。
- `file_output/`：CSV 输出到 `WFS_TASK_DATA_DIR`，并发执行使用独立文件名。
- `prepare-dependencies.txt`：在匹配生产 Python/系统/架构的干净联网环境生成完整锁定依赖与 wheels 的步骤说明，不是任务入口。

业务数据库示例需要 SQLAlchemy、configobj、cryptography 和目标数据库驱动，以及这些包的间接依赖。`from app.common.database import NewDB` 不会加载平台专用连接或 Nacos；平台通过 PYTHONPATH 提供 app 源码，任务不要复制 app 目录。GaussDB 的驱动必须按具体产品和版本验证。

最终任务包结构：

```text
main.py
helper.py          # 可选，自定义模块
sql/query.sql      # 可选，按实际代码使用
requirements.txt   # 有第三方依赖时，每行 package==version，包含全部间接依赖
wheels/            # 匹配目标系统与 Python 的 wheel 文件
README.md          # 可选，说明
```

不打包额外外层目录、.venv、.task-build、.git、.env、账号、密码或密钥。纯标准库示例不需要 requirements.txt 与 wheels。输出不写进代码目录；读取包内资源时用 `Path(__file__).resolve().parent` 定位。新版本发布后先手动执行确认，再启用调度；不要在任务内创建另一个定时器。
