# GaussDB 平台库

此部署仅面向全新平台。由 DBA 建立独立数据库与账号，默认数据库名 wfsscheduler，schema wfs；通过 Nacos 的 gauss.wfsscheduler.wfs.json（group=gauss）提供连接。

唯一基线是 schema/gauss.sql，共 32 表，包含配置、统计、历史、账户、会话、审计、通知、汇总、发布以及五类命名空间状态表，版本标记 wfs_schema_version=1。

先生成 runtime.env，配置 Nacos 和 DWS ODBC，然后从项目根目录执行：

```bash
.venv/bin/python scripts/service_config.py --environment-file deploy/root-test/runtime.env --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- .venv/bin/python scripts/init_database.py
.venv/bin/python scripts/service_config.py --environment-file deploy/root-test/runtime.env --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- .venv/bin/python scripts/check_gauss_platform.py
```

空 schema 可由初始化工具创建；非空且没有本版标记的 schema 会被拒绝，无旧数据迁移、兼容建表或自动升级。初始化前停止两项应用服务。目标 GaussDB/DWS 产品和驱动须独立验收事务、主键、表锁、索引与权限。
