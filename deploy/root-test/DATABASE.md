# GaussDB 平台库

此部署仅面向全新平台。由 DBA 建立独立数据库与账号，默认数据库名 wfsscheduler，schema wfs；通过 Nacos 的 gauss.wfsscheduler.wfs.json（group=gauss）提供连接。

唯一基线是 schema/gauss.sql，共 32 表，包含配置、统计、历史、账户、会话、审计、通知、汇总、发布以及五类命名空间状态表，版本标记 wfs_schema_version=1。

使用 `bash deploy.sh` 时，以下初始化和检查会自动执行；若需手动部署，先生成 runtime.env，配置 Nacos 和 DWS ODBC，然后从项目根目录执行：

```bash
.venv/bin/python scripts/service_config.py --environment-file deploy/root-test/runtime.env --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- .venv/bin/python scripts/init_database.py
.venv/bin/python scripts/service_config.py --environment-file deploy/root-test/runtime.env --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- .venv/bin/python scripts/check_gauss_platform.py
```

空 schema 可由初始化工具创建；非空且没有本版标记的 schema 会被拒绝，无旧数据迁移、兼容建表或自动升级。初始化前停止两项应用服务。目标 GaussDB/DWS 产品和驱动须独立验收事务、主键、表锁、索引与权限。

## DBA 需要提前准备什么

在高斯集群新建独立数据库 `wfsscheduler` 和平台运行账号。可由 DBA 使用具有建库权限的账号执行 `CREATE DATABASE wfsscheduler;`，再按目标版本的权限规则授权；不要在业务数据库里建平台表。平台 schema 默认为 `wfs`，安装工具可以创建它，或由 DBA 提前创建并授权。

运行账号需要连接数据库、使用 schema、平台表的读写与事务/表锁权限；首次安装还需要创建 schema、表、索引的权限。若生产运行账号不允许建表，可由 DBA 在指定库/schema 完整执行 `schema/gauss.sql` 后，安装工具只检查结构。

Nacos 公共命名空间内添加配置，group 为 `gauss`，dataId 为 `gauss.wfsscheduler.wfs.json`，示例（替换占位内容）：

```json
{
  "host": "高斯地址",
  "port": 8000,
  "db": "wfsscheduler",
  "schema": "wfs",
  "user": "平台数据库账号",
  "password": "数据库密码的 Base64 编码"
}
```

Base64 只是编码，不是加密；沿用现有 Nacos 约定，须限制配置访问权限。可以在受信终端用以下命令生成，不把明文密码写进命令历史：

```bash
python3.12 -c 'import base64,getpass; print(base64.b64encode(getpass.getpass("Database password: ").encode()).decode())'
```

默认连接标识 `wfsscheduler_wfs` 表示数据库 `wfsscheduler`、schema `wfs`。更改名称时，Nacos 的 dataId 与 JSON 内容需同时对应。

## 本版平台表清单

以下表全部位于上述平台数据库的 `wfs` schema；任务自身业务表由业务数据库单独管理。

- `wfs_run_history`
- `wfs_schedule_history`
- `wfs_task_config`
- `wfs_job_stats`
- `wfs_auth_sessions`
- `wfs_executions`
- `wfs_config_versions`
- `wfs_config_application`
- `wfs_audit`
- `wfs_users`
- `wfs_login_limits`
- `wfs_run_history_archive`
- `wfs_history_rollup`
- `wfs_run_summary`
- `wfs_run_totals`
- `wfs_notifications`
- `wfs_alert_incidents`
- `wfs_package_tasks`
- `wfs_task_releases`
- `wfs_state_admission_settings`
- `wfs_state_admission_receipts`
- `wfs_state_admission_work_requests`
- `wfs_state_admission_ddl_history`
- `wfs_state_admission_hook_events`
- `wfs_state_connections_profiles`
- `wfs_state_publishing_settings`
- `wfs_state_gitlab_configuration`
- `wfs_state_gitlab_snapshot`
- `wfs_state_gitlab_scan_lease`
- `wfs_state_gitlab_acknowledgements`
- `wfs_state_journal_journal`
- `wfs_schema_version`
