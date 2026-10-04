# 任务包管理

管理员打开「任务发布」管理任务代码，或在任务详情中点击「管理代码版本」。代码仍然只读，以完整 ZIP 作为发布单位。

## 新增、更新与删除

1. **新增**：填写名称、分类、目录名称，上传完整 ZIP。系统检查文件路径、大小、Python 语法，保存草稿；选择 Python 入口并点击「检查依赖环境」。检查通过后确认发布，新任务进入任务列表，自动调度默认未配置。可手动触发验证业务效果，再配置调度。
2. **更新**：选择任务、展开「上传新版本」，上传全部文件。文件清单区分新增、修改、删除，文本提供只读差异。检查依赖后确认发布，保留现有调度配置、编号和日志。如果当前配置的入口在新包中缺失，发布会拒绝，请保留原入口。
3. **回滚**：在版本历史中选择曾成功发布的版本，核对与当前版本的差异，确认「回滚到此版本」。只回滚代码；调度策略可在任务详情的「配置历史」中单独恢复。
4. **删除**：任务移入回收站，停止后续自动调度和新的手动执行。已排队、正在运行的实例仍用原版本完成，代码、配置、历史日志均保留。恢复任务后调度保持暂停，不自动补跑。
5. **现有 Git 任务**：点击「导入版本管理」。复制当前完整代码、保留原 PID；首次发布前仍使用原 Git 目录。首次发布后 Git 扫描不再覆盖该任务，即使删除后原目录还在，也不会重新出现。原 Git 目录不删除。

任务发布需要管理员角色。配置 `WFS_TASK_PUBLISHERS=alice,bob` 可进一步限定允许发布的管理员；不填写时允许所有管理员。普通查看者、操作员只能通过只读接口查看版本。

## ZIP 内容与离线依赖

```text
daily_report/
  main.py
  helpers.py
  sql/query.sql
  README.md
  requirements.txt       # 有第三方依赖时必需
  wheels/*.whl           # 或通过服务端离线依赖库提供
```

可以包含一层外部目录，上传时会识别并移除共同外层目录。拒绝符号链接、重复/大小写冲突路径、绝对路径、上级路径、特殊文件和加密文件。请去掉 `.git`、`.venv`、`__pycache__`、`.wfs-task.json`、`.env` 等本地环境文件。没有 Python 文件的包不能发布；单个 Python 文件最大 2 MiB。

每个版本建立独立 Python 虚拟环境，**不会继承平台或原任务环境里的第三方包**。没有 requirements.txt 时只有标准库与环境自带的 pip。现有任务用到平台帮助模块时，也需要列出这些模块使用的第三方依赖。

requirements.txt 每个有效行必须为 `package==version`。需要列出全部间接依赖，不能写网络地址、可编辑安装、其他文件路径或安装参数。安装使用 `--no-index --no-deps --only-binary=:all:`，随后执行 `pip check`；不会自动联网解析或下载，也不会运行源码包构建脚本。离线 wheels 必须匹配服务器 Python 版本、Linux/Windows 和 CPU 架构。依赖准备最多并行两个版本，失败可重试，当前生效版本不受影响。

检查包括 Python 语法、完整文件校验、依赖安装和依赖一致性，**不会执行业务代码**；数据库连接、邮件网关等业务行为需要发布后显式手动验证。

## 数据输出与部署

Linux 上准备好的代码文件和目录设置为只读，并禁止运行时生成 Python 缓存。业务输出请使用独立目录：

```python
import os
from pathlib import Path

data = Path(os.environ['WFS_TASK_DATA_DIR'])
(data / 'result.txt').write_text('业务输出', encoding='utf-8')
```

`WFS_TASK_DATA_DIR` 固定为 `<WFS_DATA_DIR>/task-data/<PID>`，更新、回滚和恢复都不改此目录。入口的工作目录仍为入口文件所在目录，便于读取相邻 SQL、模板和资源。需要写入相对目录的旧任务，应在导入发布前改成独立数据目录。

版本放在 `<WFS_DATA_DIR>/task-packages/<PID>/releases/<版本>/`，与平台 Git 发布目录分开。每个排队或自动调度实例固定代码路径和解释器路径，发布切换不会让旧实例读到新模块。解释器使用服务器已安装的 Python 基础运行时；跨 Python 大版本升级仍需按部署计划验证。

发布先记录意图，再切换调度器，收到确认才显示生效；失败恢复上一版本。服务重启发现未完成发布会恢复之前版本，未完成依赖准备显示失败，可重试。新依赖准备使用新的尝试目录，避免中断过程覆盖重试结果。

| 设置 | 默认 | 说明 |
|---|---|---|
| `WFS_TASK_RELEASE_DIR` | `<WFS_DATA_DIR>/task-packages` | 版本目录，Web/Scheduler 设置必须一致 |
| `WFS_TASK_WHEELHOUSE` | 不设置 | 管理员维护的离线 wheel 目录 |
| `WFS_TASK_PUBLISHERS` | 不设置 | 允许发布的管理员用户名，逗号分隔 |
| `WFS_PACKAGE_UPLOAD_MB` | 64 | ZIP 上传上限 MiB |
| `WFS_PACKAGE_EXPANDED_MB` | 256 | 解压文件总大小上限 MiB |
| `WFS_PACKAGE_MAX_FILES` | 2000 | 文件数上限 |
| `WFS_PACKAGE_PREPARE_SECONDS` | 300 | 每条环境准备命令超时，30–1800 秒 |

上线前运行 `python scripts/migrate.py` 应用新增的 **007_task_packages.sql**，再重启单实例调度服务和 Web 服务。Web 的 multipart 上传和 ZIP 下载会转发到调度服务；继续沿用会话、CSRF 和角色控制。不要增加调度器副本。

数据库登记表为 `wfs_package_tasks`、`wfs_task_releases`。`backup_local.py` 与 `backup_platform.py` 会包含默认版本目录、独立依赖环境和 task-data；设置了自定义 `WFS_TASK_RELEASE_DIR` 时，备份命令需加 `--releases <该目录>`。归档统一放入 `data/task-packages`，恢复时应复制回原版本目录与原数据目录，因为数据库和虚拟环境仍引用原路径。恢复到另一台服务器时，基础 Python、操作系统和架构必须兼容，并在启用调度前验证解释器与业务依赖。备份不接受指向外部业务文件的符号链接，此类文件需单独备份；环境中的 Python 链接会复制为可执行文件。已发布版本、回收站和失败准备目录均不会自动清理；持续运行时按磁盘容量规划保留空间，本版本不提供永久删除按钮。

## 接口

- `GET /api/taskinfo/packages`：任务与回收站；加 `pid` 返回任务状态和最近 50 个版本。
- `POST /api/taskinfo/packages/upload`：multipart，`package` 为 ZIP，更新携带 `pid`；新增携带 `task_name/group_name/folder_name`。
- `GET /api/taskinfo/packages/preview?pid=…&version=…`：清单、当前版本差异；加 `path` 返回受限文本差异。
- `GET /api/taskinfo/packages/download?pid=…&version=…`：只下载该版本代码包，不包含虚拟环境和业务数据。
- `POST /api/taskinfo/packages/action`：`import/prepare/publish/rollback/trash/restore`；切换或删除携带当前 `revision`，过期状态返回 409。

任务代码是管理员可信代码。本功能提供版本隔离和发布检查，不是执行不可信代码的安全沙箱。
