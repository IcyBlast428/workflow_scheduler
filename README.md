# Workflow Scheduler

Workflow Scheduler 是一个基于 `Flask + APScheduler + Vue 3` 的内网定时任务调度平台。后端负责扫描 `app/jobs/<group>/<task>/` 下的任务代码，前端负责登录、总览看板、任务配置、调度策略、任务控制、日志查询和代码更新。

生产环境推荐拆成两个进程：

- Web 管理进程：监听 `0.0.0.0:8008`，只提供页面和 API，不直接运行调度器。
- Scheduler 控制进程：监听 `127.0.0.1:8009`，单 worker 运行 APScheduler 和任务控制接口。

本地开发仍可以使用单进程模式，方便调试。

## 目录结构

```text
workflow-scheduler/
├── app/                    Flask 应用、API、调度器、配置和构建产物
│   ├── api/                用户接口与任务接口
│   ├── bootstrap/          调度注册、任务校验、数据库封装
│   ├── config/             development / production 配置
│   ├── dist/               Vue 构建产物，由 Flask/Gunicorn 托管
│   └── jobs/               任务目录，按 group/task 分层
├── frontend/               Vue 3 + Vite 前端源码
├── logs/                   本地运行日志
├── backend_dev_runner.py   Windows/本地开发启动入口
├── run.py                  Flask/Gunicorn 应用入口
├── run.sh                  Linux 命令行启动脚本
├── wfs.service             systemd Web 管理进程
└── wfs-scheduler.service   systemd Scheduler 控制进程
```

## 本地开发

先构建前端：

```powershell
cd frontend
npm.cmd install
npm.cmd run build
```

再启动后端单进程模式：

```powershell
cd ..
python backend_dev_runner.py
```

访问地址：

```text
http://127.0.0.1:8008/
```

健康检查：

```text
http://127.0.0.1:8008/api/user/health
```

Linux 本地也可以使用：

```bash
./run.sh single
```

如果需要模拟生产双进程，可以开两个终端：

```bash
./run.sh scheduler
./run.sh web
```

## Linux 部署

默认部署路径按 systemd 文件配置为 `/data/wfs`，Python 环境为 `/data/wfs/.venv/bin/gunicorn`。如果服务器路径、运行用户或 Python 环境不同，请先修改 `wfs.service` 和 `wfs-scheduler.service` 中的 `User`、`Group`、`WorkingDirectory`、`PYTHONPATH`、ODBC 环境变量和 `ExecStart`。

部署步骤：

```bash
cd /data/wfs/frontend
npm install
npm run build

cd /data/wfs
pip install -r requirements.txt
pip check

sudo cp wfs.service /etc/systemd/system/wfs.service
sudo cp wfs-scheduler.service /etc/systemd/system/wfs-scheduler.service
sudo systemctl daemon-reload
sudo systemctl enable wfs-scheduler wfs
sudo systemctl start wfs-scheduler
sudo systemctl start wfs
sudo systemctl status wfs-scheduler
sudo systemctl status wfs
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
code_branch=main
enable_scheduler=true
scheduler_control_url=
```

生产双进程模式建议通过 systemd 环境变量覆盖：

```text
WFS_ENABLE_SCHEDULER=false
WFS_SCHEDULER_CONTROL_URL=http://127.0.0.1:8009
```

管理员账号、token、头像地址、代码更新路径等也从 `app/config/*.ini` 或环境变量读取。

## 任务规范

典型任务目录：

```text
app/jobs/<group>/<task>/
├── main.py
├── README.md              # 推荐：任务说明、负责人、运行手册
└── requirements.txt       # 可选：该任务或任务组的额外依赖
```

目录命名规范：

- `<group>` 表示业务域或系统域，例如 `billing`、`databaseSync`、`opsReport`。
- `<task>` 表示 Task 名，也是默认 `PID`，例如目录 `app/jobs/billing/monthly_report/` 的默认 PID 就是 `monthly_report`。
- `PID` 是调度器和数据库统计表里的全局唯一任务 ID，只允许字母、数字、下划线和中划线。第三阶段开始不再从 `config.ini` 读取 PID，推荐直接用 `<task>` 目录名作为稳定 ID。
- `PID` 不能重复。平台扫描时会校验所有任务；只要发现重复，冲突任务都会显示为配置错误，调度器不会注册。
- `task_name`、入口文件、最大并发、超时秒数、是否启用自动调度和调度策略都在前端“配置”弹窗维护，并保存到 `wfs_task_config`。
- 新增任务后先执行“重扫新增”，确认组名、Task 名、PID 和入口文件都正确，再在前端保存调度策略。未保存调度策略的任务会保持停止状态，但仍然允许手动触发一次。

任务目录不再需要 `config.ini`。如果目录中还保留旧版 `config.ini`，平台不会再把它作为调度来源；后续请以 `wfs_task_config` 和前端配置为准。

任务发现和入口文件规则：

- 平台扫描 `app/jobs/<group>/<task>/`，默认使用 `<task>` 作为 PID。
- 如果目录里有 `main.py`，默认作为入口文件；如果只有一个 `.py` 文件，会自动作为入口候选。
- 如果入口文件缺失或不明确，任务会显示为配置异常，需要在前端配置里选择或填写入口文件。
- 未配置调度策略的任务不会被 APScheduler 自动注册，但“触发”按钮仍可立即执行一次，用于调试和上线前验证。

任务配置由 `app/bootstrap/task_loader.py` 发现和校验，调度注册入口是 `app/bootstrap/core.py` 的 `aps_start()`。任务元数据会拆分记录为 `group_name`、`folder_name`、`pid` 和 `task_name`，其中 `wfs_job_stats.pid` 是主键，`wfs_task_config.pid` 是前端运行配置主键。

推荐的新建任务流程：

1. 在 `app/jobs/<group>/<task>/` 下创建任务目录，`<task>` 建议等于 `PID`。
2. 编写 `main.py`，入口脚本应尽量幂等，失败后可重复执行或具备补偿能力。
3. 本地单独运行 `python main.py` 验证依赖和业务逻辑。
4. 启动平台后点击“重扫新增”，确认任务出现在任务列表。
5. 在任务列表点击“配置”，维护展示名称、入口文件、最大并发、超时秒数和调度策略。
6. 保存配置后，如果“启用自动调度”已打开，Scheduler 会刷新该任务并立即按策略注册；如果关闭，则任务保持停止状态。

### 前端调整调度策略

任务列表的“配置”按钮会读取当前任务运行配置和调度策略，保存后刷新单个任务调度并立即生效。第三阶段开始，`wfs_task_config` 是唯一调度配置来源；生产环境必须先执行新版 `ddl.sql` 创建该表。

当前支持：

- 周期间隔：每分钟、每小时、每 N 分钟、每 N 小时。
- 固定时间：每天固定时间、每周固定时间、每月固定日期固定时间、每月最后一天固定时间、单次指定时间。
- 时间窗口：例如 `09:30` 到 `18:15` 之间每 N 分钟执行，支持非整点边界。
- 高级规则：自定义 Cron 字段，用于覆盖更复杂的表达式。

调度弹窗会展示未来一段时间的执行点，便于保存前确认策略是否符合预期。现在开发人员只需要上传核心代码，调度、超时、启停状态和入口文件由平台维护。

## 子程序依赖管理建议

任务越来越多后，不建议所有子程序长期共用一个无限膨胀的 Python 环境。推荐按复杂度分层治理：

- 简单同质任务：继续使用项目主环境，但必须把依赖锁定在根目录 `requirements.txt`，新增依赖前确认不会影响现有任务。
- 同一业务域任务：优先按 `<group>` 维护一套依赖，例如 `app/jobs/<group>/requirements.txt`，由部署流程安装到该组专用虚拟环境。
- 依赖差异很大的任务：为单个 `<task>` 准备独立虚拟环境或容器，任务配置中后续可以扩展 `PYTHON_BIN` 指向专用解释器。
- 多任务共享逻辑：抽成内部公共包，例如 `app/jobs/_libs` 或单独 Python package，并固定版本；避免在多个任务目录复制同一段业务代码。
- 有先后关系的任务：在任务 README 中显式写清依赖关系、上游产物和失败处理方式；如果关系越来越多，后续应升级为 DAG/工作流模型，而不是靠目录顺序或命名约定隐式串联。
- 生产准入：新增任务至少完成 `python main.py` 本地验证、依赖安装验证、`PID` 唯一验证、超时配置确认和失败可重试确认。

## 常用接口

- `/api/user/health`：健康检查
- `/api/user/login`：登录
- `/api/taskinfo/dashboard`：首页总览数据
- `/api/taskinfo/state`：任务列表
- `/api/taskinfo/events`：实时事件流，推送任务状态和日志游标变化
- `/api/taskinfo/schedule`：读取、预览和保存调度策略
- `/api/taskinfo/editTask`：任务启动、暂停、强停、刷新
- `/api/taskinfo/call_task`：手动触发任务，暂停状态下也允许执行一次
- `/api/taskinfo/taskLogs`：任务执行日志
- `/api/taskinfo/systemLogs`：调度器系统日志
- `/api/taskinfo/updatecode`：执行代码更新

## 前端

前端包含总览、任务列表、调度日志和系统日志。修改前端源码后需要重新构建：

```bash
cd frontend
npm run build
```

构建产物会写入 `app/dist`，生产访问 `http://<server>:8008/` 即可。

## ODBC 配置

如果使用随项目提供的 DWS ODBC 驱动，需要在运行用户环境中设置：

```bash
export ODBCSYSINI=/data/wfs/app/config/driver/dws_odbc/etc
export ODBCINI=/data/wfs/app/config/driver/dws_odbc/etc/odbc.ini
```
