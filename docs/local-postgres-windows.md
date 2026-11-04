# Windows 本机 PostgreSQL 验证

本机使用 Docker PostgreSQL 18.1 替代 GaussDB 协议进行功能验证。平台主表、配置、队列及执行索引均进入 PostgreSQL，`WFS_STATE_BACKEND=gauss`，不创建 SQLite 状态文件。生产仍使用 [root + GaussDB 部署流程](../deploy/root-test/README.md)，本入口不读取生产 Nacos，也不修改 `.env.local`。

## 启动

先启动 Docker Desktop 的 Linux 容器引擎。使用已有 `.venv`，并安装原生 PostgreSQL 驱动：

```powershell
.venv/Scripts/python.exe -m pip install "psycopg[binary]==3.3.6"
docker pull postgres:18.1
.venv/Scripts/python.exe scripts/local_postgres.py prepare
.venv/Scripts/python.exe scripts/local_postgres.py serve
```

浏览器访问 <http://127.0.0.1:18008/>。原本占用 18008 的本机平台应先正常停止，避免同时启动两个调度器。

首次准备只复用 `.env.local` 的管理员用户名、密码摘要及会话密钥；不会复用其中的旧数据库连接。新检出且没有该文件时，可先执行 `python scripts/init_local_env.py` 生成本机凭据，保存当次输出的密码。该初始化器中的旧 SQLite 环境项不会被 PostgreSQL 启动入口加载，也不会因此创建 SQLite 文件。

本机资源固定为：

- 容器 `wfs-postgres-native`，镜像 `postgres:18.1`，仅监听 `127.0.0.1:15432`。
- 数据库 `wfstest`，schema `wfs`，初始化基线与全部迁移后共 32 张平台表。
- Docker 持久卷 `wfs-postgres-native-data`，配置及独立数据目录 `data/postgres-native/`。
- 单进程本机 Web + Scheduler；只用于开发验收，正式环境仍拆为两个 systemd 服务。

`prepare` 可重复执行，不清空已有表或卷。不要单独删除 `environment.json`、`container.env` 或密钥；它们与数据库卷配套，丢失后不能重新生成相同密码及解密密钥。整个 `data/` 已由 Git 忽略，不提交本机密码、任务输出或日志。

## 功能验收

在另一个终端执行：

```powershell
.venv/Scripts/python.exe scripts/accept_postgres_native.py
.venv/Scripts/python.exe scripts/check_postgres_http.py
```

第一项验证真实事务回滚、并发状态锁、密文配置、`NewDB('pg_local')` 查询及断库后的 JSON 恢复补写，并通过发布流程安装两个安全示例：文件输出、多层目录任务。其自动调度均关闭。第二项使用真实 HTTP 登录并手动执行，验证 CSV / JSON / LOG 预览和下载。执行结果保留在本机平台中。

HTTP 验收默认使用 `admin` 和本机忽略文件 `data/local-login.txt` 中的 `Password: ...`。新检出环境须自行保存本机登录凭据后再运行，文件内容不应提交。已有业务任务或修改过示例时，不应直接运行这两个会写入演示配置的验收脚本。

浏览器验收使用单独配置，不会混入默认前端测试；先安装前端依赖，再在 PowerShell 中运行：

```powershell
$env:WFS_LIVE_POSTGRES_TEST = 'true'
$env:WFS_BROWSER_EXECUTABLE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
npm --prefix frontend run test:e2e:postgres
```

检查登录、任务执行详情、CSV 在线预览与下载、业务连接以及依赖配置重载。截图保存在 `data/postgres-native/browser-acceptance.png`。本机测试通过不等同于 GaussDB/DWS 驱动、集群锁及 Linux systemd 已完成实机验收。
