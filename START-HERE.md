# 从这里开始：内网部署

本包是当前平台代码、已构建前端和部署工具。使用 **root + `/data/workflow_scheduler` + Python 3.12 + systemd + GaussDB/DWS**。服务器不需要 Node、Git 或 Docker。

## 首次安装：解压后执行一条命令

先准备 Linux x86_64 服务器、Python 3.12（含 venv/pip）、unixODBC，以及可访问的 Nacos、GaussDB 和 Nexus。GaussDB 数据库由 DBA 提前建立，见 [数据库准备](deploy/root-test/DATABASE.md)。ZIP 不包含 Python 安装程序、操作系统软件包或完整离线 wheels。

```bash
# ZIP 内已有 workflow_scheduler 这一层目录；仅在全新服务器上这样解压
mkdir -p /data
unzip workflow_scheduler-*.zip -d /data
cd /data/workflow_scheduler
bash deploy.sh
```

安装引导会依次：

1. 校验部署包，创建 `.venv`，从内网 Nexus 安装锁定依赖。
2. 提示设置 admin 登录密码（至少 12 位），自动生成并保存两份独立密钥。
3. 提示输入 Nacos 地址、用户名、密码和平台数据库标识，默认 `wfsscheduler_wfs`。
4. 检查 DWS 驱动与数据库，给空 schema 初始化 32 张平台表。已有本版表只检查，不清空、不迁移。
5. 安装并启动两个服务，检查两项服务就绪，输出访问地址。

完成后访问 **`http://服务器IP:8008/`**，用户名 **admin**，密码是刚才设置的密码。8009 只供本机 Web 与 Scheduler 通信。外部访问需要服务器网络允许 8008；脚本不会修改防火墙。

## 依赖仓库与离线安装

默认索引为 `http://nexus.immp.icbc/repository/pypi-hosted/simple/`，按你提供的无认证仓库配置。仓库须包含 `requirements-linux-py312.lock` 的全部依赖；安装失败不会退回公网。

```bash
# 换成其他内网索引
bash deploy.sh install --index-url https://内部仓库/repository/pypi/simple/

# 完全离线：先在相同 Linux / CPU / Python 版本准备全部 wheels 并拷入
bash deploy.sh install --wheelhouse /data/wheels

# 如果你已经手动建好 .venv 并安装了锁定依赖
bash deploy.sh install --skip-dependencies
```

手动准备虚拟环境的方法：`python3.12 -m venv .venv`，之后用 `.venv/bin/python -m pip install -r requirements-linux-py312.lock` 安装（先配置内网 pip 源）。任务自己的依赖源仍在平台管理页面设置，与平台安装源分开。

## 常用命令

全部从 `/data/workflow_scheduler` 执行：

| 命令 | 用途 |
| --- | --- |
| `bash deploy.sh status` | 查看两个服务状态 |
| `bash deploy.sh logs` | 查看最近 100 条服务日志 |
| `bash deploy.sh check` | 只读检查依赖、配置、DWS 驱动和表结构 |
| `bash deploy.sh stop` | 停止 Web 和 Scheduler；先在页面维护并排空任务 |
| `bash deploy.sh start` | 检查数据库后启动已有服务，并验证就绪 |
| `bash deploy.sh configure` | 停机时调整 Nacos 连接；保留密码摘要和密钥 |
| `bash deploy.sh verify` | 校验部署包文件，确认拷贝完整 |

配置保存在 `deploy/root-test/runtime.env`（0600）。重复安装会沿用密码和密钥。失败时修正提示的问题，再运行同一安装命令即可；脚本不会覆盖另一套服务定义，也不会在服务运行中更新依赖或建表。

## 高斯驱动与常见问题

- 缺少 Python 或 venv：先由服务器软件源安装 Python 3.12 和对应 venv/pip 组件。
- `libodbc.so.2` 缺失：安装系统 unixODBC。随包 DWS 客户端不能代替系统驱动管理器。
- DWS 库加载失败：使用与服务器和数据库版本匹配的厂商客户端。默认路径在 `deploy/root-test/odbc/odbcinst.ini`，私有路径可在 `runtime.env` 中调整 `ODBCSYSINI`、`ODBCINI`、`LD_LIBRARY_PATH`。保留原包配置以便完整性校验。
- Nacos 认证/配置失败：地址通常包含 `/nacos`，检查账号权限和 `group=gauss`、`dataId=gauss.<数据库>.<schema>.json`。
- 数据库不存在或没有权限：DBA 先建库、授权；安装脚本不会创建数据库用户或数据库。
- 浏览器无法连接：先 `bash deploy.sh status` 和 `logs`，再检查服务器 8008 的网络访问；页面 HTTPS 代理部署见 [systemd 手册](docs/systemd-deployment.md)。

## 更新与备份

这是全新安装入口。已有安装不要直接用 ZIP 覆盖运行目录：先进入维护、排空执行、停止两个服务，备份数据库、`data/`、`logs/` 和 `deploy/root-test/runtime.env`，再按运维方案更新代码。固定密钥必须保留。脚本不会自动进行数据库版本升级或回滚。

ZIP 不包含本机任务、账号、密钥、日志、输出、虚拟环境或 Git 历史；旧集成配置中的账号信息已替换为空模板。`PACKAGE-MANIFEST.json` 记录每个文件摘要以及本包是否包含未提交的工作区修改。本次前端与架构改动均随包包含，不只打包上次 Git 提交。

平台部署和任务发布分开：平台只在更新自身代码时部署；业务任务仍按现有 GitLab 审查、准备依赖、显式发布流程操作。

目标内网 Nacos、Nexus、DWS 驱动和 GaussDB 实库需现场验收；本机 PostgreSQL 协议测试不能替代它们。具体见 [验证范围](deploy/root-test/VALIDATION.md)。
