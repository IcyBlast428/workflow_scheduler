# 长期运行与任务管理优化

本轮按用户要求实施其余优化；第四项归档管理不增加定时归档、管理页面或批量归档改造。

## 交付内容

| 方向 | 实现 |
| --- | --- |
| 执行记录规模 | 独立的本地 WAL 持久化执行日志，按任务、待补写、状态建立索引；输出按日期和编号前缀分目录；固定 256 个锁；维护按批次处理。平台数据库仍为 GaussDB。 |
| 状态一致 | 成功、脚本失败、超时、取消、重启中断、并发跳过、错过调度分别展示；失败计数包含超时，不包含取消、中断和跳过。 |
| 完整统计 | 完成事务更新小时汇总与累计失败计数；历史记录按批次补算，补算期间使用完整原始数据计算，页面提示补算状态。 |
| 页面刷新 | 矩阵共享短期缓存，使用游标传输更新及删除的片；历史模式暂停自动刷新；实时模式通过服务器日期跨日。仪表盘不再同时由事件轮询和独立计时器刷新。 |
| 调度诊断 | 使用 APScheduler 的原始运行时间记录计划时间、启动延迟；并发跳过和错过窗口生成可追查的记录；详情显示全局容量和未启动原因。 |
| 告警可靠性 | 完成事务生成持久化通知，连续失败按事件合并，默认冷却 1800 秒，恢复成功通知；发送前失败有限重试，发送后结果不明确标记待核对，防止自动重复发送。开发环境不发送通知。 |
| 任务身份 | `.wfs-task.json` 固定任务 ID；本轮现有任务沿用原 ID，移动分组或重命名目录后仍关联原配置与历史。复制任务必须使用新的 ID，重复 ID 会阻止注册。 |
| 执行版本 | 保存发布版本、入口 SHA256、Python 版本与依赖文件摘要。历史界面显示执行时信息；代码浏览器仍显示当前文件，不伪装成历史源码。 |
| 操作效率 | 收藏与常用筛选按账户保存在本浏览器；负责人过滤；批量启用/暂停先预览任务、活动实例与配置版本，配置变化时拒绝提交。正在执行的实例继续运行。 |
| 矩阵浏览 | 分类、异常、全天/最近 6 小时/最近 1 小时筛选；全屏；保存视角；保留原有 Alt 鼠标操作与恢复全景。 |
| 维护与回归 | 管理页展示待补写、空间、统计覆盖、告警状态、接口和数据库采样耗时；前端状态拆分为组合函数，测试接入 CI；新增备份及恢复演练工具。 |

## 升级顺序

停止本地 Web 和 Scheduler 后，在现有环境中执行数据库迁移，再启动新版本。不要在旧代码仍执行时应用迁移。

```bash
bash scripts/local_service.sh stop .env.postgres.local
bash scripts/postgres_test_env.sh scripts/migrate.py
bash scripts/postgres_test_env.sh scripts/backfill_summaries.py --batch-size 1000 --max-batches 100
bash scripts/local_service.sh start .env.postgres.local
```

生产使用原 GaussDB 环境运行 `scripts/migrate.py`。新增迁移 006 会新增汇总标记列和索引，百万级表创建索引需要维护窗口；本地 PostgreSQL 测试不能替代实际 GaussDB 验收。

后台维护每轮最多处理 `WFS_MAINTENANCE_BATCH` 条（默认 500），待补写循环使用 `WFS_MAINTENANCE_SECONDS` 时间预算（默认 10 秒），单个数据库操作仍受查询超时约束；旧文件导入、历史补算和清理均限定条数。需要快速补算时，可重复运行上面的补算命令；事务失败回滚，重复运行不会重复计数。

旧 JSON 保持可按已知编号读取；后台分批导入本地日志索引，提交成功后删除对应 JSON，原有输出路径保持可读取。首次升级建议在停机期间执行：

```bash
bash scripts/postgres_test_env.sh scripts/backfill_summaries.py --import-legacy --batch-size 1000 --max-batches 1000
```

此操作不归档、不删除数据库历史。旧日志目录需要保留到导入和恢复检查完成。本地执行记录默认保留 90 天，`WFS_LOG_RETENTION_DAYS` 最小值为 60；数据库历史仍沿用已有保留与手动归档规则。

现有任务已生成标识文件。其他环境在移动目录前运行 `scripts/assign_task_ids.py` 固定原编号；新任务可使用 `--new-ids`，已有标识不会覆盖。代码版本摘要用于定位历史执行，不保证任务自行修改源码时的完全重现；生产采用不可变发布目录。

## 备份与恢复

SQLite 本地环境使用 `scripts/backup_local.py`。备份包含平台库、执行日志索引和分目录输出；执行恢复只能写入尚不存在的新目录。

PostgreSQL/GaussDB 使用匹配数据库版本的 `pg_dump`/`gs_dump`，同时备份任务代码及本地执行记录：

```bash
python scripts/backup_platform.py --data /var/lib/wfs --tasks /data/wfs/current/app/jobs \
  --output /backup/wfs-20261003.zip --database YOUR_DATABASE --schema wfs \
  --user YOUR_USER --host YOUR_HOST --port YOUR_PORT --tool /path/to/gs_dump
python scripts/restore_local.py --backup /backup/wfs-20261003.zip --destination /restore/wfs-20261003
```

工具沿用数据库工具的认证方式，不通过命令行参数传递密码。备份拒绝覆盖文件，Linux 文件权限为 0600；连接配置和 `.env` 不打包，但数据库备份、业务输出和代码本身应按敏感数据保护。

恢复先验证备份与本地日志完整性，再通过匹配版本的 `pg_restore`/`gs_restore` 恢复 `database.dump` 到新建数据库。任务配置、数据库历史、本地执行记录、任务 ID 与代码版本一并核对后才能切换服务。恢复工具不自动覆盖现有数据库。

GaussDB 工具格式与版本匹配要求参考 [华为官方 gs_dump 文档](https://support.huaweicloud.com/intl/en-us/tg-gaussdb-dist-v8/gaussdb-08-0011.html)。这是逻辑备份；生产的角色、集群配置和数据库级备份仍由现有数据库运维流程负责。

## 验证边界

2026-10-03 本地验证结果：

- 后端原回归 52 个用例：51 个通过、实际 GaussDB 连接用例因未提供专用环境而跳过；新增状态归档兼容用例及相关 6 个用例通过。
- PostgreSQL 18.1 / ODBC 的 8 个验收用例全部通过，包含并发完成、重复补写和秒级时间戳统计。
- 前端 4 组检查及生产构建通过；Windows 浏览器的 4 个场景通过，包含执行和日志、移动端、收藏与批量预览、矩阵筛选持久化和历史暂停刷新。
- 100 万条本地索引记录、100 个任务、1 万个实际输出文件：按任务最近记录查询中位数 0.31 毫秒、P95 0.39 毫秒，查询计划使用索引。此结果只反映本地测试环境。
- 100 个真实任务进程、8 个工作线程的混合测试：88 次成功、8 次预期失败、4 次超时，100 条历史均保存，执行名额全部释放。
- PostgreSQL 平台备份已恢复到独立测试数据库，共 2,000,034 条历史记录；备份摘要和本地日志索引完整性检查通过。
- 更新后的 Web 和单实例 Scheduler 已在 WSL 启动，Windows 侧就绪检查通过，启动后的实际定时任务执行成功。
- 本地历史补算全部完成：核对时在线历史与小时汇总均为 2,000,043 条，待补算为 0；原始失败记录和累计失败数均为 2,000。任务持续运行，后续计数会继续增长。

- Linux 后端功能回归：故障恢复、补算幂等、通知超时不重发、任务移动保持 ID、备份恢复。
- PostgreSQL 18.1 / ODBC：迁移、秒级时间戳兼容、并发完成时统计不丢失或重复、矩阵与日志查询。
- 前端：几何与配置测试、增量合并、跨日请求；浏览器测试包含收藏、批量启停预览、筛选恢复、历史停止轮询和移动端。
- 本地规模测试：100 万条索引记录、100 个任务、1 万个实际日志文件；另执行 100 个真实任务进程的长短任务、失败和超时混合突发测试。
- 不代表实际 GaussDB 已验证、百万个实际文件已生成，或生产长期吞吐与短信/邮件网关已验收。

复现命令：

```bash
python -m unittest discover -s tests -v
npm --prefix frontend test
npm --prefix frontend run test:e2e
python scripts/benchmark_journal.py --rows 1000000 --files 10000
python scripts/benchmark_pipeline.py
```
