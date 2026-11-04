# root + GaussDB 固定目录部署

工作目录 `/data/workflow_scheduler`；root 用户；虚拟环境 `.venv`；访问 `http://服务器IP:8008/`。Web 监听 0.0.0.0:8008；单实例 Scheduler 只监听 127.0.0.1:8009。防火墙仅向需要的内网客户端开放 8008。root 启动的业务任务也有 root 权限，只发布可信脚本。

平台主库使用 GaussDB/DWS。WFS_STATE_BACKEND=gauss 将连接配置、发布设置、队列和索引全部保存至 GaussDB，生产不再创建或读取 SQLite 配置/索引文件。普通日志、输出和恢复暂存仍在 data 目录，详见[数据库及表清单](DATABASE.md)。

## 1. 解压和安装依赖

在独立 Linux x86_64 测试机直接解压到 `/data/workflow_scheduler`，不要再套一层目录。服务器准备 Python 3.12、venv/pip、systemd、unixODBC 及厂商驱动要求的系统库。前端已构建，不需要 Node/npm、Git、wfs 系统账号或 current 软链接。

```bash
cd /data/workflow_scheduler
python3.12 -m venv .venv
.venv/bin/python -m pip install --index-url http://nexus.immp.icbc/repository/pypi-hosted/simple/ \
  --trusted-host nexus.immp.icbc -r requirements-linux-py312.lock
.venv/bin/python -m pip check
```

完全离线时改用匹配 Linux/Python3.12/CPU 的完整 wheels：
`.venv/bin/python -m pip install --no-index --find-links=/path/to/wheels -r requirements-linux-py312.lock`。
本 ZIP 不含 Python/systemd 安装包或完整 wheels；仓库附带的 DWS 驱动必须在目标系统核对，必要时替换为厂商匹配版本。

## 2. 初始化管理员与 GaussDB 连接

```bash
.venv/bin/python scripts/setup_root_test.py
```

首次提示设置并确认至少 12 位管理员密码。登录名 admin；自动生成固定密钥和 `deploy/root-test/runtime.env`（0600），不保存明文管理员密码。重复运行保留旧配置及密钥。

编辑该文件，填写实际 `WFS_DB_ID`、`WFS_NACOS_URL`、`WFS_NACOS_USERNAME`、`WFS_NACOS_PASSWORD`，替换所有 CHANGE_ME。特殊字符按 systemd EnvironmentFile 字面量规则加引号，不使用 shell 展开。当前生产适配器按现有 Nacos 读取 GaussDB，不能只填主机后跳过 Nacos。

默认例子：独立平台数据库 **wfsscheduler**，schema **wfs**，设置 `WFS_DB_ID=wfsscheduler_wfs`；对应 Nacos dataId **gauss.wfsscheduler.wfs.json**，group **gauss**，当前代码使用默认 namespace。JSON 字段：host、port、db、schema、user、password；password 沿用当前生产代码要求的 Base64 编码（仅编码，不是加密），通过受保护的 Nacos 管理，勿写入源码。

配置中的 ODBCSYSINI/ODBCINI 已指向本包 `deploy/root-test/odbc`，DWS 驱动绝对路径已设为 `/data/workflow_scheduler/app/config/driver/dws_odbc/lib/odbc/psqlodbcw.so`。替换驱动时同步核对该配置及系统库。

## 3. DBA 建库建表，再执行增量迁移

先按 [DATABASE.md](DATABASE.md) 在 GaussDB 的独立平台库中创建 wfs schema 与基线表。不是业务库，也不是 Nacos 的数据库；已有平台库不得重复执行初始 ddl.sql。

基线完成、两个服务停止且已备份后，执行增量迁移：

```bash
.venv/bin/python scripts/service_config.py \
  --environment-file /data/workflow_scheduler/deploy/root-test/runtime.env \
  --data /data/workflow_scheduler/data --logs /data/workflow_scheduler/logs -- \
  /data/workflow_scheduler/.venv/bin/python scripts/migrate.py
```

该命令会修改指定平台库，只对确认好的测试库或经过审批的升级库执行。GaussDB 产品、版本、驱动兼容性仍需现场验收，不将普通 PostgreSQL 测试视为真实高斯验收。

## 4. 安装并启动 service

```bash
.venv/bin/python scripts/setup_root_test.py --install
```

程序先检查 GaussDB 连接和 32 张平台表可读，检查不通过不安装/启动服务；不自动执行初始 DDL，不回退到 SQLite。成功后安装并开机启用 wfs-scheduler.service、wfs.service。若已有不同的同名服务则拒绝覆盖，先核对旧部署。两项服务每次启动都执行 GaussDB 表检查和 ready 检查。

```bash
systemctl status wfs.service wfs-scheduler.service
curl --fail http://127.0.0.1:8008/api/user/ready
curl --fail http://127.0.0.1:8009/api/user/ready
journalctl -u wfs -u wfs-scheduler -n 100 --no-pager
```

浏览器打开 http://服务器IP:8008/，使用初始化时的 admin 密码。此直接 HTTP 配置 WFS_COOKIE_SECURE=false；接 HTTPS 后可改 true。只有一个 Scheduler，不同时运行 run.py、旧后台程序或另一套容器。

首次没有已发布业务任务。“代码更新”配置内网 GitLab，“依赖仓库”配置任务 Nexus，再在任务列表审查并发布。任务业务库和业务表单独管理，平台不会执行任务的 DDL 草稿。

## 升级与备份

升级前先停 Web、再停 Scheduler，等待任务完成，配套备份 GaussDB 平台库、data、logs、runtime.env 和密钥。不要覆盖已有 data/logs/runtime.env。配置修改后统一重启两个服务；不要重新生成已有密钥。启动顺序是 Scheduler 后 Web。

```bash
systemctl stop wfs.service wfs-scheduler.service
systemctl start wfs-scheduler.service wfs.service
```

ZIP 无 Git 历史，不直接使用依赖 Git 的 deploy_release.sh。原非 root 标准部署仍保留，见 docs/systemd-deployment.md。
