# 全新投产操作手册

本手册从空的部署目录和平台 schema 开始，适用于当前稳定版本。平台代码部署一次，业务任务随后通过页面单独发布。已有生产实例继续运行时，不执行本手册的全新安装步骤；更新与恢复另见 [systemd 运维手册](docs/systemd-deployment.md)。

## 1. 确认部署信息

| 项目 | 本版约定 |
| --- | --- |
| 服务器 | Linux x86_64，systemd，root 用户 |
| 目录 | `/data/workflow_scheduler` |
| Python | 3.12，包含 venv 和 pip |
| 平台数据库 / schema | GaussDB/DWS：`immpdb` / `wfs` |
| 连接标识 | `immpdb_wfs`（新安装默认值，可在引导中修改） |
| Nacos 配置 | 公共命名空间，group=`gauss`，dataId=`gauss.immpdb.wfs.json` |
| 服务 | 一个 `wfs.service`，内部管理 Web 和单实例 Scheduler |
| Web / 调度控制端口 | `8008` / `127.0.0.1:8009`（8009 不对外开放） |
| 代理访问示例 | `http://wfs.example.com:8000/`，域名指向 Nginx 机器 |

平台运行不需要 Node、npm 或 Docker。只有通过 GitLab clone 交付代码时才需要 Git。Nginx 可位于另一台机器并使用 Docker；它不是平台的启动依赖。

先由管理员准备 Python 3.12、unixODBC 和匹配服务器/数据库版本的 DWS ODBC 客户端。包内包含已构建前端和驱动文件，但不包含 Python 安装程序、系统软件包或完整离线 wheels。平台服务器需要能访问 Nacos、GaussDB、GitLab API 和 Nexus；代理机器需要能访问平台服务器的 8008。

## 2. 准备数据库和 Nacos

DBA 确认数据库 `immpdb` 可用，并为平台分配专用空 schema `wfs`。如果 `immpdb` 已存在，不重复建库，不清空其中其他 schema。全新平台不得复用已有任务数据的 `wfs`；如果该 schema 已被占用，应使用另一空 schema 并同步修改连接标识和 Nacos 配置。

平台表全部建在 `immpdb.wfs`，任务业务表由各业务数据库单独管理。唯一建表基线为 `schema/gauss.sql`，共 **32 张表**；安装器会自动初始化空 schema，不需要逐张手动建表。账号权限、DBA 手动建表方案及完整表名见 [数据库准备](deploy/root-test/DATABASE.md)。本版基线已包含 GaussDB 空字符串视为 NULL 时的字段定义，无需在全新安装后再运行旧修复 SQL。

在 Nacos 公共命名空间发布 JSON，group 为 `gauss`，dataId 为 `gauss.immpdb.wfs.json`：

```json
{
  "host": "高斯服务器地址",
  "port": 8000,
  "db": "immpdb",
  "schema": "wfs",
  "user": "平台数据库账号",
  "password": "数据库密码的 Base64 编码"
}
```

`port` 改为实际数据库端口。Base64 是编码，不是加密；沿用平台现有 Nacos 约定。可在受信任终端生成，不将明文密码放入命令历史：

```bash
python3.12 -c 'import base64,getpass; print(base64.b64encode(getpass.getpass("Database password: ").encode()).decode())'
```

部署时另需输入 Nacos 地址（含 `/nacos`）、Nacos 用户名和登录密码；Nacos 登录密码不是上述数据库密码，也不填 Base64。

## 3. 将发布文件放到服务器

以下两种方式选一种。先确认 `/data/workflow_scheduler` 是本次新建的目录，避免覆盖已有实例。

### 方式 A：直接解压部署 ZIP

将本次发布 ZIP 放到 `/tmp`，把示例文件名换成实际文件名：

```bash
mkdir -p /data
unzip /tmp/workflow_scheduler-发布版本.zip -d /data
cd /data/workflow_scheduler
```

ZIP 已含 `workflow_scheduler/` 这一层，不要再次解压出嵌套同名目录。不要用通配符一次解压多个版本。

### 方式 B：通过内网 GitLab 转存部署包

在交付电脑解压部署包，将完整内容提交到内网 GitLab，再在服务器 clone 到 `/data/workflow_scheduler`。必须提交同一版本的 `app/dist/`（包括 `.vite/manifest.json`）、驱动文件、`.gitattributes` 和 `PACKAGE-MANIFEST.json`。

部署包不含 `.github/`，平台运行不依赖它；`.gitlab-ci.yml` 禁止创建流水线，本阶段不启用 CI。不要提交生产 `runtime.env`、`.venv`、`data/` 或日志。

Git 转存允许 UTF-8 文本的 CRLF/LF 换行转换，但真实内容变化、文件丢失或二进制变化仍会报错。不要删除或手工重算清单来绕过报错。如果仅 clone 源码仓库而未携带部署包清单，安装器仍会检查前端构建资源，但不能据此证明完整发布包一致。

```bash
cd /data/workflow_scheduler
bash deploy.sh verify
```

脚本默认查找 `python3.12`。若服务器将 Python 3.12 命名为 `python3`，先核对版本，再使用 `WFS_DEPLOY_PYTHON=python3 bash deploy.sh verify`；后续命令同理。不要使用指向旧版 Python 的 `python`。

## 4. 创建环境、安装依赖并启动

默认平台依赖源由 `scripts/deploy.py` 的 `DEFAULT_INDEX` 指定。此索引需包含 `requirements-linux-py312.lock` 的全部兼容包及其依赖，失败不会回退公网。

推荐直接运行：

```bash
bash deploy.sh
```

安装顺序：校验文件及前端 → 创建 `.venv` → 安装锁定依赖并执行 pip check → 设置 admin 密码与固定密钥 → 输入 Nacos 与数据库标识 → 检查 DWS 驱动和平台表 → 安装、启用并启动 `wfs.service` → 检查两个进程就绪。

管理员密码至少 12 位。首次生成的配置保存在 `deploy/root-test/runtime.env`，权限为 0600；`root-test` 是保留的目录名称，实际用于本版生产部署，不需要改名。重复运行会保留密码摘要和加密密钥。

其他安装方式（三选一，不重复执行）：

```bash
# 改用另一内网索引
bash deploy.sh install --index-url https://内部仓库/repository/pypi/simple/

# 完全离线：必须是匹配 Linux x86_64 / Python 3.12 的完整 wheels
bash deploy.sh install --wheelhouse /data/wheels

# 已手动安装完锁定依赖时使用，仍检查 pip check
bash deploy.sh install --skip-dependencies
```

如需自己建虚拟环境，可执行：

```bash
python3.12 -m venv .venv
bash deploy.sh install  # 使用已创建的 .venv 安装锁定依赖并继续部署
```

安装器禁用 pip 配置文件和额外索引；需要仓库认证时使用受限 `.netrc`，或选离线 wheels。平台安装依赖与任务安装依赖是两套配置，完成本步骤后仍需在页面设置任务仓库。

## 5. 验证服务及代理访问

```bash
cd /data/workflow_scheduler
bash deploy.sh status
curl --fail http://127.0.0.1:8008/api/user/ready
curl --fail http://127.0.0.1:8009/api/user/ready
```

两个就绪接口成功后，直连地址是 `http://平台服务器IP:8008/`，登录名为 `admin`，密码是安装时设置的密码。使用 Chrome 或新版 Edge；IE/IE 模式不支持。

如果通过另一台 Docker Nginx 访问，按 [Nginx 配置说明](docs/nginx-deployment.md) 配置。示例链路为浏览器 → `wfs.example.com:8000` → Nginx → 平台 `192.0.2.10:8008`。将示例域名和 IP 换成现场地址，并把域名解析到 Nginx 机器。HTTP 部署保持 `WFS_COOKIE_SECURE=false`。

## 6. 首次登录后配置仓库并发布任务

1. **任务依赖仓库**：管理员菜单 → 平台设置 → 连接与依赖 → 依赖仓库，选择 Nexus 并保存实际 `/simple/` 索引地址；无认证时账号密码留空。初始模式是离线，不会因平台通过 Nexus 安装而自动切换。
2. **GitLab 连接**：代码更新 → GitLab 连接与目录规则，填写根地址、项目 ID/路径、目标分支 `main`、具有项目读取权限的 `read_api` 令牌，任务根目录为 `app/jobs`。仅 `read_repository` 不足以覆盖平台所用的分支和比较 API。内网 HTTP 需显式勾选允许 HTTP，然后保存并立即检查。
3. **提交任务代码**：按 `app/jobs/<任务组>/<任务目录>/main.py` 提交并合并到目标分支；同目录可有多层模块、资源和配置文件。无需 `.wfs-task.json`，任务编号由平台生成。
4. **发布入口**：任务列表 → GitLab 任务变更 → 审查并发布，选择名称与 Python 入口、获取版本，核对差异与依赖，点击“识别并安装依赖”，通过后“发布此版本”。推送代码不会自动发布或启用调度。
5. **依赖处理**：没有 `requirements.txt` 时识别 import 及引用公共模块的导入依赖。可在页面填写完整依赖清单；例如 pandas 的 `.style` 需要手动追加 `Jinja2`，当前稳定版不自动推断该可选功能。每个任务版本有独立环境，发布后复用，不继承平台环境。Nexus 缺包时按提示补齐，不改用公网。
6. **验证与调度**：先手动执行，查看结果、日志、输出文件及实际业务结果，再配置并启用调度。用到业务库的任务先配置连接和授权。平台默认不授权业务库、不自动开启重试或补跑。

“代码更新”主要显示待合并分支与平台版本差异；没填平台部署基线时可能没有平台差异，新任务仍应在任务列表审查。不要为了看到新任务而填写不确定的 SHA。

详细说明：[任务发布](docs/task-packages.md) · [依赖与 Nexus](docs/task-environments-and-nexus.md) · [多层目录与输出](docs/task-outputs-and-projects.md) · [GitLab 配置](docs/gitlab-updates.md)。

## 7. 投产完成标准与日常保管

- 服务 active，Web 和 Scheduler 就绪；代理登录正常。
- 平台库与 schema 正确，首次任务列表为空，未导入旧平台数据。
- GitLab 扫描成功，任务依赖可从内网仓库准备。
- 首个任务手动执行成功，日志/输出可查看，实际业务结果正确；再启用计划。
- 备份平台数据库、`data/`、`logs/` 和 `deploy/root-test/runtime.env`；密钥备份单独受控保管。数据库中的 GitLab、Nexus、业务连接密文需要原密钥才能恢复。

用户已反馈当前稳定版本在生产完成任务发布、手动补充 Jinja2、运行及启用调度；这不代替新服务器的驱动、网络、权限和业务验收。详细边界见 [验证范围](deploy/root-test/VALIDATION.md)。

## 8. 常见问题与命令

| 现象 | 处理 |
| --- | --- |
| 部署包文件校验失败 | 核对发布版本与完整文件，使用同一发布包；不要删除清单绕过 |
| 缺前端文件、npm/vite 报错 | 携带完整已构建 `app/dist/`；生产无需 npm 构建 |
| `libodbc.so.2` 或 DWS 库加载失败 | 安装 unixODBC，检查 `deploy/root-test/odbc/odbcinst.ini` 和驱动版本 |
| Nacos 认证/读取失败 | 核对地址、登录凭据、公共命名空间、group 和 dataId |
| 平台表已存在 | 确认是否误用了旧 schema；不要删表冒充全新安装 |
| GitLab 或发布配置无法解密 | 恢复保存配置时的原密钥；不要重新生成密钥或清空任务表 |
| 缺包或 pandas 提示需要 jinja2 | 用原代码重新准备依赖，保留完整清单并追加包，发布新版本 |
| GitLab 目标变化 | 重新检查并核对任务变化；原代码重建依赖仅在任务目录内容和绑定未变时允许发布 |

```bash
bash deploy.sh check      # 只读检查前端、依赖、连接、驱动和表
bash deploy.sh logs       # 最近服务日志
bash deploy.sh stop       # 日常停机前先在页面进入维护并排空任务
bash deploy.sh start      # 检查数据库后启动已有服务
bash deploy.sh configure  # 停机时修改 Nacos 配置，保留固定密钥
```

旧安装恢复、单任务清理、历史兼容修复不属于首次投产步骤，按 [运维手册](docs/systemd-deployment.md)、[任务清理](docs/reset-task.md) 和 [空字符串兼容说明](docs/gauss-empty-string-compatibility.md) 单独处理。不要在生产运行开发回归测试命令。
