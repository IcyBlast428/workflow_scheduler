# systemd + GaussDB/DWS 部署

生产统一使用 **root 用户和 root 用户组**，目录为 `/data/workflow_scheduler`，普通 HTTP 访问即可。无需创建 `wfs` 系统账户。服务器需具备 Linux x86_64、Python 3.12、systemd、unixODBC，以及与目标版本匹配的 DWS ODBC 驱动。

## 1. 目录与部署入口

```text
/data/workflow_scheduler/                              平台代码和已构建前端
/data/workflow_scheduler/wfs.service                  唯一生产服务模板
/data/workflow_scheduler/.venv/                        Python 环境
/data/workflow_scheduler/data/                         任务版本、依赖、输出和运行数据
/data/workflow_scheduler/logs/                         服务文件日志
/data/workflow_scheduler/deploy/root-test/runtime.env  固定密钥、管理员密码摘要和 Nacos 配置
/data/workflow_scheduler/scripts/wait_ready.py         服务就绪检查
```

首次安装统一按 [START-HERE.md](../START-HERE.md)，在项目目录以 root 运行 `bash deploy.sh`。安装器只读取项目根目录的 `wfs.service`，Web 监听 `0.0.0.0:8008`，Scheduler 只监听 `127.0.0.1:8009`。

生产统一安装一个 `wfs.service`。它启动 `scripts/serve.py`，依次拉起单 worker 调度器和双 worker Web，并等待调度器就绪后才开放 Web。任一 Gunicorn 主进程异常退出会清理另一进程，由 systemd 的 `Restart=on-failure` 重启整体；正常停止有超时清理机制。8009 仍作为进程间回环端口，不需要第二份 service。

唯一生产模板固定为 `User=root`、`Group=root`。`deploy/root-test/` 继续保存既有 `runtime.env` 和 ODBC 配置，不再保存另一份 service；已有密钥、密码摘要和数据目录无需搬迁。Linux 服务账户与数据库账户相互独立，数据库用户名仍以 Nacos 或平台连接配置为准。WSL 本机用户服务保持原有方式，不自动迁移或启用自启动。

## 2. GaussDB/DWS 与 HTTP

平台默认连接标识为 `wfsscheduler_wfs`，对应数据库 `wfsscheduler`、schema `wfs`。Nacos 使用 group=`gauss`、dataId=`gauss.wfsscheduler.wfs.json`。数据库由 DBA 提前建立，配置与表结构见 [数据库准备](../deploy/root-test/DATABASE.md)。

ODBC 路径统一由 `runtime.env` 中的 `ODBCSYSINI`、`ODBCINI` 和 `LD_LIBRARY_PATH` 指定；首次安装默认使用 `deploy/root-test/odbc/`，驱动库位于 `app/config/driver/dws_odbc/lib/odbc/`。服务模板不再设置另一套 ODBC 路径，已有配置继续生效。

HTTP 部署使用 `WFS_COOKIE_SECURE=false`，以便浏览器发送登录 Cookie；不要求 HTTPS。前端执行请求编号支持普通 HTTP 环境，不依赖只有安全上下文才提供的 `crypto.randomUUID()`。本机 localhost HTTP 被浏览器视为可信环境，因此不能单凭本机测试判断服务器 HTTP 兼容性。

只有已经配置 HTTPS 代理时，才设置 `WFS_COOKIE_SECURE=true` 或向下述服务生成工具传入 `--https-proxy`。这个选项不会配置证书或代理，也不会改变监听地址。

Nacos 的同进程配置缓存默认 60 秒，可通过 `WFS_NACOS_CONFIG_TTL_SECONDS` 设置为 0–3600 秒。修改连接信息最长需等待缓存有效期，或重启服务立即应用。配置过期且读取失败会报错，不继续使用过期配置。

唯一建表文件是 `schema/gauss.sql`。初始化只对空 schema 建表，已有本版基线只校验，不清空或自动迁移。目标 GaussDB、Nacos 与厂商驱动必须在生产现场验证，本机 PostgreSQL 回归不能替代这一步。

## 3. 核对唯一服务配置

日常安装使用 `bash deploy.sh`。如需在安装前预览生成结果，可执行：

```bash
cd /data/workflow_scheduler
.venv/bin/python scripts/install_systemd.py --scope system --output /tmp/wfs-units
diff -u wfs.service /tmp/wfs-units/wfs.service
```

默认生成结果与根目录模板完全一致，只有一个 `wfs.service`，运行账户固定为 root；不再提供 `--user` / `--group` 选择。预览不会安装、启用或重启服务。`runtime.env` 保持 0600，并保留原有密钥和密码摘要。

安装后检查实际生效配置（包括已有 drop-in）：

```bash
systemctl show wfs.service -p User -p Group -p FragmentPath
systemctl status wfs.service
curl --fail http://127.0.0.1:8008/api/user/ready
curl --fail http://127.0.0.1:8009/api/user/ready
```

`User` 和 `Group` 均应为 `root`，服务文件位于 `/etc/systemd/system/wfs.service`。Web 默认 2 个 worker，Scheduler 固定 1 个 worker、1 个实例。启动前自动校验 GaussDB 表结构，任一检查不通过都不会开放 Web。

## 4. 从双服务迁移及更新已有安装

先在页面开启维护并排空执行，备份数据库、`data/`、`logs/`、原 `runtime.env`，以及现有 service 和对应 `.service.d/` 覆盖配置。保留原密钥和数据；新模板统一以 root 运行，默认 HTTP 监听 `0.0.0.0:8008`。使用代理或自定义监听范围的已有安装，应核对相关覆盖配置。停止服务后更新代码与完整 `app/dist/`，包括新增的 `unsupported-browser.html`。

从旧版双服务切换时，必须先停用旧调度 service：

```bash
sudo systemctl stop wfs.service wfs-scheduler.service
sudo systemctl disable wfs-scheduler.service
```

先检查 `systemctl cat wfs.service wfs-scheduler.service`，将原 service 与 drop-in 文件备份到独立目录。更新代码和配置后，把项目根目录唯一的 `wfs.service` 安装到 `/etc/systemd/system/wfs.service`。迁移命令为：

```bash
cd /data/workflow_scheduler
# 先完成上述备份与维护停机，再安装已核对的新定义
sudo install -m 0644 wfs.service /etc/systemd/system/wfs.service
sudo systemctl daemon-reload
bash deploy.sh check
sudo systemctl start wfs.service
sudo systemctl status wfs.service
curl --fail http://127.0.0.1:8008/api/user/ready
curl --fail http://127.0.0.1:8009/api/user/ready
```

原来使用 `wfs` 账户的安装也统一切换到 root。先备份并核对旧 drop-in 中的 `User`、`Group`、`ExecStart`、`EnvironmentFile` 等覆盖项，修改或移除与新模板冲突的设置；不要删除无关的网络或资源限制。重启后用第 3 节命令确认实际账户和配置来源。旧调度 service 可保留为已禁用文件以便备份对照；新 service 声明冲突以避免同时运行，安装器还会拒绝仍在运行或仍启用自启动的旧调度服务。

以后启动、停止、重启与查日志只操作 `wfs.service`。日常更新无需再重复迁移步骤。首次安装是否随 Linux 服务器开机启动由部署命令决定；这些命令不涉及 Windows/WSL 本机自启动设置。

如果原数据或密钥实际位于旧目录，须停机迁移到统一位置后再修改 service。已有 `.venv` 迁移目录后按锁定依赖重建。部署脚本不会自动搬移或清空运行数据。

页面入口 HTML 使用 no-store；更新后重新载入页面即可获取新资源。前端源代码变更须在构建机运行 `npm --prefix frontend test` 和 `npm --prefix frontend run build` 后打包。

平台部署与任务发布分开：业务任务依旧按 GitLab 审查、依赖准备、显式发布流程处理，不需要重新部署平台。

## 5. 运维与备份

管理员可在“平台设置 → 运行策略 → 性能诊断”查看平台数据库连接、配置读取、查询与写入、事务锁等待、队列等待、任务启动延迟和接口耗时。页面每 30 秒更新，隐藏页面或离开分栏后暂停；失败会保留上次结果并退避重试。

耗时为最近 15 分钟的有界采样：每个进程每项最多 512 个样本、最多 128 项，汇总最多 64 个进程。P50/P95 从各进程原始样本合并后计算，不是各进程百分位的平均值。每个进程约每 5 秒原子写入 `WFS_DATA_DIR/runtime-metrics`，Web 与 Scheduler 必须能读写同一个持久目录；多主机部署也必须共享此目录。采样不包含 SQL、参数、密码或任务标识。快照损坏、写入失败或达到容量上限会在页面提示，不阻止业务操作。停机进程的窗口内样本仍可参与统计，来源列表不代表进程存活状态。该功能不替代长期监控系统，无需新增数据库表。

队列等待只统计成功派发的请求，从请求创建到派发完成，包含计划延后和重试退避；任务启动延迟从计划时间（无计划时取创建时间）到进程启动。两项可能重叠，不应相加。锁等待测量平台辅助状态事务获取表锁的耗时，包含一次数据库往返；不代表数据库所有锁。

失败率与耗时采样分开统计：在数据库端按最近 24 小时完成的执行记录聚合，缓存最多 30 秒；失败率为“失败与超时次数 / 成功、失败与超时次数”。取消、中断、跳过、错过和未知结果单列，试运行不计入。没有有效执行时显示“暂无执行”。统计截至时间在页面展示，历史补写会在下一次缓存更新后反映。

```bash
sudo journalctl -u wfs.service -n 100
sudo systemctl stop wfs.service
```

先开启维护模式并排空执行，再停止 wfs.service。使用目标产品支持的 gs_dump 等工具和同一时间窗口的共享文件备份，示例：

```bash
.venv/bin/python scripts/backup_platform.py --data /data/workflow_scheduler/data  --tasks app/jobs --output /backup/wfs-20261104.zip  --database wfsscheduler --schema wfs --user DB_USER --host DB_HOST --port 8000 --tool gs_dump
```

`DB_USER` 是数据库账号，不是 Linux 的 root 用户。命令应通过同一生产环境包装器执行，以便备份收据写入 GaussDB。数据库密码使用厂商工具支持的受限认证文件，不放命令行。数据库 dump 含加密业务连接、账户摘要及业务日志，应限制访问；密钥、Nacos、ODBC、pip 配置单独安全保管。

恢复工具 scripts/restore_platform.py 仅校验归档、摘要和路径并解压到不存在的新目录，不恢复数据库，也不证明业务恢复成功。由 DBA 使用匹配的厂商 restore 工具恢复到新数据库，再配置原加密密钥、新目标连接和共享目录，检查 schema、发布版本、授权、队列和外部业务结果后启动。任何状态不确定的执行都不自动重放。
