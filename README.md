# Workflow Scheduler

Python 任务调度与运维平台，使用 Flask、APScheduler 和 Vue。平台正式部署采用 **systemd + GaussDB/DWS**；任务代码由现有 GitLab 管理，依赖从私有 PyPI 准备。

## 快速部署

内网 root 固定目录安装请先阅读 [START-HERE.md](START-HERE.md)。解压到 `/data/workflow_scheduler` 后运行 `bash deploy.sh`，自动完成环境准备、配置引导、建表和服务启动。

## 当前架构

- Web 与单实例 Scheduler 分离，由 systemd 管理。
- 平台数据统一存入 GaussDB：账户、会话、任务配置、执行历史、队列、授权、业务连接、GitLab 配置、发布记录、DDL 修改记录和标签。
- 共享文件目录保存任务代码版本、独立 Python 环境、业务输出、日志、指标，以及数据库故障时的临时恢复文件。
- 任务默认无业务库授权，只能使用管理员明确授权的连接。业务库支持 MySQL、PostgreSQL 协议（含需独立验收的 GaussDB）与 ClickHouse。
- 不提供文件数据库、平台 MySQL 切换、旧目录自动发现或旧数据导入。全新安装使用唯一基线 `schema/gauss.sql`。

## 功能

任务发布采用 GitLab 扫描、源码分类、差异审查、显式发布和回收流程。任务执行支持参数、独立依赖、资源限制、并发配额、限速、错峰、持久排队、超时与取消。只有管理员声明可重复执行的任务才可开启自动重试与业务日期补跑，默认关闭。

页面提供任务列表与标签搜索、执行矩阵、增量日志、输出预览和下载、DDL 编辑与修改记录、GitLab 联动、角色权限、业务连接授权、私有依赖源、维护模式及备份状态。DDL 编辑不会直接执行数据库语句；ZIP 示例可下载，但不支持通过 ZIP 上传发布任务。

## 全新部署

请按 [systemd 部署手册](docs/systemd-deployment.md) 或固定目录的 [root 测试部署手册](deploy/root-test/README.md) 操作。不要复用旧平台库/schema，也不要复制旧数据目录。

初始化前由 DBA 建立独立数据库与账号，配置 Nacos 和 DWS ODBC。执行 `scripts/init_database.py` 创建全新 schema 的 32 张平台表；重复执行只检查当前基线。发现非空且没有本版标记的 schema 会拒绝初始化，不会升级、清空或导入。

## 本机开发与测试

生产仅使用 GaussDB/DWS。本机缺少生产服务器时，可显式使用独立 PostgreSQL 测试库验证协议、事务与界面；它不代表已通过实际 GaussDB 验收。应用仍以 systemd 运行，Docker 仅承载独立测试数据库。

参见 [本机数据库测试](docs/local-postgres-windows.md)。后端回归统一运行 `python scripts/test_backend.py`，每次创建独立 schema，每个用例重置测试表；禁止把此命令连接到生产数据库。前端在 `frontend` 中执行 `npm test`、`npm run build`、`npm run test:e2e`。

## 文档

[文档索引](docs/README.md) · [任务发布](docs/task-packages.md) · [GitLab 联动](docs/gitlab-updates.md) · [DDL 与标签](docs/task-schema-and-tags.md) · [调度容量](docs/task-dispatch.md) · [新架构检查记录](docs/fresh-gauss-audit.md)
