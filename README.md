# Workflow Scheduler

长期运行优化、升级步骤和验证范围见 [优化说明](docs/runtime-scale-improvements.md)。

面向内网运维与业务脚本的定时任务平台，使用 Flask、APScheduler 和 Vue 3。提供登录、任务发现、调度配置、手动执行、暂停、强停、运行日志，以及 CPU/内存和任务运行时间线。

## 运行结构

- Web：提供页面与 API，可运行多个 worker。
- Scheduler：运行 APScheduler 和任务控制接口，必须只有一个 worker；Web 将控制请求转发给它。
- 每次执行：独立 Python 子进程；手动和自动执行共享任务并发限制；超时、强停与服务退出清理子进程组。
- 生产数据库：GaussDB/DWS，使用短生命周期 ODBC 连接。
- 本地验证：显式启用独立 SQLite 或 PostgreSQL 18.1 测试库。

生产默认 Web 8008、Scheduler 127.0.0.1:8009；WSL 本地默认 18008、18009。状态每 5 秒轮询，页面隐藏时暂停，不占用 SSE 长连接。

## 目录

```text
app/api/                 登录、任务控制、查询接口
app/bootstrap/           任务发现、调度、执行、数据库、会话与指标
app/common/              公共业务工具与数据库适配器
app/config/              非敏感配置模板与 ODBC 驱动
app/jobs/<group>/<task>/  任务代码
app/dist/                已构建前端
frontend/                Vue 源码
migrations/              编号数据库迁移
scripts/                 本地环境初始化、服务管理、发布、迁移
tests/                   独立本地数据库的集成测试
ddl.sql                  新建生产数据库的初始表结构
```

## WSL 启动

在 Ubuntu WSL 终端进入项目目录：

```bash
cd /mnt/c/Users/cy428/Documents/GitLab/workflow_scheduler
python3 -m venv ~/.local/share/workflow-scheduler/.venv
~/.local/share/workflow-scheduler/.venv/bin/pip install -r requirements.txt
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
~/.local/share/workflow-scheduler/.venv/bin/python scripts/init_local_env.py
bash run.sh migrate
bash scripts/local_service.sh start
```

初始化脚本生成随机管理员密码并只显示一次；配置写入未被 Git 跟踪的 `.env.local`。已存在时不会覆盖配置。启动脚本使用其中的 Python 路径，将 Web 与 Scheduler 放在后台运行。访问 <http://127.0.0.1:18008/>。

```bash
bash scripts/local_service.sh status
bash scripts/local_service.sh stop
# 停止后再启动即可重启
bash scripts/local_service.sh start
```

日志为 `data/web.log`、`data/scheduler.log`，数据库为 `data/wfs-local.sqlite3`。WSL 关闭后需要重新启动服务。后台进程不会在关闭终端后退出。

单进程调试可使用 `bash run.sh single`。Windows 原生调试需要自行设置同名环境变量后运行 `backend_dev_runner.py`；`.env.local` 是 Bash 格式。

### PostgreSQL 18.1 兼容性测试

当前 WSL 已运行用户本地的 `postgres:18.1` 镜像，容器为 `wfs-postgres18-test`。数据库连接为 `127.0.0.1:15432`，数据库/用户为 `wfstest`，schema 为 `wfs`；数据卷为 `wfs-postgres18-test-data`，挂载到 PostgreSQL 18 的 `/var/lib/postgresql`。密码和配置保存在 Git 忽略的 `.env.postgres.local` 与 `.wfs-secrets/`，管理员登录沿用原本地账户。

首次配置需要 WSL 中可用的 Docker 镜像、Python 环境，以及 `odbc-postgresql`、`libodbc2`、`unixodbc`。已有配置可以直接从启动数据库开始：

```bash
# 首次生成配置；已存在时拒绝覆盖
set -a
source .env.local
set +a
"$WFS_PYTHON" scripts/init_postgres_test.py

# 启动数据库，创建初始表并应用增量迁移；可以重复执行
bash scripts/start_postgres_test.sh
bash scripts/postgres_test_env.sh scripts/prepare_postgres_test.py
bash scripts/postgres_test_env.sh scripts/accept_postgres_test.py

# 切换 Web 和 Scheduler 到 PostgreSQL 测试库
bash scripts/local_service.sh stop
bash scripts/local_service.sh start .env.postgres.local
```

当前测试库包含 14 张表和 4 个已应用迁移。页面地址仍为 <http://127.0.0.1:18008/>。原 SQLite 数据库保留，两种配置使用独立执行数据目录；恢复 SQLite 时先停止服务，再执行 `bash scripts/local_service.sh start`。该切换不会迁移两种数据库中的数据。

可选容量测试：`bash scripts/postgres_test_env.sh scripts/benchmark_postgres_history.py`。它只允许指定本地测试环境，生成 200 万条标记为 `postgres-volume-test` 的合成日志，并写出 `data/postgres-history-benchmark.json`；这些记录会保留供页面查询，数据库约占 1.7 GB。测试衡量本机 SQL 查询与索引计划，不能代表实际业务日志大小、并发压力或生产 GaussDB 性能。

测试使用 `WFS_DB_DRIVER=PostgreSQL Unicode`；生产默认仍为 `DWS`。`WFS_DB_QUERY_TIMEOUT_SECONDS` 控制服务端单语句超时，默认 10 秒，允许 1–3600 秒。PostgreSQL 测试验证通用 SQL、ODBC、事务和锁；真正 GaussDB 的驱动、分布式行为与执行计划仍需在目标环境验收。

## 任务与调度

### 在线只读查看任务文件

在“任务列表 → 详情 → 查看代码”打开任务目录文件浏览器。支持进入子目录、返回上级、切换文件；文本和配置文件显示行号，支持搜索、复制和自动换行，常见图片支持预览。当前展示的是部署目录中的文件，不能用于追溯某次历史执行的代码版本。

接口仅提供 `GET /api/taskinfo/source`，登录后按现有角色读取，没有写入接口。服务端限制访问到当前任务目录，拒绝路径越界、符号链接和特殊文件。文本最多 1 MiB / 10000 行、图片最多 2 MiB；每页目录最多 200 项，每个目录扫描上限 20000 项。其他二进制和超限文件展示类型、大小、修改时间等信息，不执行 HTML/SVG 内容。Python 编码声明与常见 UTF-8/GBK 中文文本可读取。

任务目录中的配置文件也属于可读范围；平台凭据配置继续存放于任务目录外的环境配置或密钥配置中。

任务目录为 `app/jobs/<group>/<task>/`，PID 为 `<group>__<task>`，默认入口 `main.py`。目录名确定后应保持稳定。

```text
app/jobs/<group>/<task>/
├── main.py
├── README.md              说明、负责人、运行手册
├── requirements.txt       可选，任务专属依赖
└── .venv/                 可选，任务专属 Python 环境
```

解释器优先级：任务 `.venv` → 任务组 `.venv` → 平台 Python。业务任务应维护自己的依赖、幂等逻辑和合理超时；任务组也可以提供 `requirements.txt` 与共享 `.venv`。

新增任务后点击“同步任务”，再配置入口、展示名称、并发、超时和调度。配置保存在 `wfs_task_config`；任务目录的旧 `config.ini` 不作为当前调度依据。支持每分钟/小时、每 N 分钟/小时、每日/周/月、月末、单次、时间窗口及高级 Cron。interval 首轮注册会随机错峰，错峰不写入数据库。

暂停自动调度后仍可手动运行一次。强停会取消该任务已排队和正在运行的所有实例；实例真正结束后才释放并发名额。每次运行的输出最多保留 63 KiB，超出部分仍持续读取并丢弃，日志标明截断。输出包括合并后的标准输出和错误输出。

## 登录与密钥

必须设置 `WFS_SECRET_KEY` 和 `WFS_ADMIN_PASSWORD_HASH`，后者是 Werkzeug 生成的 scrypt 密码摘要。`WFS_ADMIN_USERNAME` 默认 `admin`。本地初始化脚本自动设置这些值。

浏览器登录使用 HttpOnly、SameSite=Strict Cookie，服务端数据库记录有效会话，8 小时过期，注销立即撤销。修改请求必须附带登录返回的 `X-CSRF-Token`。前端只在 sessionStorage 保存 CSRF 值；URL、localStorage 和静态长期 token 不再用于认证。

生产通过 `/etc/wfs/wfs.env` 配置凭据，文件权限应为 0600。生产服务开启 `WFS_COOKIE_SECURE=true`，需要 HTTPS 反向代理；不能直接在普通 HTTP 页面登录。不要把密钥或密码摘要提交到仓库。

| 变量 | 用途 |
| --- | --- |
| `WFS_ENV` | development / production |
| `WFS_ENABLE_SCHEDULER` | 是否启用调度器 |
| `WFS_SCHEDULER_CONTROL_URL` | Web 转发任务控制请求的地址 |
| `WFS_SECRET_KEY` | 所有 Web/Scheduler 实例共享的随机 Cookie 签名密钥 |
| `WFS_ADMIN_PASSWORD_HASH` | 管理员 scrypt 摘要 |
| `WFS_COOKIE_SECURE` | HTTPS Cookie，生产为 true |
| `WFS_NACOS_URL/USERNAME/PASSWORD` | 生产配置中心连接 |
| `WFS_DB_ID` | 数据库与 schema，默认 sysimemedb_wfs |
| `WFS_DB_CONFIG_FILE` | 开发 GaussDB 配置文件，建议放在仓库外 |
| `WFS_DB_PASSWORD` | 开发 GaussDB 明文密码的环境覆盖值 |
| `WFS_LEGACY_DES_KEY` | 仅用于兼容历史加密配置 |
| `WFS_LEGACY_FTP_PASSWORD` | 旧 FTP 公共工具密码 |
| `WFS_MPCM_ACCESS_TOKEN` | 对应业务集成的外部凭据 |
| `WFS_LOCAL_DB_PATH` | 独立本地 SQLite；生产发布脚本会清除此值 |
| `WFS_DEV_RUN_ALL` | 开发环境发现所有任务 |
| `WFS_CODE_REMOTE/BRANCH` | 检查更新时比较的远端和分支；生产 archive 目录需使用仓库 URL，而不是 origin 别名 |

仓库模板中的历史凭据已清空。历史版本中暴露的真实密码和 token 必须在对应系统轮换；清空当前文件不会使旧凭据失效，也不会删除 Git 历史。

## 数据库与迁移

默认平台数据库为 `sysimemedb` 的 `wfs` schema。已有部署使用其他 schema 时设置 `WFS_DB_ID`，例如 `sysimemedb_immpdb`，不要把新 DDL 导入另一 schema。生产从 Nacos 读取 `gauss.<database>.<schema>.json`，密码兼容原有 Base64 格式；Base64 不是安全加密，应依靠配置中心访问控制。

新库先执行 `ddl.sql`，再运行以下迁移；现有库保留数据，只运行增量迁移：

```bash
# 先导出生产环境变量与 ODBC 配置
.venv/bin/python scripts/migrate.py
```

迁移按文件名顺序执行，每个文件一个事务，成功后写入 `wfs_schema_migrations`。数据库锁防止同时应用；SHA256 校验防止已应用文件被修改。旧登记无校验值时首次补录。解析器支持引号内分号、转义引号、美元引号与 SQL 注释；复杂过程仍应先在测试库验证。已应用文件不要修改；用新编号增加迁移。

当前迁移包括基线、共享会话，以及执行状态、配置历史、生效状态、账户、操作审计与登录限制。发布回滚只切换代码，不回滚数据库；迁移必须向后兼容，变更前应备份数据库。

### 大量调度日志与可查询归档

继续使用 GaussDB。日志页面默认最近 7 天，按结束时间和记录编号游标分页，不再使用深 OFFSET 或每 5 秒统计历史全表。日期结束当天包含完整一天；每次最多查询 93 天，可查询更早的任意日期段。

`003_history_archive.sql` 增加归档表、累计失败归档汇总表和在线/归档的组合索引。索引建设需要在目标 GaussDB 测试及维护窗口执行；已验证独立 SQLite 和本地 PostgreSQL 18.1，未验证生产 GaussDB 执行计划或吞吐。

- 近期记录默认保留至少 90 天（超过两个月）；归档工具拒绝更短的在线保留时间。
- 归档仍保留在数据库的 `wfs_run_history_archive`，页面选择“归档记录”或“近期与归档”，按任务 ID 与日期查询。两张表各取一页候选后合并，避免加载全部历史。
- 归档表无自动删除期限；其大小会继续增长，需按业务要求规划备份、存储容量和进一步的按月分区。它与在线表仍共享数据库资源。
- 每批默认 200 条，每次最多 50 批。先复制、逐条比较全部字段，再在同一事务中移除源记录；不一致时整批回滚。失败可重跑，已提交批次不会重复累计归档失败数。
- 累计失败数合并在线历史和归档汇总，缓存 60 秒；最近结果与连续失败仍读取最新状态。
- 后台维护不再直接删除 `wfs_run_history` 或 `wfs_schedule_history`。系统调度日志暂不归档，也不会由该工具删除。
- 旧日期的任务日志详情读取保存的 `tasklog`。本地完整输出文件至少保留 90 天，过期后仍能查询数据库中的输出摘要；新执行的摘要上限为 63 KiB。

先备份数据库，应用迁移，再部署前后端。以下命令继承已经导出的生产环境变量和 ODBC/Nacos 配置；不载入本地 `.env.local`：

```bash
# 只预览最多 200 个符合日期的记录，不查询全表总数、不移动数据
.venv/bin/python scripts/archive_history.py --days 90
# 明确执行最多 50 批；完成后可重复执行，直到旧记录归档完毕
.venv/bin/python scripts/archive_history.py --days 90 --batch-size 200 --max-batches 50 --apply
```

不默认创建定时归档任务。生产首次执行前，应在测试库验证锁行为、异常回滚、归档内容与查询，并检查查询计划命中组合索引；当前实现不等同于生产海量日志验收。

平台表：`wfs_run_history`、`wfs_schedule_history`、`wfs_job_stats`、`wfs_task_config`、`wfs_auth_sessions`、`wfs_schema_migrations`。调度配置替换和运行结果写入使用事务。

任务业务库使用 `app/common/db/` 工厂和适配器，兼容入口为 `app.common.database.NewDB`。业务数据库配置与平台数据库分开；特殊驱动放在任务环境中。

## Linux 生产发布

服务使用专用 `wfs` 用户，代码通过 `/data/wfs/current` 指向独立版本目录。先创建用户、配置 `/etc/wfs/wfs.env`、准备 GaussDB 表和 HTTPS 代理，将两个 `.service` 文件安装到 `/etc/systemd/system/` 后运行 `systemctl daemon-reload`。本轮验证使用 Linux x86_64、Python 3.12；发布安装 `requirements-linux-py312.lock`。服务器还需 Node/npm、ODBC 运行库、Git、curl 和 flock。

```bash
# 在源代码 checkout 中，发布已经提交的版本
sudo bash scripts/deploy_release.sh <commit-or-ref>
sudo systemctl enable wfs-scheduler wfs
sudo journalctl -u wfs -u wfs-scheduler -f
```

发布脚本加锁，导出指定提交到 `/data/wfs/releases/<sha>`，安装平台和声明的任务/任务组依赖，执行测试、前端构建和数据库迁移，再原子切换 current 并重启服务。健康检查失败时恢复旧版本链接。已存在的版本目录不覆盖，以便检查失败产物。初次迁移旧目录时应先备份并移开现有 current 普通目录。

自定义部署根目录时，必须同步修改两个 systemd 文件中的路径。ODBC 配置由脚本改为当前 release 的绝对路径。生产服务的 Scheduler 始终保持单 worker；不要横向扩容调度器。

执行日志、运行状态、指标统一放在 `/data/wfs/shared/data`，服务日志放在 `shared/logs`，发布不切换数据目录。代码归 root:wfs 所有，服务不能修改代码；业务文件请写入 `WFS_DATA_DIR` 或明确的外部目录。旧版本 `current/data` 有数据时，发布会要求先停服务、备份并迁移到 `shared/data`，避免自动复制正在写入的数据。

页面上的“检查更新”通过 ls-remote 比较 Git 版本，不修改在线工作目录、不执行 reset、不自动发布。生产版本目录保存 `.release-revision`；环境中的 `WFS_CODE_REMOTE` 需设置可读取的仓库 URL，不包含密码。代码发布通过上面的版本目录流程完成。

## 验证与开发

```bash
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
```

测试使用临时 SQLite；覆盖认证、权限、配置冲突/恢复、生效失败、并发、日志截断/中文分块、进程树清理、数据库故障补写、重启恢复、资源限制、指标恢复、备份和迁移校验。发布测试使用模拟服务验证构建失败与激活失败回退，不改动 systemd。GitLab CI 包含后端测试、前端构建及 Playwright 浏览器回归；浏览器测试服务只使用临时目录，不读取 `.env.local`。

浏览器自动化回归（需要浏览器及其 Linux 运行依赖）：

```bash
cd frontend
npx playwright install chromium
WFS_BROWSER_PYTHON=/absolute/path/to/python3.12 npm run test:e2e
```

GaussDB 验收仅在提供专用测试 schema 后显式运行：导出对应 Nacos/ODBC 环境，取消 `WFS_LOCAL_DB_PATH`，执行 `WFS_TEST_GAUSS=true python -m unittest discover -s tests -p test_gauss_integration.py -v`。该用例创建并清理独立临时表；不要把全部本地测试当作 GaussDB 验收。

Vite 开发服务默认 5173，API 代理默认 8008；使用 WSL 18008 时相应修改代理配置。正常使用直接访问 Flask/Gunicorn 托管页面即可。

本地验证不等于生产 GaussDB、ODBC、Nacos、通知通道和 systemd 发布验收；这些需在对应目标环境完成。

## 常用接口

执行矩阵从左侧菜单进入，展示按任务分组的当日执行轨迹，支持 Alt 鼠标旋转、缩放和平移。高频记录会自动按时间段合并，并可跳转到原始日志。详细规则和测试见 [执行矩阵](docs/execution-matrix.md)。

- `GET /api/user/health`：公开存活检查。
- `POST /api/user/login`、`POST /api/user/logout`：登录/注销。
- `GET /api/taskinfo/state`、`dashboard`、`events`：任务、指标、实时快照。
- `GET/POST/PUT /api/taskinfo/schedule`：读取/预览/保存。
- `POST /api/taskinfo/editTask`：启动、暂停、强停、刷新。
- `POST /api/taskinfo/call_task`：手动执行。
- `POST /api/taskinfo/taskLogs`、`systemLogs`：日志查询。
- `GET /api/user/ready`：数据库、磁盘空间、调度心跳就绪检查；未就绪返回 503。
- `GET /api/taskinfo/detail`、`runs`、`run`、`run-download`：任务详情、执行记录、增量日志、下载。
- `GET /api/taskinfo/matrix`：最近 90 天内按日期读取任务与执行矩阵摘要。
- `POST /api/taskinfo/restore`：按当前版本号恢复历史配置并生成新版本。
- `GET/POST /api/admin/users`、`GET /api/admin/audit`：账户和审计。

## 执行、配置与权限

- 每次执行有独立编号，记录排队、运行、心跳、成功/失败/取消/重启中断。数据库写入失败保留本地日志，并每 60 秒补写；结果与失败统计在同一个事务中，重复恢复不会重复计数。
- 重启时将未结束执行标记为中断，校验 Linux 进程身份后清理遗留 worker。不会自动重试失败或补跑停机期间的执行，避免业务重复写入；确认业务数据后可在执行详情选择“再执行一次”。恢复不等于业务事务恢复。
- APScheduler 保持 `coalesce=True`；可配置错过执行的宽限秒数。全平台默认最多 20 个排队/运行实例，手动与自动共享名额；每个任务另有自己的并发上限。
- 调度“已启用”和活动实例分别显示；连续失败和保留历史内累计失败分开展示，取消与重启中断不计为脚本失败。历史分页显示是否还有下一页，不展示推算总页数。
- 配置保存必须携带当前版本；冲突拒绝覆盖。配置历史可恢复为新版本；保存与生效状态分开，未生效配置每 60 秒重新应用。任务说明、负责人、最近耗时、修改人和操作记录在“详情”查看。
- 查看者只读；操作员可手动执行、启停/刷新任务；管理员可改配置、恢复历史、同步/重载和管理账户。账户禁用与权限变更实时检查。环境管理员通过服务配置管理。失败登录按 IP 和用户名/IP 组合限制，15 分钟内分别最多 20/5 次失败。
- 平台入口改为按需导入；任务 worker 使用标准库启动。任务扫描缓存 3 秒，配置保存/刷新使缓存失效。资源监控从调度启动开始，每 5 秒采样，保留 6 小时；页面增量请求，并在隐藏时暂停轮询。

## 容量、资源与备份

| 环境变量 | 默认与用途 |
| --- | --- |
| `WFS_DATA_DIR` | 本地 `data`；生产 `shared/data`，Web/Scheduler 必须一致 |
| `WFS_MAX_ACTIVE_RUNS` | 20，全平台活动实例上限 |
| `WFS_RUN_LOG_MAX_BYTES` | 5 MiB，每次执行保留日志上限；历史摘要 63 KiB，超额输出持续读取后丢弃 |
| `WFS_LOG_RETENTION_DAYS` | 90，已完成且成功补写的本地日志/状态保留天数，最少 90 天 |
| `WFS_HISTORY_RETENTION_DAYS` | 90，执行状态镜像和审计历史保留天数；不删除任务执行历史或系统调度历史 |
| `WFS_CONFIG_VERSIONS_KEEP` | 每任务保留最近 100 个版本，最少 20 |
| `WFS_MIN_FREE_MB` | 100，低于此值就绪检查失败并拒绝创建新执行 |
| `WFS_TASK_MEMORY_MB` | 0 不限；Linux 每进程地址空间上限 |
| `WFS_TASK_CPU_SECONDS` | 0 不限；Linux 每进程累计 CPU 时间上限 |
| `WFS_TASK_FILE_MB` | 100，Linux 每个输出文件大小上限 |

任务配置可设置更严格的资源值；全局设置了上限时，任务填 0 也不能绕过。限制通过 Linux `resource` 实现，子进程继承；不是整个进程树的总内存/总 CPU 限制，也不是不可信脚本沙箱。超时和取消使用进程组清理。

通知最多 2 个后台消费者、100 条待发记录，网关超时 10 秒；满队列会记录错误，执行结果仍保留。通知队列本身不跨重启持久化。短信需设置 `WFS_SMS_USERNAME/PASSWORD`，可用 `WFS_SMS_HOST/PORT` 覆盖网关；邮件可用 `WFS_SMTP_HOST/PORT/SENDER` 配置。需在实际业务通道验收。

本地一致备份：先停止服务，备份文件必须在 data 外，且不会覆盖旧备份：

```bash
bash scripts/local_service.sh stop
python3 scripts/backup_local.py --database data/wfs-local.sqlite3 --data data --output backups/wfs-backup.zip
bash scripts/local_service.sh start
```

备份包含 SQLite 快照、执行状态/日志、审计待写文件和指标，并检查数据库完整性。恢复时停止服务，将 `database.sqlite3` 放回原数据库路径，将归档内 `data` 内容放回原 `WFS_DATA_DIR`；保留原 `.env.local`，其中的签名密钥和管理员摘要不在备份内。备份包含业务日志和账户摘要，请限制访问。GaussDB 需另行执行目标数据库支持的一致备份，再备份共享数据目录；此本地工具不备份生产数据库。
- `POST /api/taskinfo/updatecode`：检查 Git 更新。

### 任务代码发布

新增「任务发布」页面，支持多文件 ZIP 上传、只读差异预览、离线依赖检查、发布、代码回滚和回收站。原 Git 任务可保留编号导入，现有调度配置和日志延续使用。部署前应用 `007_task_packages.sql`；操作方式、离线依赖和数据目录见 [任务包管理说明](docs/task-packages.md)。
