# /data/workflow_scheduler 全新测试部署

此方案使用 Linux root、Python 3.12、systemd、GaussDB/DWS 和私有 PyPI，应用不需要 Docker。正式专用账号部署见 docs/systemd-deployment.md。

1. 解压干净代码到 /data/workflow_scheduler，建立 .venv，通过私有 PyPI 安装 requirements-linux-py312.lock，执行 pip check。前端使用已构建 app/dist，或 npm ci、npm test、npm run build。
2. 运行 `.venv/bin/python scripts/setup_root_test.py`，交互设置至少 12 位管理员密码；生成固定密钥和 deploy/root-test/runtime.env，权限 0600，登录名 admin。不要将该文件提交 Git。
3. 填好 runtime.env 中的 Nacos、GaussDB 与 DWS 驱动配置。按 [数据库说明](DATABASE.md) 初始化全新的 schema/gauss.sql 基线并检查 32 表。使用新数据库/schema 和新 data 目录，无数据迁移。
4. 执行 `.venv/bin/python scripts/setup_root_test.py --install`，工具先检查真实 GaussDB 与表结构，再安装启动 wfs-scheduler.service 和 wfs.service。Scheduler 8009 仅监听回环，Web 8008 提供页面。

```bash
systemctl status wfs.service wfs-scheduler.service
curl --fail http://127.0.0.1:8008/api/user/ready
curl --fail http://127.0.0.1:8009/api/user/ready
journalctl -u wfs -u wfs-scheduler -n 100 --no-pager
```

首次任务列表为空。配置 GitLab 与依赖仓库后，在任务列表审查、准备依赖并显式发布。任务自动调度默认关闭，业务连接默认无权限，任务 DDL 只展示与记录，不自动执行。

更新时维护排空、停止两项服务，配套备份 GaussDB 与共享文件，沿用固定密钥和原路径。平台代码、任务版本与输出分别管理。ZIP 包不含 Git 历史，不使用依赖 Git 的 deploy_release.sh。

实际 GaussDB 驱动、版本、锁行为与集群故障恢复验收要求见 [VALIDATION.md](VALIDATION.md)。
