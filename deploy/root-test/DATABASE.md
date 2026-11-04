# 平台数据库与表：在哪里建、建哪些

## 建库位置

本部署的平台主库使用 **GaussDB/DWS**。请 DBA 在目标 GaussDB 集群创建独立数据库，例如 **wfsscheduler**，在其中使用 **wfs schema**，配独立平台账号。不要把这些表建进业务数据库、Nacos 自己的库或 ClickHouse。

当前连接标识按第一个下划线分隔数据库名/schema，例子使用无下划线的数据库名 wfsscheduler：`WFS_DB_ID=wfsscheduler_wfs`。Nacos 对应 `gauss.wfsscheduler.wfs.json`（group gauss），连接的 db=wfsscheduler、schema=wfs。已有生产平台库若沿用其他名字，修改配置指向实际库/schema，不能另建空库冒充迁移。

## 初始化顺序

1. **全新平台库**：DBA 先建立数据库与账号，再连接该数据库核对并执行根目录 `ddl.sql`。该文件针对 GaussDB Kernel 503.1.0.SPC2000c，包含 `CREATE SCHEMA wfs`、设置 search_path 和基线表，不是 MySQL DDL，也不是跨型号通用 SQL。schema 已存在时先核对，不盲目重跑 CREATE SCHEMA/CREATE TABLE。
2. 在正确的库/schema 下执行 `scripts/migrate.py`，按编号顺序应用 `migrations/001_*.sql` 起的所有迁移；迁移生成/记录校验和，不修改已应用的迁移文件。完整命令见本目录 README 第 3 步。
3. `setup_root_test.py --install` 只检查连接与下面 20 张表，不替 DBA 自动建库或执行初始 DDL。检查成功后才启动。
4. **已有平台库升级**：停服、配套备份，核对基线后仅执行未应用迁移。不要重新执行 ddl.sql，不要清空历史表。

运行期账号需要平台表 SELECT/INSERT/UPDATE/DELETE，迁移期另需建表、建索引、修改表等权限；DDL 权限是否拆分由 DBA 管理。schema 搜索路径须正确指向 wfs。表完整检查不等于全部列、索引、SQL 方言和性能已在目标产品验收。

## GaussDB 平台表清单（最终 20 张）

| 表名（均在平台库 wfs schema） | 用途 |
| --- | --- |
| wfs_task_config | 任务调度与配置 |
| wfs_job_stats | 任务运行状态和统计 |
| wfs_run_history | 近期执行历史及日志摘要 |
| wfs_run_history_archive | 归档执行历史 |
| wfs_history_rollup | 归档统计汇总 |
| wfs_schedule_history | 调度器平台事件 |
| wfs_auth_sessions | 登录会话 |
| wfs_executions | 执行状态镜像 |
| wfs_config_versions | 配置历史版本 |
| wfs_config_application | 配置生效状态 |
| wfs_audit | 操作审计 |
| wfs_users | 平台账号 |
| wfs_login_limits | 登录限流 |
| wfs_run_summary | 执行明细汇总 |
| wfs_run_totals | 任务累计统计 |
| wfs_notifications | 通知发送队列 |
| wfs_alert_incidents | 告警事件 |
| wfs_package_tasks | 已发布任务注册信息 |
| wfs_task_releases | 任务代码版本 |
| wfs_schema_migrations | 数据库迁移记录与校验和 |

不要执行 app/bootstrap/mysql_schema.sql；其中 wfs_platform_lock 为 MySQL 平台方案专用，不属于本 GaussDB 清单。app/bootstrap/sqlite_schema.sql 是本机/测试兼容基线，不在 GaussDB 上执行。

## 仍存在的本地配置/索引存储

平台主库使用 GaussDB，并不代表程序完全不使用 SQLite。当前架构自动创建以下文件，无需 DBA 手工建表，不能删除或忽略备份：

| 相对项目路径 | 自动维护内容 |
| --- | --- |
| data/database-connections.sqlite3 | profiles：加密平台/业务连接配置 |
| data/task-publishing.sqlite3 | settings：依赖仓库与任务示例设置 |
| data/gitlab-updates.sqlite3 | configuration、snapshot、scan_lease、acknowledgements：GitLab 配置、检查快照和已读状态 |
| data/admission.sqlite3 | settings、receipts、work_requests、ddl_history、hook_events：准入/执行请求、授权策略、DDL 草稿、标签与 webhook 去重等 |
| data/executions/journal.sqlite3 | journal：执行索引和恢复日志 |

这些文件在首次用到对应功能时自动创建，可能有 SQLite 的 -wal/-shm 伴随文件。应在停服后整体备份 data 与固定密钥。现阶段没有把这些表迁到 GaussDB 的开关，本包不隐含该架构重构。不会创建 data/platform.sqlite3 作为平台主库。

## 业务任务自己的表

业务表由每个任务决定，建在该任务业务连接所指向的业务库/schema，不与上述平台表混用。任务的 ddl/schema.sql 和页面“DDL 与标签”仅用于记录、审查；平台不会自动执行这些 SQL。由业务方/DBA 审核后在对应业务库执行。

CSV、JSON、业务日志等输出保存于 data/task-data/<任务编号>/runs/<执行编号>/，不是数据库表。数据库与文件存储应配套备份。
