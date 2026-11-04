# 本机协议测试环境

正式平台仅运行于 GaussDB/DWS。本机没有目标 GaussDB 服务，因此开发验证显式使用 PostgreSQL 18.1；它只验证共用 SQL、事务和界面，不能证明 DWS 驱动或生产环境已验收。

独立测试容器 wfs-gauss-dev，端口 127.0.0.1:15433，数据库 wfstest。配置与数据目录为忽略提交的 data/gauss-dev，不读取生产 Nacos，也不搬迁旧数据。

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe scripts/local_postgres.py prepare
.venv\Scripts\python.exe scripts/test_backend.py
```

WSL 使用项目虚拟环境安装 requirements-test.txt。应用以 scripts/install_systemd.py 安装 Web 与 Scheduler 用户服务，配置使用同一独立测试库和新数据目录。Windows 开发可显式运行 scripts/local_postgres.py serve，切勿与 systemd 同时启动调度器。

后端回归每次建立随机 test_* schema，结束后删除该 schema，运行前确认本机测试容器可用。CI 使用显式 WFS_CI_POSTGRES=true、PGDATABASE=wfstest、PGPASSWORD 和 PGPORT。前端浏览器测试也使用独立 schema。测试凭据和密钥不提交 Git。
