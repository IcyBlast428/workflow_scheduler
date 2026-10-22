# Workflow Scheduler

长期运行优化、升级步骤和验证范围见 [优化说明](docs/runtime-scale-improvements.md)。

面向内网运维与业务脚本的定时任务平台，使用 Flask、APScheduler 和 Vue 3。提供登录、任务发现、调度配置、手动执行、暂停、强停、运行日志，以及 CPU/内存和任务运行时间线。

## 运行结构

- Web：提供页面与 API，可运行多个 worker。
- Scheduler：运行 APScheduler 和任务控制接口，必须只有一个 worker；Web 将控制请求转发给它。
- 每次执行：独立 Python 子进程；手动和自动执行共享任务并发限制；超时、强停与服务退出清理子进程组。
- 生产数据库：支持管理员界面配置 PolarDB for MySQL / MySQL 8.0+；保留 GaussDB/DWS 的旧配置入口。
- 本地验证：显式启用独立 SQLite 或 PostgreSQL 18.1 测试库。

生产默认 Web 8008、Scheduler 127.0.0.1:8009；WSL 本地默认 18008、18009。状态每 5 秒轮询，页面隐藏时暂停，不占用 SSE 长连接。

Web 和 Scheduler 应使用相同的 `WFS_DATA_DIR`。调度器每 2 秒原子发布 `runtime-state.json`，任务状态、事件轮询与总览优先由 Web 读取共享快照和数据库；快照缺失、未就绪或超过 15 秒时回退到控制接口。Web 读取调度器保存的资源采样，不额外启动采样线程。任务控制与代码发布仍由单实例 Scheduler 处理。

`/api/user/health` 只检查接口存活；`/api/user/ready` 分别检查数据库、调度器和数据空间，未就绪时返回 HTTP 503 及组件状态。页面独立展示接口、数据库与调度器状态，每 30 秒检查一次，普通接口请求成功不会覆盖尚未恢复的组件告警。

桌面导航可展开文字并保存选择；手机矩阵首次使用时默认二维时间图，筛选按需展开，手动选择的视图会保留。任务、执行记录、平台事件与总览已拆为独立页面，任务发布、矩阵和管理模块按需加载。

## 用户与管理员入口

- `/viewer/#tasks`：普通用户登录后只查看任务列表、详情、执行矩阵和执行记录，可筛选及收藏任务。
- `/admin/#dashboard`：管理员登录后使用全部功能，包含任务控制、发布、代码查看、账户及数据库连接设置。
- 普通用户访问管理地址会回到任务列表；后端使用只读接口白名单，管理接口、代码、任务包及所有写操作均返回 403。原 `operator` 角色也按只读用户处理，管理员可将其调整为 `viewer`。普通用户不能从管理员登录表单登录。
- 账号仍由管理员在“账户与审计”分配。环境管理员的用户名和密码摘要继续由服务环境配置管理。

## PolarDB 与数据库连接设置

管理员打开“数据库连接”分别管理平台库和业务库。地址只填主机名/IP，默认端口 3306；使用允许写入的 PolarDB 主地址或集群地址，并配置实例白名单、网络及数据库账号权限。TLS 默认校验 CA 与主机名，CA 文件需部署在所有 Web、Scheduler 和任务运行环境的同一路径。

1. **平台数据库**：固定标识 `platform`，保存任务、账号、会话、审计及执行历史。测试连接会检查 MySQL 版本、只读状态、InnoDB 表和所需字段；结构不完整不能保存。
2. **新空库初始化**：先创建独立数据库和账号。在页面填写连接信息，输入库名确认“初始化新库平台表”。服务只在没有任何 `wfs_` 平台表的新库执行 [MySQL 基线](app/bootstrap/mysql_schema.sql)，需要 CREATE/INSERT 权限。MySQL DDL 隐式提交，失败后应核对已建表，用数据库工具执行同一份幂等基线补全；不会自动删除已有表。
3. **已有库切换**：先备份并完成数据迁移，核对表结构、索引、主键和账号权限，再测试并保存。连接页不搬迁旧数据库数据。运行账号需要目标库的 SELECT/INSERT/UPDATE/DELETE 权限，建表账号可单独使用。`python scripts/migrate.py` 对 MySQL 检查当前基线，不执行 PostgreSQL/GaussDB 迁移文件。
4. **生效方式**：平台配置先保存为待生效；停止所有 Web/Scheduler 及任务进程后统一启动。应用启动时激活新配置，存量进程始终使用其启动时的连接；任务子进程不会提前采用待生效平台配置。平台切换应在维护窗口进行，不使用逐个滚动重启。
5. **业务数据库**：使用固定标识（例如现有 `mysql_orders`）保存多个连接。任务使用 `from app.common.database import NewDB`，通过 `with NewDB('mysql_orders') as db:` 连接。页面配置优先于旧 INI，同名配置修改后，下次创建 `NewDB` 时读取；已经打开的连接继续使用旧配置。直接在脚本中写死连接信息的任务仍需一次性改为使用连接标识。

连接配置保存在共享 `WFS_DATA_DIR/database-connections.sqlite3`，内容使用 Fernet 认证加密。默认从高强度 `WFS_SECRET_KEY` 派生独立密钥；生产可另设固定的 `WFS_CONNECTIONS_KEY`，所有服务保持一致。平台和业务连接使用不同的派生密钥；任务仅获得业务连接的派生密钥，不获得会话签名密钥、主配置密钥或平台连接解密能力。使用公共数据库工具的任务独立环境需要安装其依赖（包括 SQLAlchemy、PyMySQL、configobj、requests、cryptography），可复用平台依赖版本。

密码不回传浏览器；编辑时留空保留原密码。连接测试/保存错误仅返回错误码和排查提示，审计不保存请求密码。共享目录不要放入 Git；Linux 配置文件权限为 0600，Windows 应限制数据目录 ACL。备份工具会一致备份加密配置，恢复时必须另行保留原密钥，不能直接轮换或丢失密钥。

如果新平台库在重启后无法使用，可设置 `WFS_IGNORE_MANAGED_DATABASE=true` 并统一重启，临时恢复原环境/INI/SQLite 连接入口；在连接页面修正、测试并保存后，取消该覆盖并再次统一重启。覆盖期间业务连接仍按保存的配置读取。默认数据库仍从原配置启动，未保存管理配置时不会改变现有部署。

本地 MySQL 兼容性验收使用 `WFS_TEST_MYSQL=true python scripts/accept_mysql_isolated.py`：只连接本机测试端口（默认 33080，可设 `WFS_MYSQL_TEST_PORT`），使用 `WFS_MYSQL_TEST_USER` / `WFS_MYSQL_TEST_PASSWORD`；测试账号需能创建/删除独立测试库。脚本创建随机名称的新库，验证后只删除该新库，不读取现有生产连接。PolarDB 的实际网络、TLS 证书和账号权限仍需在目标环境验收。

MySQL 的显式平台写事务先锁定 `wfs_platform_lock` 中的单行，以替代旧实现的表锁；提交、回滚或断开连接都会释放该锁，避免 `LOCK TABLES` 隐式提交破坏原子性。这些短事务会串行化；本地并发正确性验证不代表生产 PolarDB 的吞吐或故障切换验收。

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
cd "/mnt/c/Users/<Windows用户名>/Documents/Github/workflow_scheduler"
python3 -m venv ~/.local/share/workflow-scheduler/.venv
~/.local/share/workflow-scheduler/.venv/bin/pip install -r requirements.txt
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
~/.local/share/workflow-scheduler/.venv/bin/python scripts/init_local_env.py
bash run.sh migrate
bash scripts/local_service.sh start
```

如果已经配置本地 PostgreSQL，请使用对应配置启动：

```bash
bash scripts/local_service.sh start .env.postgres.local
```

启动前可加载选择的环境并执行只读检查：

```bash
set -a
source .env.postgres.local  # SQLite 环境则选 .env.local
set +a
"$WFS_PYTHON" scripts/check_local_env.py --database
```

检查显示解释器、依赖、端口、空间、数据库类型与基础迁移表，不打印密码或连接凭据。端口已有服务时先用 `local_service.sh status` 核对，不必重复启动。

平台业务时间统一为 `Asia/Shanghai`（UTC+8），包含调度、记录、矩阵与默认日志日期。历史无时区时间按原业务含义保留；已有 UTC 等其他来源数据的安装应先核对来源，再安排单独迁移。本次不自动改写历史记录。普通 PostgreSQL 可显式设置 `WFS_DB_DIALECT=postgresql` 启用统计行级更新；GaussDB/DWS 保持原兼容路径。

界面提供任务更多操作、执行记录名称检索、日期快捷范围、可直接定位的任务/执行链接、总览待处理事项、二维时间图，以及持久化的“简化特效”选项。管理员可在账户与审计页检查版本容量和保留范围；此功能只做预览，不自动删除版本。详细说明见 [本轮优化与验证](docs/workspace-optimizations-2026-10-04.md)。

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

项目回归检查建议使用 `bash scripts/postgres_test_env.sh scripts/accept_postgres_isolated.py`。它为每次检查新建临时 schema，应用全部迁移，验证真实 ODBC、事务、行锁、执行写入、并发汇总和归档，结束后移除该临时 schema；不会改动正在运行页面使用的 `wfs` 数据。

测试库表结构由当前 `ddl.sql` 和全部编号迁移维护，初始化脚本会显示实际表清单。页面地址仍为 <http://127.0.0.1:18008/>。原 SQLite 数据库保留，两种配置使用独立执行数据目录；恢复 SQLite 时先停止服务，再执行 `bash scripts/local_service.sh start`。该切换不会迁移两种数据库中的数据。

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
| `WFS_SESSION_COOKIE_NAME` | 登录 Cookie 名称；同一主机运行多个独立平台时使用不同名称，本地浏览器验收已使用独立名称 |
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
- 普通用户及原操作员只读查看任务；管理员拥有全部控制、配置、代码、账户和数据库设置功能。账户禁用与权限变更实时检查。环境管理员通过服务配置管理。失败登录按 IP 和用户名/IP 组合限制，15 分钟内分别最多 20/5 次失败。
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

两种备份工具还会归档任务版本代码、独立依赖环境和 `task-data` 业务输出。使用自定义 `WFS_TASK_RELEASE_DIR` 时加 `--releases <版本目录>`；恢复后将 `data/task-packages` 复制回原版本目录。恢复跨机器时需验证 Python、操作系统和架构兼容。详见 [任务包备份说明](docs/task-packages.md)。

```bash
bash scripts/local_service.sh stop
python3 scripts/backup_local.py --database data/wfs-local.sqlite3 --data data --output backups/wfs-backup.zip
bash scripts/local_service.sh start
```

备份包含 SQLite 快照、执行状态/日志、审计待写文件和指标，并检查数据库完整性。恢复时停止服务，将 `database.sqlite3` 放回原数据库路径，将归档内 `data` 内容放回原 `WFS_DATA_DIR`；保留原 `.env.local`，其中的签名密钥和管理员摘要不在备份内。备份包含业务日志和账户摘要，请限制访问。GaussDB 需另行执行目标数据库支持的一致备份，再备份共享数据目录；此本地工具不备份生产数据库。
- `POST /api/taskinfo/updatecode`：检查 Git 更新。

### 任务代码发布

新增「任务发布」页面，支持多文件 ZIP 上传、只读差异预览、离线依赖检查、发布、代码回滚和回收站。原 Git 任务可保留编号导入，现有调度配置和日志延续使用。部署前应用 `007_task_packages.sql`；操作方式、离线依赖和数据目录见 [任务包管理说明](docs/task-packages.md)。

任务详情新增「执行流程」，可离线分析 Python 分支、循环和本地函数调用，展开跨文件流程并定位源码。使用方式与分析边界见 [任务执行流程说明](docs/task-flow.md)。
