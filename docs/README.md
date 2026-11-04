# 文档导航

## 当前使用与运维

- [项目总说明](../README.md)：运行结构、登录与权限、连接配置。
- [systemd 部署](systemd-deployment.md)、[平台升级与旧任务迁移](platform-releases.md)、[部署与存储](deployment-and-storage.md)。
- [GitLab 接入](gitlab-updates.md)、[任务发布与回滚](task-packages.md)、[任务依赖与 Nexus](task-environments-and-nexus.md)。
- [多层目录与输出文件](task-outputs-and-projects.md)、[任务 DDL 与标签](task-schema-and-tags.md)、[任务调度与队列](task-dispatch.md)。
- [任务执行流程](task-flow.md)、[执行矩阵](execution-matrix.md)。
- [日常操作](operational-improvements.md)、[改进与操作手册](remaining-improvements.md)、[长期运行说明](runtime-scale-improvements.md)。

## 兼容与历史内容

本轮整理范围与保留依据见[旧内容清理记录](repository-cleanup.md)。

[历史记录与暂缓提案](archive/README.md)不作为当前操作手册。日常任务代码由 GitLab 管理，ZIP 只用于下载示例或版本备份；平台更新交给运维部署。

以下内容仍有用途，保留原接口和路径：

- `app/jobs`：默认 GitLab 任务目录和示例身份文件；平台运行使用已发布版本，而不是直接扫描本机目录。
- `scripts/migrate_legacy_tasks.py`、迁移 SQL 和旧日志读取：旧部署升级与历史数据兼容。
- GaussDB/DWS 驱动、Nacos、DES 兼容读取和通知公共模块：现有平台配置、旧业务脚本及共享 SDK 仍可能依赖。
- 返回 HTTP 410 的旧上传、同步和在线更新接口：明确告知旧客户端功能已停用，避免误操作。
- `run.sh`、`run.bat`、`backend_dev_runner.py`：本地调试入口；正式环境按 systemd 手册部署。

前端 `app/dist` 为构建产物，静态源文件统一放在 `frontend/public`。构建会清空旧产物并重新复制 public 资源；默认头像和兼容 favicon 均有对应源文件。不要在 dist 内手工保存业务文件或定制资源。
