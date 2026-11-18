# Workflow Scheduler

Python 任务调度与运维平台，使用 Flask、APScheduler 和 Vue。当前稳定版本采用 **root + `/data/workflow_scheduler` + Python 3.12 + systemd + GaussDB/DWS**，业务任务通过 GitLab 审查和显式发布。

## 全新投产

从 [START-HERE.md：全新投产操作手册](START-HERE.md) 开始，按顺序准备数据库和 Nacos、交付代码、安装依赖、启动服务、配置代理和发布首个任务。

- 新安装默认连接 `immpdb` 数据库、`wfs` schema，连接标识 `immpdb_wfs`；可以在引导中修改。已有配置保持原值。
- DBA 确认数据库与专用空 schema、账号权限；安装器按 `schema/gauss.sql` 初始化 32 张平台表。非空且没有当前基线标记的 schema 会拒绝初始化，不清空或导入旧数据。
- 完整部署包已带前端，不在生产执行 npm。交付可直接解压，也可经 GitLab 转存；保留完整构建文件和发布校验清单。
- 在目标目录运行 `bash deploy.sh`，引导创建环境、安装依赖、保存配置、初始化并启动唯一的 `wfs.service`。
- 直连端口 8008，Scheduler 控制端口仅绑定本机 8009；独立 Nginx/Docker 示例见 [代理部署](docs/nginx-deployment.md)。

`deploy/root-test/` 和 `scripts/setup_root_test.py` 是沿用的路径名称，实际用于生产配置与安装。保留这些路径是为了兼容已运行实例，无需改名或新建其他服务。数据库账号与 Linux root 账号相互独立。

## 稳定版功能与边界

- 一个 systemd 服务管理 Web 与单实例 Scheduler。平台账户、配置、历史、队列、授权和发布记录保存在 GaussDB；共享文件目录保存版本源码、独立 Python 环境、日志、输出和临时恢复文件。
- 每个任务版本建立独立环境，不继承平台或其他任务的包。没有 requirements.txt 时识别 import；可选功能包在页面补充，例如 pandas `.style` 使用的 Jinja2。暂不启用 pandas 功能用法自动推断。
- GitLab 推送不等于平台部署或任务发布。新任务在任务列表审查并发布；原代码重新准备依赖时保留任务身份和源码来源，任务目录未变可容许仓库其他提交前进。
- 支持参数、资源上限、并发配额、限速、错峰、队列、超时取消、执行矩阵、日志和输出预览下载。重试和补跑默认关闭，只对明确可重复执行的任务启用。
- 任务默认无业务数据库权限。管理员配置并授权后，通过公共 NewDB 接口访问业务库；数据库操作示例位于任务示例与文档。DDL 编辑不会直接执行数据库语句。
- GitLab 流水线当前停用，`.gitlab-ci.yml` 禁止创建流水线；生产不依赖 `.github/`。

用户已反馈本版在生产成功发布并执行任务；新环境仍需现场验证驱动、权限、网络和业务结果。详细边界见 [验证说明](deploy/root-test/VALIDATION.md)。

## 运维与开发

现有生产实例更新、备份和恢复见 [systemd 运维手册](docs/systemd-deployment.md)，不将全新安装流程用作重置操作。固定密钥、数据库和 `data/` 需要配套备份；重新生成密钥不能恢复原有加密配置。

本机开发使用独立 PostgreSQL 测试库，不能替代目标 GaussDB/DWS 验收。后端回归入口为 `python scripts/test_backend.py`，每次创建隔离 schema，禁止连接生产数据库。前端开发在 `frontend` 执行测试和构建，不在生产编译。参见 [本机测试](docs/local-postgres-windows.md)。

## 文档入口

[文档索引](docs/README.md) · [数据库与 32 张表](deploy/root-test/DATABASE.md) · [任务发布](docs/task-packages.md) · [任务依赖 / Nexus](docs/task-environments-and-nexus.md) · [GitLab](docs/gitlab-updates.md) · [多层目录与输出](docs/task-outputs-and-projects.md) · [业务连接](docs/business-database-connections.md)

历史架构图、PDF 和审查记录作为补充资料保留；首次投产以 START-HERE.md 和当前脚本为准。
