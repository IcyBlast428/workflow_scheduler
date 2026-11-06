# /data/workflow_scheduler 引导部署

推荐从项目根目录阅读 [START-HERE.md](../../START-HERE.md)，全新 Linux x86_64 服务器以 root 运行：

```bash
cd /data/workflow_scheduler
bash deploy.sh
```

工具自动创建 Python 3.12 虚拟环境、安装锁定依赖、设置管理员密码与独立密钥、引导 Nacos 配置、初始化空 GaussDB schema、安装并检查两项 systemd 服务。默认 Web 为 8008，Scheduler 为本机 8009。

数据库由 DBA 提前创建，建库、Nacos 配置和表清单见 [DATABASE.md](DATABASE.md)。服务器须具备 Python 3.12、systemd、unixODBC，以及与目标系统匹配的 DWS 客户端。前端已构建，不需要 Node。索引和离线依赖参数、常用运维命令见入口文档。

原有 `setup_root_test.py` 保留为手动分步工具，不必再逐条运行。正式专用账号、不可变版本目录及 HTTPS 代理方案见 [systemd 手册](../../docs/systemd-deployment.md)。ZIP 包不含 Git 历史，不使用依赖 Git 的 `deploy_release.sh`。

首次任务列表为空。配置 GitLab 与任务依赖仓库后，审查、准备依赖并显式发布任务。自动调度默认关闭，业务库默认无授权。

[目标环境验收范围](VALIDATION.md)
