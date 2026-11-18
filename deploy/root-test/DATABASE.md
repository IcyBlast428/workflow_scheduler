# GaussDB 平台库

此部署仅面向全新平台。由 DBA 确认数据库和专用平台账号，首次安装默认数据库名 immpdb，schema wfs；通过 Nacos 的 gauss.immpdb.wfs.json（group=gauss）提供连接。

唯一基线是 schema/gauss.sql，共 32 表，包含配置、统计、历史、账户、会话、审计、通知、汇总、发布以及五类命名空间状态表，版本标记 wfs_schema_version=1。

使用 `bash deploy.sh` 时，以下初始化和检查会自动执行；若需手动部署，先生成 runtime.env，配置 Nacos 和 DWS ODBC，然后从项目根目录执行：

```bash
.venv/bin/python scripts/service_config.py --environment-file deploy/root-test/runtime.env --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- .venv/bin/python scripts/init_database.py
.venv/bin/python scripts/service_config.py --environment-file deploy/root-test/runtime.env --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- .venv/bin/python scripts/check_gauss_platform.py
```

空 schema 可由初始化工具创建；非空且没有本版标记的 schema 会被拒绝，不导入或清空旧数据。已有本版标记时保留数据并校验，初始化可修正已知可空执行字段；全新基线已包含这些定义，无需额外运行升级或修复 SQL。初始化前停止 wfs.service。目标 GaussDB/DWS 产品和驱动须独立验收事务、主键、表锁、索引与权限。

## DBA 需要提前准备什么

由 DBA 确认数据库 `immpdb` 和平台运行账号。仅当数据库不存在时新建；数据库已存在时使用其中专用空 schema `wfs`，不修改其他 schema。平台表不能与业务表混放于同一 schema。平台 schema 默认为 `wfs`，安装工具可以创建它，或由 DBA 提前创建并授权。

运行账号需要连接数据库、使用 schema、平台表的读写与事务/表锁权限；首次安装还需要创建 schema、表、索引的权限。若生产运行账号不允许建表，可由 DBA 在 `immpdb` 中完整执行 `schema/gauss.sql`（包含建 schema 和版本标记），并授予运行账号需要的权限。该文件默认创建 `wfs`；若 schema 已由 DBA 建好，只跳过 `CREATE SCHEMA wfs`，其余语句按顺序执行。自定义 schema 时相应调整建 schema/search_path 和 Nacos 配置。基线结构一致时，安装器不会重复建表或改动已有记录。

Nacos 公共命名空间内添加配置，group 为 `gauss`，dataId 为 `gauss.immpdb.wfs.json`，示例（替换占位内容）：

```json
{
  "host": "高斯地址",
  "port": 8000,
  "db": "immpdb",
  "schema": "wfs",
  "user": "平台数据库账号",
  "password": "数据库密码的 Base64 编码"
}
```

Base64 只是编码，不是加密；沿用现有 Nacos 约定，须限制配置访问权限。可以在受信终端用以下命令生成，不把明文密码写进命令历史：

```bash
python3.12 -c 'import base64,getpass; print(base64.b64encode(getpass.getpass("Database password: ").encode()).decode())'
```

默认连接标识 `immpdb_wfs` 表示数据库 `immpdb`、schema `wfs`。更改名称时，Nacos 的 dataId 与 JSON 内容需同时对应。

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
