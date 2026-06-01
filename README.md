# Workflow Scheduler

Workflow Scheduler 是一个面向内网运维和业务脚本的定时任务调度平台，基于 `Flask + APScheduler + Vue 3` 构建。平台扫描 `app/jobs/<group>/<task>/` 下的任务代码，提供登录、任务列表、调度配置、手动触发、暂停强停、运行日志、系统日志、代码更新，以及总览页的 CPU/内存时间线监控。

总览页会把机器 CPU、内存使用率和任务运行时间段叠加在同一张时间图中：CPU 为蓝线，内存为黄线；成功任务为绿色运行块，失败任务为红色运行块，运行中的任务为紫色运行块。图表支持滚轮缩放时间轴、中键拖动时间轴，适合观察“任务开始执行”和“机器资源升高”之间的关系。

生产环境推荐拆成两个进程：

- Web 管理进程：监听 `0.0.0.0:8008`，提供页面和 API，不直接运行调度器。
- Scheduler 控制进程：监听 `127.0.0.1:8009`，单 worker 运行 APScheduler 和任务控制接口。

本地开发可以使用单进程模式，方便调试。

## 目录结构

```text
workflow-scheduler/
├── app/
│   ├── api/                用户接口与任务接口
│   ├── bootstrap/          调度注册、任务扫描、数据库封装、系统指标采样
│   ├── config/             development / production 配置
│   ├── dist/               前端构建产物，由 Flask/Gunicorn 托管
│   └── jobs/               任务目录，按 group/task 分层
├── frontend/               Vue 3 + Vite 前端源码
├── logs/                   本地运行日志
├── backend_dev_runner.py   本地开发启动入口
├── run.py                  Flask/Gunicorn 应用入口
├── run.sh                  Linux 命令行启动脚本
├── requirements.txt        平台主环境依赖
├── wfs.service             systemd Web 管理进程
└── wfs-scheduler.service   systemd Scheduler 控制进程
```

## 任务与依赖管理

平台主环境只应该安装“调度平台本身”需要的依赖，例如 Flask、APScheduler、数据库驱动、pandas 等。子任务依赖建议和主项目分开管理，避免某个任务升级第三方库后影响平台或其他任务。

任务目录规范：

```text
app/jobs/<group>/<task>/
├── main.py
├── README.md              # 推荐：任务说明、负责人、运行手册
├── requirements.txt       # 可选：当前任务的依赖
└── .venv/                 # 可选：当前任务的独立虚拟环境
```

也可以按任务组共享一套环境：

```text
app/jobs/<group>/
├── .venv/
├── requirements.txt       # 可选：当前任务组共享依赖
└── <task>/
    └── main.py
```

任务执行时 Python 解释器的选择顺序：

1. 如果存在 `app/jobs/<group>/<task>/.venv`，使用任务自己的虚拟环境。
2. 否则如果存在 `app/jobs/<group>/.venv`，使用任务组共享虚拟环境。
3. 否则使用平台主环境，也就是启动 WFS 的 Python。

推荐策略：

- 平台主环境：只安装 `requirements.txt`，保持稳定。
- 简单同质任务：可以直接使用平台主环境，但新增依赖前要确认不会影响现有任务。
- 同一业务域任务：使用 `app/jobs/<group>/.venv`，适合一组任务共享数据库 SDK、业务 SDK 或同版本工具库。
- 依赖差异大的任务：使用 `app/jobs/<group>/<task>/.venv`，让单个任务完全隔离。
- 共享业务代码：抽成内部公共包或共享模块，固定版本后安装到对应任务环境，不建议在多个任务目录复制同一段代码。

示例：为单个任务创建独立环境。

```bash
cd app/jobs/testJob/test_job
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Windows：

```powershell
cd app\jobs\testJob\test_job
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

示例：为任务组创建共享环境。

```bash
cd app/jobs/testJob
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

生产准入建议：

- 每个任务至少提供 `main.py`，并能独立运行。
- 依赖文件和运行环境要随任务一起维护。
- 脚本尽量幂等，失败后可重试，或具备补偿能力。
- 在前端配置合理的超时时间和最大并发。
- 任务依赖变化时，先在对应 `.venv` 验证，再刷新调度器。

## 任务发现与调度配置

平台扫描 `app/jobs/<group>/<task>/`，默认使用 `<group>__<task>` 作为 PID。PID 是任务在调度器、运行日志和统计表中的全局唯一 ID，只允许字母、数字、下划线和中划线。

入口文件规则：

- 如果任务目录里有 `main.py`，默认作为入口文件。
- 如果只有一个 `.py` 文件，会自动作为入口候选。
- 如果入口文件缺失或不明确，任务会显示为配置异常，需要在前端“配置”弹窗中选择或填写入口文件。

调度配置由前端保存到 `wfs_task_config`，不再依赖任务目录中的旧版 `config.ini`。如果旧任务仍保留 `config.ini`，可以作为迁移参考，但实际调度以数据库配置为准。

当前支持的调度策略：

- 周期间隔：每分钟、每小时、每 N 分钟、每 N 小时。
- 固定时间：每天固定时间、每周固定时间、每月固定日期固定时间、每月最后一天固定时间、单次指定时间。
- 时间窗口：例如 `09:30` 到 `18:15` 之间每 N 分钟执行。
- 高级规则：自定义 Cron 字段。

为避免项目重启后大量 interval 任务同时启动，Scheduler 批量注册 interval 任务时会为首次执行加入一个内存中的随机错峰时间。这个错峰不会写回数据库，也不会改变任务的周期策略。

推荐新增任务流程：

1. 创建目录 `app/jobs/<group>/<task>/`，任务 PID 会生成为 `<group>__<task>`，目录名确定后不要频繁改动。
2. 编写 `main.py` 和任务 README。
3. 如有特殊依赖，创建任务级或组级 `.venv` 并安装依赖。
4. 本地运行 `python main.py` 或对应 `.venv` 的 Python 验证任务逻辑。
5. 启动平台后点击“重扫新增”，确认任务出现在任务列表。
6. 在任务列表点击“配置”，维护展示名称、入口文件、最大并发、超时秒数和调度策略。
7. 保存配置后，如果“启用自动调度”已打开，Scheduler 会刷新并注册该任务。

## 本地开发

安装后端依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
```

构建前端：

```powershell
cd frontend
npm.cmd install
npm.cmd run build
```

启动后端单进程模式：

```powershell
cd ..
.\.venv\Scripts\python.exe backend_dev_runner.py
```

访问地址：

```text
http://127.0.0.1:8008/
```

健康检查：

```text
http://127.0.0.1:8008/api/user/health
```

前端开发模式：

```powershell
cd frontend
npm.cmd run dev
```

Vite 默认访问：

```text
http://127.0.0.1:5173/
```

Linux 本地也可以使用：

```bash
./run.sh single
```

如果需要模拟生产双进程：

```bash
./run.sh scheduler
./run.sh web
```

## Linux 部署

默认部署路径按 systemd 文件配置为 `/data/wfs`，Python 环境为 `/data/wfs/.venv/bin/gunicorn`。如果服务器路径、运行用户或 Python 环境不同，请先修改 `wfs.service` 和 `wfs-scheduler.service` 中的 `User`、`Group`、`WorkingDirectory`、`PYTHONPATH`、ODBC 环境变量和 `ExecStart`。

部署步骤：

```bash
cd /data/wfs
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip check

cd /data/wfs/frontend
npm install
npm run build

cd /data/wfs
sudo cp wfs.service /etc/systemd/system/wfs.service
sudo cp wfs-scheduler.service /etc/systemd/system/wfs-scheduler.service
sudo systemctl daemon-reload
sudo systemctl enable wfs-scheduler wfs
sudo systemctl start wfs-scheduler
sudo systemctl start wfs
sudo systemctl status wfs-scheduler
sudo systemctl status wfs
```

如果任务或任务组使用独立 `.venv`，部署时需要额外安装对应依赖。例如：

```bash
cd /data/wfs/app/jobs/testJob/test_job
/data/wfs/.venv/bin/python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

查看日志：

```bash
sudo journalctl -u wfs -f
sudo journalctl -u wfs-scheduler -f
```

重启服务：

```bash
sudo systemctl restart wfs-scheduler
sudo systemctl restart wfs
```

## systemd 说明

`wfs.service` 是 Web 管理进程：

```text
Environment="WFS_ENABLE_SCHEDULER=false"
Environment="WFS_SCHEDULER_CONTROL_URL=http://127.0.0.1:8009"
ExecStart=... gunicorn --workers 2 --worker-class gthread --threads 8 --timeout 120 --keep-alive 75 --bind 0.0.0.0:8008 ... run:app
```

`wfs-scheduler.service` 是 Scheduler 控制进程：

```text
Environment="WFS_ENABLE_SCHEDULER=true"
ExecStart=... gunicorn --workers 1 --worker-class gthread --threads 8 --timeout 120 --keep-alive 75 --bind 127.0.0.1:8009 ... run:app
```

Scheduler 必须保持单 worker，否则同一批任务可能被重复注册和重复执行。Web 进程可以多 worker，并通过 `WFS_SCHEDULER_CONTROL_URL` 将任务启停、手动触发、全量重载等控制操作转发给 Scheduler。

实时状态接口 `/api/taskinfo/events` 使用 SSE 长连接。systemd 服务里使用 `gthread` worker 是为了让 Gunicorn 可以长期保持事件流连接，同时继续处理普通 API 请求；如果前面还套了 Nginx，需要对该路径关闭代理缓冲，例如 `proxy_buffering off`。

## 配置

应用名称和运行参数维护在：

```text
app/config/development.ini
app/config/production.ini
```

关键配置：

```ini
[basic]
app_id=workflow_scheduler
app_name=定时任务调度

[runtime]
repo_path=/data/wfs
code_remote=origin
code_branch=workflow_scheduler
enable_scheduler=true
scheduler_control_url=
```

生产双进程模式建议通过 systemd 环境变量覆盖：

```text
WFS_ENABLE_SCHEDULER=false
WFS_SCHEDULER_CONTROL_URL=http://127.0.0.1:8009
```

管理员账号、token、头像地址、代码更新路径等也从 `app/config/*.ini` 或环境变量读取。生产环境请不要提交真实密钥或长期有效 token。

## 数据库

平台本体只维护高斯数据库连接，入口是 `app/bootstrap/database.py` 中的 `WfsDB/GaussDB`。这部分只服务 WFS 自己的运行历史、系统日志、任务统计和任务配置表，不和任务业务库混用。

任务和公共函数访问非高斯业务库时，使用 `app/common/db/` 下的连接工厂和适配器。兼容入口仍然是 `app/common/database.py` 中的 `NewDB`，当前平台主环境已内置 MySQL 适配器；Oracle、ClickHouse 等适配器位置已预留，使用时由对应任务环境安装驱动。

连接策略保持简单稳定：平台高斯库默认使用短生命周期连接，由 ODBC 驱动层处理底层连接复用；`NewDB` 使用 SQLAlchemy Engine/QueuePool 管理非高斯业务库连接。普通任务建议按任务运行周期打开和关闭连接，高频任务或需要异步 IO 的任务，建议在自己的 `.venv` 中安装对应驱动并在任务内部维护更细粒度的连接池。

任务中推荐写法：

```python
from app.common.database import NewDB

with NewDB("mysql_immpdb") as db:
    rows = db.execute_query_sql("select * from immp_cfg_user_mail_sms", return_json=True)
```

本地开发环境的业务库配置读取 `app/config/database/development.ini`，生产环境读取 `app/config/database/production.ini`。平台高斯库生产环境从 Nacos 读取 `gauss.<database>.<schema>.json`，例如默认 `sysimemedb_wfs` 对应 `gauss.sysimemedb.wfs.json`。

平台依赖 `ddl.sql` 中的运行历史、系统日志、任务统计和任务配置表。首次部署或升级后请确认目标库已执行最新 DDL，尤其是：

- `wfs_run_history`：任务执行历史和输出日志。
- `wfs_schedule_history`：调度器系统事件。
- `wfs_job_stats`：任务统计和最近状态。
- `wfs_task_config`：前端保存的任务运行配置和调度策略。

## 前端

前端包含：

- 总览：CPU/内存折线图、任务运行色块、时间轴缩放和平移。
- 任务列表：任务扫描、配置、启动、暂停、强停、手动触发。
- 调度日志：查看任务执行历史和输出。
- 系统日志：查看调度器事件和异常。

修改前端源码后需要重新构建：

```bash
cd frontend
npm run build
```

构建产物会写入 `app/dist`，生产访问 `http://<server>:8008/` 即可。

## 常用接口

- `/api/user/health`：健康检查
- `/api/user/login`：登录
- `/api/taskinfo/dashboard`：总览数据，包含 CPU/内存采样和任务运行段
- `/api/taskinfo/state`：任务列表
- `/api/taskinfo/events`：实时事件流
- `/api/taskinfo/schedule`：读取、预览和保存调度策略
- `/api/taskinfo/editTask`：任务启动、暂停、强停、刷新
- `/api/taskinfo/call_task`：手动触发任务，暂停状态下也允许执行一次
- `/api/taskinfo/taskLogs`：任务执行日志
- `/api/taskinfo/systemLogs`：调度器系统日志
- `/api/taskinfo/updatecode`：执行代码更新

## ODBC 配置

如果使用随项目提供的 DWS ODBC 驱动，需要在运行用户环境中设置：

```bash
export ODBCSYSINI=/data/wfs/app/config/driver/dws_odbc/etc
export ODBCINI=/data/wfs/app/config/driver/dws_odbc/etc/odbc.ini
```
