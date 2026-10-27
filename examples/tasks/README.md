# 任务编写示例

「任务示例」页从 catalog.json 和这里的源码生成初始示例，管理员后续编辑独立持久化。每个子目录是独立示例；复制到 GitLab 的 `app/jobs/<分类>/<任务>`，添加稳定任务身份文件并合并到目标分支，再在任务列表审查发布。ZIP 仅用于下载完整示例，平台已移除上传入口。

- `hello/`：标准库入门，将 main.py 放在任务根目录，无需依赖文件。
- `database_query/`：通过 `NewDB('mysql_orders')` 查询。需要管理员配置业务连接，准备 `orders(id, status)` 表；只有 SELECT 1 的连通性检查不需要业务表。
- `database_transaction/`：演示表 `task_demo_items(id 主键, status)` 上的事务批量更新。先在演示业务库插入 id=1、2 且 status='pending' 的两行。失败时自动回滚，重复运行不会再次更新已完成的两行。
- `file_output/`：CSV 输出到 `WFS_TASK_DATA_DIR`，并发执行使用独立文件名。
- `prepare-dependencies.txt`：在匹配生产 Python/系统/架构的干净联网环境生成完整锁定依赖与 wheels 的步骤说明，不是任务入口。
- `nexus-requirements.txt`：Nexus 模式的直接依赖示例，下载或复制为 requirements.txt，随代码上传，不需要附带 wheels。

业务数据库示例需要 SQLAlchemy、configobj、cryptography 和目标数据库驱动，以及这些包的间接依赖。`from app.common.database import NewDB` 不会加载平台专用连接或 Nacos；平台通过 PYTHONPATH 提供 app 源码，任务不要复制 app 目录。GaussDB 的驱动必须按具体产品和版本验证。

最终任务包结构：

```text
main.py
helper.py          # 可选，自定义模块
sql/query.sql      # 可选，按实际代码使用
requirements.txt   # 有第三方依赖时声明；Nexus 模式自动解析间接依赖
wheels/            # 离线模式需要，全部依赖精确锁定并提供 wheel
README.md          # 可选，说明
```

不打包额外外层目录、.venv、.task-build、.git、.env、账号、密码或密钥。纯标准库示例不需要 requirements.txt 与 wheels。输出不写进代码目录；读取包内资源时用 `Path(__file__).resolve().parent` 定位。新版本发布后先手动执行确认，再启用调度；不要在任务内创建另一个定时器。

管理员在任务发布页选择 Nexus 后，平台准备每个版本的独立虚拟环境并安装依赖，依赖环境检查通过才能发布。每次运行只启动该环境中的新子进程，不重复安装。仓库和运行关系详见[任务环境与 Nexus](../../docs/task-environments-and-nexus.md)。
