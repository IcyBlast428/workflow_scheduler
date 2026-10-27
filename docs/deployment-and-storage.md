# systemd 部署与数据保留

当前部署方式已统一为 **systemd 管理 Web 和单实例 Scheduler**。完整安装、环境配置、升级、回退和故障排查见[systemd 部署手册](systemd-deployment.md)。此前的容器交付选型建议不再作为本项目的生产实施方案。

## 当前约定

- 应用通过 systemd 托管 Gunicorn，无需 Docker 镜像或 Compose。CI 使用的测试镜像与生产应用部署是两件事。
- 生产继续使用已有 GaussDB/DWS、Nacos 和私有 PyPI；此次调整不更换数据库引擎、不迁移生产数据。
- 本机 PostgreSQL 测试库按用户选择保留 Docker，应用改由 WSL 用户级 systemd 管理。旧 18018 预览应用已停用，数据库与数据卷保留。
- Web 和 Scheduler 使用相同的共享绝对路径、固定密钥和数据库；Scheduler 保持一个进程实例、一个 worker。

## 平台数据与业务数据

平台数据库保存账号、会话、任务配置、版本注册、执行结果与审计。业务任务通过 `NewDB('连接标识')` 访问各自业务库，平台保留标识 `platform` 不供业务任务使用。

`shared/data` 则保存执行索引、日志、资源采样、加密连接/发布/GitLab 配置，以及任务代码版本、独立 Python 环境和输出。数据库备份不能代替文件备份，丢失密钥也无法仅靠恢复配置 SQLite 解密。

任务来自 GitLab 目标分支，确认发布时生成新的独立目录。平台版本切换不搬动任务环境，GitLab 删除也不直接删除运行目录；本地额外输出不会阻碍任务更新或移入回收站。

## 数据库边界

GaussDB/DWS 生产入口沿用现有 DWS ODBC/Nacos 配置。型号、版本、驱动、分布式事务、索引和恢复流程必须以目标环境验证为准。开发 PostgreSQL/SQLite 测试不能代表全部 GaussDB 产品兼容性。

项目另有 MySQL/PolarDB 的管理连接能力，本次不要求切换到它。ClickHouse 仍用于业务或分析需求，不作为本次平台主库变更。页面保存连接配置不搬迁历史数据。

## 长期运行与备份

保留至少 90 天在线执行明细及可查询归档，按任务/日期索引查询，定期观察数据库锁等待、完成事件写入速度、磁盘余量和归档增长。不因改用 systemd 就扩大 Scheduler 副本数。

每次平台激活前，先等待活动任务结束、停服，按产品配套方案备份数据库、shared 文件和原配置密钥。恢复先到新库/新目录做校验，兼容验证完成后再切换；不要把旧 Python 虚拟环境搬到不兼容的系统或路径。

后续运维入口统一使用 systemctl/journalctl；任务代码投产使用平台内的 GitLab 任务审查流程。对应操作见[平台与任务分别投产](platform-releases.md)、[任务发布](task-packages.md)及[任务依赖仓库](task-environments-and-nexus.md)。
