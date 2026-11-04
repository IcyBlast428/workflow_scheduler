# 验证范围

本版按全新 GaussDB/DWS 设计，没有生产数据库账户，也未连接目标内网 GaussDB。开发和 CI 使用独立 PostgreSQL 实库，覆盖参数绑定、事务回滚、CAS、去重、并发汇总、排队、发布、权限、DDL/标签、恢复文件和前端交互。包含直接执行 GaussDB SQL 分支的并发测试；仍不能代替目标 DWS ODBC 与集群验收。

后端运行 python scripts/test_backend.py，浏览器运行 python scripts/run_browser_tests.py。测试每次建立独立 schema，无文件数据库模拟。当前结果见 docs/fresh-gauss-audit.md。

现场验收：核对产品和驱动版本；用空 schema 初始化 32 表；检查两项 systemd 服务与单调度实例；配置业务库、GitLab、私有 PyPI；审查发布低风险任务并验证日志与输出；测试事务、锁等待、断库恢复、超时和重启；在新库演练原生备份恢复并核对外部业务结果。结果不确定的任务不自动重放。
