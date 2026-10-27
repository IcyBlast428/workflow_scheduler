# 平台与业务任务分别投产

正式安装、systemd 服务、环境配置和运维操作统一见[systemd 部署手册](systemd-deployment.md)。本文件说明两条发布流程及旧任务迁移，避免平台升级与任务代码更新混用。

## 两条发布流程

| 对象 | 操作入口 | 固定版本 | 回退范围 |
| --- | --- | --- | --- |
| 平台程序 | 运维使用 deploy_release.sh，systemd 管理 Web/Scheduler | 审批后的完整平台提交 SHA | 平台程序；数据库兼容性另行核对 |
| 业务任务 | GitLab 合并后，在任务列表审查、检查依赖并确认发布 | GitLab 完整提交、任务内容指纹及平台生成的任务版本 | 单任务代码；调度配置通过配置历史恢复 |

平台发布只构建平台依赖与前端；不会从 app/jobs 自动注册任务，不会重建已有任务环境或清理输出。任务新增以绿色卡片置顶，更新和删除在原任务行标识，经过确认后生效。ZIP 上传已删除，「任务示例」仅用于维护和下载示例；私有 PyPI 在独立「依赖仓库」配置。

目标分支之外的代码只用于差异与合并审查，不能直接发布。任务尚未发布前不会出现在运行任务统计中；已移入回收站的任务不自动恢复。详见[任务发布](task-packages.md)和[GitLab 接入](gitlab-updates.md)。

## 平台发布

```text
/data/wfs/releases/<SHA>/        平台程序与固定平台 .venv
/data/wfs/current               当前平台链接
/data/wfs/shared/data/          稳定的配置、执行记录、任务版本及输出
/data/wfs/shared/logs/          持久日志
```

1. checkout 审批提交，在旧平台仍运行时执行 `deploy_release.sh --prepare <SHA>`，完成依赖、后端/前端测试及构建。准备阶段不连接生产数据库、不切换版本、不停止服务。
2. 维护窗口内停止接收发布和手动执行，暂停调度，等待任务完成；停止 Web 和 Scheduler，配套备份数据库、shared 数据和密钥。
3. 首次从旧目录模型升级时，先完成下节迁移。脚本核对已知任务编号，发现旧任务尚无版本或删除记录时拒绝激活。
4. 执行 `deploy_release.sh --activate <SHA>`。只有两项服务停止后才运行迁移；之后切换 current，通过 systemd 启动 Scheduler 和 Web 并检查就绪。
5. 核对运行版本、数据目录、任务数量、两个 ready 接口和低风险任务，再恢复调度。记录审批 SHA、备份位置和验证结果。

已完成的 release 不覆盖。激活失败时先停止新服务，再尝试恢复旧代码；不自动撤销数据库迁移。必须使用经验证的向后兼容迁移，不兼容变更另行演练数据库恢复。回退不能只恢复平台代码而丢失 shared 数据与密钥。

Web 可以多 worker；Scheduler 只允许一个 worker、一个实例，不使用 preload/热重载。生产使用系统级 `wfs.service` 和 `wfs-scheduler.service`；本机 WSL 使用用户级 `wfs-local.service` 和 `wfs-local-scheduler.service`。不要同时启动旧 nohup 进程或 Docker 应用预览。

跨主机、Python 大版本、系统或 CPU 架构升级，需要在目标环境重建并验证任务依赖，不能把虚拟环境视为可随意搬移的发布产物。参见 [Python venv 说明](https://docs.python.org/3/library/venv.html)。

## 旧任务的一次性迁移

此工具只用于首次从旧目录任务升级，不是日常任务投产入口。先备份并停止 Web、Scheduler 及活动任务；平台库、共享数据目录、依赖仓库与密钥必须与原安装一致。

从准备好的新版 release 执行，生产配置通过 `service_config.py` 字面量读取，维护子进程不会启动 Scheduler：

```bash
APP_SHA='填写准备完成的完整平台提交SHA'
RELEASE="/data/wfs/releases/$APP_SHA"
cd "$RELEASE"

# 仅检查旧目录，不复制、安装依赖或发布
sudo .venv/bin/python scripts/service_config.py --environment-file /etc/wfs/wfs.env \
  --data /data/wfs/shared/data --logs /data/wfs/shared/logs -- \
  "$RELEASE/.venv/bin/python" scripts/migrate_legacy_tasks.py --source /path/to/old-platform/app/jobs

# 确认备份与停服后复制代码、建立独立环境、保留原编号注册版本
sudo .venv/bin/python scripts/service_config.py --environment-file /etc/wfs/wfs.env \
  --data /data/wfs/shared/data --logs /data/wfs/shared/logs -- \
  "$RELEASE/.venv/bin/python" scripts/migrate_legacy_tasks.py --source /path/to/old-platform/app/jobs --apply
```

迁移保留 PID、调度配置、历史和累计统计，不执行业务代码、不删除旧目录。任务的第三方依赖需要 requirements.txt，并提供可用的私有 PyPI 配置或匹配的离线 wheels；不能依赖旧平台环境中偶然安装的包。迁移创建的共享文件需归 `wfs:wfs`，激活脚本也会整理共享目录的属主。

重复执行跳过已发布或已删除任务。准备失败时保留草稿，不启动新版 Scheduler；修正依赖并重试，或按配套备份恢复旧平台。激活时自动执行 `--verify-only`。接入 GitLab 后使用相同稳定编号或绑定目录，再通过任务列表发布；缺失目录不会仅因一次扫描失败被当成删除。

## 备份与输出

生产数据库与 shared 文件共同构成平台数据，必须在停服窗口配套备份。shared 包括执行索引、三份加密配置、任务代码/环境和 task-data 输出；密钥另行保护。数据库使用对应产品配套工具；本机 PostgreSQL 容器仅为兼容性测试，不替代生产 DWS 验收。

业务发布读取固定提交并创建新任务版本，不对运行目录执行 Git 删除/清理。因此旧目录里多出的输出不会阻碍更新或回收任务，输出和旧代码继续保留。迁移到独立输出目录后，在业务代码里使用 `WFS_OUTPUT_DIR`、`WFS_TASK_DATA_DIR`。
