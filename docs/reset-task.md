# 将旧任务彻底清理后按新任务发布

以下以任务 `daily_report` 为例，请替换为要清理的实际任务编号及 GitLab 目录：

```
app/jobs/reports/daily_report
```

删除任务统计表的一行、移入回收站或重装平台，都不会删除完整任务身份。因此旧目录仍可能被原任务占用。此工具清理该任务专属的注册、版本、调度、执行历史、通知、授权与目录绑定，并移出它的版本文件、持久数据、输出和执行日志。清理后重新扫描 GitLab，可按新任务获取代码、检查依赖并发布；调度需要重新配置，内部编号由平台生成，不需要修改仓库目录或添加 v2。

工具保留 GitLab 连接与令牌、其他任务和共享数据库连接。GitLab 源代码、Git 提交记录、共享平台日志、业务数据库内容及浏览器偏好不在清理范围。任务文件和数据库记录先备份到 `/data/workflow_scheduler/data/task-reset-backups/<时间-随机编号>/`，该目录不参与任务发现。备份只允许服务器部署账户读取。

## 1. 预览清理范围

本版部署包已包含清理工具。进入部署目录，先预览：

```bash
cd /data/workflow_scheduler
task_id=daily_report
.venv/bin/python scripts/reset_task.py \
  --project /data/workflow_scheduler --expect-db-id immpdb_wfs \
  --pid "$task_id" --path "app/jobs/reports/$task_id"
```

不加 `--apply` 只读取和显示清理范围，不修改数据库或任务文件。预览可能包含原编号和该目录自动生成的编号。若发现不同仓库、不同目录或不安全文件路径，工具会停止，不会自动扩展清理范围。

## 2. 停止平台，执行清理并重新启动

这一步会短暂停止整个平台，请在没有业务任务运行时执行。工具还会检查服务已停止、没有该任务的子进程，以及数据库和 schema 确实是 `immpdb.wfs`。继续使用上一步的终端：

```bash
systemctl stop wfs.service
.venv/bin/python scripts/reset_task.py \
  --project /data/workflow_scheduler --expect-db-id immpdb_wfs \
  --pid "$task_id" --path "app/jobs/reports/$task_id" --apply \
  && systemctl start wfs.service
```

看到“清理完成”和隔离备份目录才表示成功。失败时不要继续手工删表；保留完整错误和备份路径。数据库修改在同一事务中执行，普通文件移动异常会回滚数据库并移回已移动文件。断电或强制杀死进程时需核对备份中的 `records.json`、`files/` 和 `COMPLETED` 标记再恢复服务，不能仅凭文件是否存在判断是否提交。

## 3. 重新发布

登录平台，在“任务列表”中点击“立即检查 GitLab”，等待检查完成。原目录应显示“新任务 · 待发布”。依次获取代码、检查依赖、发布，再配置调度。无需重新推送相同代码，也不需要更改目录名。

脚本复用服务器现有虚拟环境和 Nacos 配置，不安装依赖，不修改部署包中的源文件，也不需要重建数据库表。
