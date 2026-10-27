# systemd 部署手册

适用版本：GitLab 任务发布分支，2026-10-27。正式应用部署采用 systemd 管理 Gunicorn Web 和独立 Scheduler；生产沿用现有 GaussDB/DWS 和私有 PyPI。Docker 只保留给本机 PostgreSQL 测试库或 CI 测试环境，不作为应用运行依赖。

## 1. 运行结构与目录

```text
用户 → 现有 HTTPS 反向代理 → wfs.service（127.0.0.1:8008，2 个 Web worker）
                                ↓ 控制请求
                          wfs-scheduler.service（127.0.0.1:8009，1 个 worker）
                                ↓
                          任务独立 Python 子进程
```

Scheduler 必须保持一个实例、一个 worker；不要使用 Gunicorn preload、热重载或另起一套容器/后台脚本。服务文件通过 Gunicorn 参数固定角色，配置文件中的旧角色设置不能让 Web 再启动调度器。两项服务共用数据库、密钥和持久目录。

```text
/srv/wfs-source/                      GitLab 源码 checkout，只用于取代码和发布
/data/wfs/releases/<完整提交 SHA>/      平台代码、已构建页面、平台 .venv，root:wfs 所有
/data/wfs/current                     指向当前平台版本的链接
/data/wfs/shared/data/                执行日志、索引、指标、配置 SQLite、任务版本和输出
/data/wfs/shared/data/task-packages/  各任务的代码历史及独立依赖环境
/data/wfs/shared/data/task-data/      各次执行输出及长期检查点
/data/wfs/shared/logs/                需要落盘的服务/业务日志
/etc/wfs/wfs.env                     固定密钥、管理员摘要、Nacos 等生产配置
/etc/wfs/wait_ready.py               systemd 就绪检查工具，与平台版本独立
```

服务标准输出、访问日志和异常由 journald 管理。业务输出仍保存在 shared/data，不随平台切换、任务更新或移入回收站而清理。

## 2. 生产服务器准备

基准为 Linux x86_64、Python **3.12**、Node.js 24、systemd、Git、curl、flock 和 unixODBC。`requirements-linux-py312.lock` 对应 Python 3.12；本机开发的 Python 3.14 不用于替代生产依赖锁基准。GaussDB/DWS 驱动需与服务器系统和目标数据库版本匹配，按现有厂商客户端要求安装其动态库。

将审批后的代码取到源码 checkout，避免在运行版本里更新代码。以下命令从源码仓库根目录执行：

```bash
id wfs >/dev/null 2>&1 || sudo useradd --system --user-group --create-home --home-dir /var/lib/wfs --shell /usr/sbin/nologin wfs
sudo install -d -o root -g wfs -m 0750 /etc/wfs /data/wfs /data/wfs/releases
sudo install -d -o wfs -g wfs -m 0750 /data/wfs/shared/data /data/wfs/shared/logs

# 已存在时保留原配置，尤其不能重新生成既有密钥
if ! sudo test -e /etc/wfs/wfs.env; then
  sudo install -o root -g root -m 0600 deploy/wfs.env.example /etc/wfs/wfs.env
fi
sudoedit /etc/wfs/wfs.env
```

配置只允许字面量 `KEY=value`，含空格或特殊字符时使用引号，不写 shell 命令、变量展开或 `source`。`.env.postgres.local` 只供本机验证，不复制为生产配置。

首次安装可以用 Python 标准库生成两个独立随机密钥，每项单独执行一次并填入配置：

```bash
python3.12 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

`WFS_SECRET_KEY`、`WFS_CONNECTIONS_KEY` 必须固定并另行备份。升级时沿用原值；原安装未设独立连接密钥时，保持原派生方式，不能直接补一个新值，否则已有加密连接、GitLab 和依赖仓库配置无法解密。

## 3. 生产数据库与私有依赖源

当前 GaussDB/DWS 生产入口保持原有 Nacos 读取方式：

- `WFS_DB_ID=<数据库>_<schema>` 对应 Nacos 的 `gauss.<数据库>.<schema>.json`，group 为 `gauss`。
- 配置 `WFS_NACOS_URL`、用户名和密码；JSON 保留现网的 host、port、db、schema、user、password 字段及兼容的 Base64 密码格式。
- `WFS_DB_DRIVER=DWS` 与 `odbcinst.ini` 中的驱动名称对应。服务使用当前版本内的 ODBC 配置；发布脚本将驱动库路径改为该版本的固定路径。
- `WFS_DB_CONFIG_FILE`、`WFS_DB_PASSWORD` 是现有开发环境入口，不是生产 Nacos 的替代设置。生产不设置 `WFS_LOCAL_DB_PATH`、`WFS_POSTGRES_TEST` 或 `WFS_DEV_RUN_ALL`。
- 新数据库需由 DBA 先建立独立库/schema 和账号，并在对应产品上核对、执行 `ddl.sql`。增量迁移不是自动创建空 GaussDB 平台库的替代步骤。

不要因为部署方式变化切换生产数据库类型。普通 PostgreSQL 测试通过，不代表生产 DWS 驱动、分布式事务、索引或查询计划已经验收。

平台依赖安装使用运维维护的 pip 配置，例如 `/etc/wfs/pip.conf`：

```ini
[global]
index-url = http://nexus.immp.icbc/repository/pypi-hosted/simple/
trusted-host = nexus.immp.icbc
disable-pip-version-check = true
```

按现网情况改为 HTTPS 和内部 CA；需要认证时保护该文件，避免在命令行或 Git 中填写密码。不配置公网 extra-index。**平台构建依赖**使用此 pip 配置；**任务独立环境依赖**由平台导航「依赖仓库」配置，两者分别管理。

平台准备阶段还会执行 `npm ci`、前端测试和构建。封闭网络需提供可用的 npm 镜像/缓存；只有 Python wheels 并不足以完成前端构建。Python 完全离线时可额外设置绝对路径 `WFS_DEPLOY_WHEELHOUSE`。

## 4. 首次部署

### 4.1 准备固定版本

先将源码 checkout 切到已审批的提交，再保存完整 SHA。准备阶段可在旧服务运行时执行，不读取生产配置中的数据库凭据、不迁移生产数据库、不切换 current 或重启服务。

```bash
APP_SHA="$(git rev-parse HEAD)"
sudo env PIP_CONFIG_FILE=/etc/wfs/pip.conf WFS_DEPLOY_PYTHON=/usr/bin/python3.12 \
  bash scripts/deploy_release.sh --prepare "$APP_SHA"
```

脚本将固定提交导出到最终版本目录，安装锁定的平台依赖，执行后端测试、前端测试和构建，完成后写入 `.release-ready`。已有目录不会覆盖，失败产物保留以供排查。不要移动已经建立 `.venv` 的版本目录。

新安装的管理员密码摘要可使用已准备好的 Python 环境生成，密码在终端交互输入，不放进命令行：

```bash
sudo "/data/wfs/releases/$APP_SHA/.venv/bin/python" -c \
  'from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass("管理员密码: ")))'
sudoedit /etc/wfs/wfs.env
```

填好所有 `CHANGE_ME` 字段后再启动。已有安装沿用现有管理员摘要。

### 4.2 安装服务定义

```bash
sudo python3 scripts/install_systemd.py --install
```

安装器生成 `wfs.service` 与 `wfs-scheduler.service`，安装共享就绪工具，并执行 daemon-reload；默认**不启动**。首次部署时 current 可以尚不存在，下一步激活后才引用有效的版本目录。根目录两份 `.service` 文件与默认生成内容一致，便于审阅。

旧服务器若已有手工安装的同名 unit，先备份并移开这两份文件，再安装；安装器拒绝覆盖未由本工具管理的服务定义。变更目录、账号或端口时先生成审阅文件：

```bash
python3 scripts/install_systemd.py --output /tmp/wfs-unit-review
# 自定义路径示例；配置、共享目录与部署脚本的 base 必须一致
sudo python3 scripts/install_systemd.py --project /custom/wfs/current \
  --data /custom/wfs/shared/data --logs /custom/wfs/shared/logs --install
```

默认端口固定为 8008/8009，均仅监听回环地址。确需修改时，安装器的 `--web-port/--control-port` 与激活脚本的 `WFS_DEPLOY_WEB_PORT/WFS_DEPLOY_CONTROL_PORT` 必须相同，代理地址也同步调整。

### 4.3 维护窗口内激活

停止新的任务发布/手动执行、暂停自动调度并等待活动实例结束。停止两个服务，在同一维护窗口完成数据库一致备份、shared 文件备份和配置密钥备份。首次空库部署也需核对基线表已建立。

```bash
sudo systemctl stop wfs.service wfs-scheduler.service
# 此处按现网 DBA 流程备份数据库，并备份 shared 和 /etc/wfs 配置
sudo bash scripts/deploy_release.sh --activate "$APP_SHA"
sudo systemctl enable wfs-scheduler.service wfs.service
```

激活脚本先确认两项服务已停止，才加载生产配置，应用增量迁移并核对旧任务迁移情况；随后切换 current，启动 Scheduler 和 Web。两项服务都需通过真正的 `/api/user/ready` 检查，单纯端口监听或返回登录页面不算成功。

`deploy_release.sh <SHA>` 仍可一次完成准备和激活，但激活前同样要求两个服务已停止。日常升级推荐分两步，缩短维护窗口。

已有旧目录任务时，先按[旧任务的一次性迁移](platform-releases.md#旧任务的一次性迁移)完成编号、依赖、版本注册与历史核对；激活检查不通过时不要跳过保护。生产 DWS 初次上线需在实际网络中验收 Nacos、ODBC、数据库和业务连接。

## 5. 日常操作、升级和回退

```bash
sudo systemctl status wfs.service wfs-scheduler.service --no-pager
sudo journalctl -u wfs.service -u wfs-scheduler.service -n 100 --no-pager
sudo journalctl -u wfs.service -u wfs-scheduler.service -f
curl --fail http://127.0.0.1:8009/api/user/ready
curl --fail http://127.0.0.1:8008/api/user/ready
```

异常退出由 systemd 重启；反复启动失败可能触发启动频率限制，修复配置后执行 `systemctl reset-failed` 再启动。停止给 Gunicorn 60 秒退出宽限，90 秒后 systemd 清理剩余服务进程。正常维护必须先等待任务结束，停服务不代表可以让正在写业务数据的任务无损继续。

平台升级重复「准备固定版本 → 维护窗口与备份 → 激活 → 两端就绪 → 低风险业务验收 → 恢复调度」。不要 HUP/热重载 Scheduler，也不要在正在使用的 release 目录执行 `git pull`。shared 数据、任务环境及输出路径保持不变；平台 Python 大版本、系统或架构变化需单独重建和验证任务环境。

激活失败会先停止新服务，再恢复旧 current 链接并尝试启动旧服务。**此操作只回退平台代码，不撤销数据库迁移**；仅支持经验证的向后兼容迁移。旧服务恢复后仍需核对就绪与数据。首次激活失败时没有旧版本，服务保持停止，文件保留排查。

手工回退也在维护窗口进行，备份后将 current 原子切回已验证的旧 release，再统一启动两项服务。结构不兼容时由 DBA 恢复配套备份，不能只改链接。发布工具不自动删除旧平台版本、任务版本、回收站或输出。

## 6. HTTPS、GitLab 任务和备份

生产通过现有 HTTPS 代理转发到 `127.0.0.1:8008`，不对外暴露 8009。生产服务固定安全 Cookie，需要通过 HTTPS 登录；不要用修改生产 Cookie 配置来掩盖代理未部署的问题。本机开发服务仍允许 HTTP。

GitLab 任务发布与平台投产分开：在「代码更新」设置项目、只读令牌和目标分支；在独立「依赖仓库」设置私有 PyPI；任务合并后到「任务列表」审查新增、修改或删除。管理员确认后才发布/移入回收站。ZIP 上传已移除，「任务示例」只用于编写、维护和下载示例，详见[任务发布手册](task-packages.md)。

发布任务读取固定提交并创建新版本，不对运行目录执行 Git 更新或清理。目录中多出的输出文件不会阻碍任务更新/删除；已有实例固定旧版本完成，长期输出保留在 task-data。

备份必须配套保存：生产数据库一致备份、完整 shared 数据（含 task-packages、task-data、执行索引、三份加密配置 SQLite）及原配置密钥。DWS 数据库使用当前产品配套工具和已演练的 DBA 流程，不能将本机 PostgreSQL 的 pg_dump 命令直接视为 DWS 备份验收。恢复先到新目录/新库校验，再在停服窗口切换；恢复任务环境需保持原绝对路径和相容的 Python/系统。

## 7. 本机 WSL：用户级 systemd

本机使用 `systemctl --user`，无需修改生产服务或管理员密码；继续沿用原 PostgreSQL 容器、账号、密钥、任务版本和数据目录。当前名称为 `wfs-local.service`、`wfs-local-scheduler.service`，页面仍是 `http://127.0.0.1:18008/`。

首次安装前停止旧后台脚本启动的进程，先确保 Docker Desktop 和原测试数据库就绪。旧的 18018 容器预览 Web/Scheduler 已停用且取消自动重启，数据库和数据卷保留。

```bash
cd /mnt/c/Users/你的用户名/Documents/Github/workflow_scheduler
bash scripts/local_service.sh stop .env.postgres.local
# 已有容器的启动；没有容器时按 README 的测试库首次初始化流程操作
docker start wfs-postgres18-test  # WSL 集成不可用时可用 docker.exe
python3 scripts/install_systemd.py --scope user --project "$PWD" \
  --environment-file "$PWD/.env.postgres.local" --install --start
```

若使用原 SQLite 开发环境，替换为 `.env.local`，不要为了切换服务管理方式迁移数据库。安装器只读取已有配置，把字面量设置写入 Linux 用户配置目录的 0600 文件；不会重新生成密钥或密码。更改原 `.env` 后重新执行安装器同步，再重启服务。

```bash
systemctl --user status wfs-local.service wfs-local-scheduler.service --no-pager
systemctl --user stop wfs-local.service wfs-local-scheduler.service
systemctl --user start wfs-local-scheduler.service wfs-local.service
systemctl --user restart wfs-local-scheduler.service wfs-local.service
journalctl --user -u wfs-local.service -u wfs-local-scheduler.service -f
```

用户服务已 enable，随该用户的 systemd 会话启动；WSL 关闭后进程仍会结束，不等于 Windows 开机自动启动 WSL/Docker。需要无需交互登录的 WSL 用户服务时，由管理员确认后使用 `loginctl enable-linger <用户名>`，同时确保测试数据库启动。生产服务器使用系统级服务，不依赖个人登录会话。

本机 PostgreSQL 备份需同时保留测试库、原数据目录和配置。下面只针对既有本机测试容器；`docker` 不可用时用 `docker.exe`。先等待任务完成，备份后再启动两项用户服务：

```bash
systemctl --user stop wfs-local.service wfs-local-scheduler.service
BACKUP_DIR="$PWD/backups/systemd-$(date +%Y%m%d-%H%M%S)"
(
  set -e
  umask 077
  mkdir -p "$PWD/backups"
  mkdir "$BACKUP_DIR"  # 已存在时失败，不覆盖
  docker.exe exec wfs-postgres18-test pg_dump -U wfstest -F c -n wfs wfstest > "$BACKUP_DIR/database.dump"
  tar -czf "$BACKUP_DIR/data.tar.gz" -C "$PWD/data/postgres-test" .
  tar -czf "$BACKUP_DIR/config.tar.gz" .env.postgres.local .wfs-secrets
) && systemctl --user start wfs-local-scheduler.service wfs-local.service
```

先确认全部备份步骤成功再启动，失败时保留现场。恢复先到新库/新目录核对，原路径、账号和密钥保持一致；不要直接覆盖正在运行的数据。

## 8. 常见故障与验证范围

| 现象 | 检查方向 |
| --- | --- |
| 服务启动后马上退出 | journal 中的 Python/依赖、配置路径、密钥与文件权限；确认服务 Python 可执行 |
| 启动卡在就绪检查，最终失败 | 分别请求 Scheduler/Web 的 ready，检查数据库、Nacos/ODBC、迁移表、共享磁盘空间 |
| 端口冲突或出现两套任务 | 停止旧 nohup 进程/容器预览，只保留一套 Scheduler；不要同时使用旧启动脚本 |
| 代码更新后任务数量为零 | 核对原 WFS_DATA_DIR、任务注册表、task-packages 路径及旧任务迁移，不能指向新的空目录 |
| 登录失败或加密配置无法解密 | 保留原密钥/管理员摘要；生产通过 HTTPS；本机确认已同步原开发配置 |
| 依赖准备失败 | 检查独立「依赖仓库」配置、私有 PyPI wheel 兼容性及版本目录 prepare.log |
| systemd 服务已 enable 但 WSL 重启后未运行 | 检查用户会话/linger 和 Docker Desktop 数据库启动顺序 |

安装和重启行为以 [systemd service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)、[执行环境说明](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)为依据。本次在本机 WSL 实测用户服务和 PostgreSQL；生产系统级账号、HTTPS、GaussDB/DWS、Nacos 和厂商驱动仍需在实际服务器验收。
