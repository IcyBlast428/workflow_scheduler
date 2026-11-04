# systemd + GaussDB/DWS 全新部署

本手册面向 Linux x86_64、Python 3.12、systemd、unixODBC、目标版本匹配的 DWS ODBC 驱动。应用不需要 Docker；本机 PostgreSQL 测试库可以保留 Docker。

## 1. 目录与账号

```text
/srv/wfs-source/                  源码 checkout，只用于准备发布
/data/wfs/releases/<SHA>/         平台代码、构建页面、.venv
/data/wfs/current                当前版本链接
/data/wfs/shared/data/           任务发布版本、依赖环境、输出、日志和恢复文件
/data/wfs/shared/logs/           服务文件日志
/etc/wfs/wfs.env                 固定密钥、管理员密码摘要与 Nacos 配置
```

首次部署使用全新的数据库/schema 和数据目录。生产使用专用 wfs 系统账号；创建账号、目录，确保 wfs 可写 shared/data 和 shared/logs，可读代码、配置与驱动。不要让任务代码写平台源码。Web 默认 2 worker，Scheduler 固定 1 worker、1 实例。不要开启 reload、preload 或额外调度实例。

```bash
sudo useradd --system --user-group --create-home --home-dir /var/lib/wfs --shell /usr/sbin/nologin wfs
sudo install -d -o root -g wfs -m 0750 /etc/wfs /data/wfs/releases
sudo install -d -o wfs -g wfs -m 0750 /data/wfs/shared/data /data/wfs/shared/logs
sudo install -o root -g root -m 0600 deploy/wfs.env.example /etc/wfs/wfs.env
sudoedit /etc/wfs/wfs.env
```

仅首次创建配置文件，后续沿用固定密钥。分别生成 WFS_SECRET_KEY、WFS_CONNECTIONS_KEY，并使用 Werkzeug 的 generate_password_hash 生成管理员摘要。配置仅支持字面量 KEY=value，无 shell 展开。私有 PyPI 使用运维配置的 pip.conf；不要把含凭据的地址写进源码、命令参数或 Git。

## 2. GaussDB/DWS

默认 WFS_DB_ID=wfsscheduler_wfs，表示数据库 wfsscheduler、schema wfs。Nacos 的 group=gauss、data_id=gauss.wfsscheduler.wfs.json，应包含 host、port、db、schema、user、password；生产 password 按现有 Nacos 约定使用 Base64。Base64 是编码，Nacos 访问权限仍须受限。

配置 WFS_NACOS_URL、WFS_NACOS_USERNAME、WFS_NACOS_PASSWORD、WFS_DB_DRIVER=DWS、WFS_STATE_BACKEND=gauss。ODBC 驱动注册名与动态库路径必须匹配；确保服务可读取厂商客户端依赖。本机测试开关 WFS_POSTGRES_TEST 不允许用于生产配置。

唯一建表文件为 schema/gauss.sql。初始化脚本会在事务内检查目标 schema，只对空 schema 建表；已有本版基线只做检查，其他非空 schema 拒绝处理。初始化期间停止 Web 和 Scheduler，使用具有建表权限的部署账户。日常运行账号需具备读写、事务与表锁权限，初始化后可按 DBA 方案收敛建表权限。

从已经准备好依赖的版本目录执行：

```bash
.venv/bin/python scripts/service_config.py --environment-file /etc/wfs/wfs.env   --data /data/wfs/shared/data --logs /data/wfs/shared/logs --   .venv/bin/python scripts/init_database.py
.venv/bin/python scripts/service_config.py --environment-file /etc/wfs/wfs.env   --data /data/wfs/shared/data --logs /data/wfs/shared/logs --   .venv/bin/python scripts/check_gauss_platform.py
```

DBA 直接执行 SQL 时需使用一致的 schema，并完整执行 schema/gauss.sql；不要只建部分表。平台采用原生参数化 SQL、数据库事务和命名空间表锁；锁行为参见 [华为 DWS LOCK 文档](https://support.huaweicloud.com/intl/en-us/sqlreference-dws/dws_06_0234.html)。必须在目标 GaussDB 产品、版本和驱动上验证建表、事务、并发与故障恢复；本机协议测试不能替代这一步。

## 3. 准备代码与安装服务

在新版本目录建立 Python 3.12 虚拟环境，通过私有 PyPI 安装 requirements-linux-py312.lock。执行 pip check。前端执行 npm ci、npm test、npm run build，确认 app/dist 随版本完整发布。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py312.lock
.venv/bin/python -m pip check
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend test
npm --prefix frontend run build
```

首次安装：把 /data/wfs/current 指向此版本，完成上一节数据库初始化后安装服务。

```bash
sudo .venv/bin/python scripts/install_systemd.py --scope system   --project /data/wfs/current --environment-file /etc/wfs/wfs.env   --data /data/wfs/shared/data --logs /data/wfs/shared/logs --install --start
sudo systemctl status wfs.service wfs-scheduler.service
curl --fail http://127.0.0.1:8008/api/user/ready
curl --fail http://127.0.0.1:8009/api/user/ready
```

Scheduler 8009 仅绑定回环。Web 8008 通过现有 HTTPS 代理暴露；生产设置 WFS_COOKIE_SECURE=true。Web 与 Scheduler 必须共用数据库、密钥和持久目录。

## 4. 平台与任务更新

平台代码由管理员维护。scripts/deploy_release.sh 可准备不可变版本，在维护排空并停止两项服务后检查现有 GaussDB 基线并切换代码；不导入旧数据、不自动升级数据库。部署前 CI 必须完成独立数据库回归。任务使用 GitLab 审查、依赖准备和显式发布，任务新增或修改不需要重新部署平台；删除进入回收流程，输出与已发布代码分离保存。

页面入口 HTML 使用 no-store。每个版本须同时部署 HTML、manifest 和全部带摘要资源；前端检测失效模块后给出刷新入口，并保护未保存的表单。

## 5. 运维与备份

```bash
sudo journalctl -u wfs.service -u wfs-scheduler.service -n 100
sudo systemctl stop wfs.service wfs-scheduler.service
```

先开启维护模式并排空执行，再停止两项服务。使用目标产品支持的 gs_dump 等工具和同一时间窗口的共享文件备份，示例：

```bash
.venv/bin/python scripts/backup_platform.py --data /data/wfs/shared/data  --tasks app/jobs --output /backup/wfs-20261104.zip  --database wfsscheduler --schema wfs --user wfs --host DB_HOST --port 8000 --tool gs_dump
```

命令应通过同一生产环境包装器执行，以便备份收据写入 GaussDB。数据库密码使用厂商工具支持的受限认证文件，不放命令行。数据库 dump 含加密业务连接、账户摘要及业务日志，应限制访问；密钥、Nacos、ODBC、pip 配置单独安全保管。

恢复工具 scripts/restore_platform.py 仅校验归档、摘要和路径并解压到不存在的新目录，不恢复数据库，也不证明业务恢复成功。由 DBA 使用匹配的厂商 restore 工具恢复到新数据库，再配置原加密密钥、新目标连接和共享目录，检查 schema、发布版本、授权、队列和外部业务结果后启动。任何状态不确定的执行都不自动重放。
