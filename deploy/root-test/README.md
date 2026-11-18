# 生产运行配置与数据库准备

推荐从项目根目录阅读 [START-HERE.md](../../START-HERE.md)，全新 Linux x86_64 服务器以 root 运行：

```bash
cd /data/workflow_scheduler
bash deploy.sh
```

工具自动创建 Python 3.12 虚拟环境、安装锁定依赖、设置管理员密码与独立密钥、引导 Nacos 配置、初始化空 GaussDB schema、从项目根目录唯一模板安装并检查一个以 root 用户和组运行的 wfs.service（内部管理 Web 与单实例调度器）。默认 Web 为 8008，Scheduler 为本机 8009。

数据库由 DBA 提前创建，建库、Nacos 配置和表清单见 [DATABASE.md](DATABASE.md)。服务器须具备 Python 3.12、systemd、unixODBC，以及与目标系统匹配的 DWS 客户端。前端已构建，不需要 Node。索引和离线依赖参数、常用运维命令见入口文档。

安装工具会调用 `scripts/setup_root_test.py` 完成底层配置，无需手动逐条运行。统一 root 服务、HTTP/HTTPS 代理与已有安装更新说明见 [systemd 手册](../../docs/systemd-deployment.md)。ZIP 包不含 Git 历史，部署统一使用项目根目录的 `deploy.sh`。

本目录只保留 `runtime.env`、ODBC 配置和配套说明，不再包含 service 模板。已有配置与密钥继续使用原路径，无需搬迁。

首次任务列表为空。配置 GitLab 与任务依赖仓库后，审查、准备依赖并显式发布任务。自动调度默认关闭，业务库默认无授权。

[目标环境验收范围](VALIDATION.md)

`root-test` 是沿用的路径名，不表示要在生产运行测试。新建配置默认 `WFS_DB_ID=immpdb_wfs`；已有 runtime.env 保留原数据库、密码摘要和固定密钥。无需先执行历史兼容修复脚本。
