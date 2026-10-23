# 任务环境、示例管理与 Nexus

## Python 运行关系

平台的 Web / Scheduler 使用部署时安装的平台 Python 环境。通过任务发布页面管理的每个任务版本，在“检查依赖环境”阶段创建自己的 `environment-<准备编号>` 虚拟环境，不继承平台或其他任务的第三方包。虚拟环境基于 Scheduler 当前使用的 Python 主版本，不代表每任务可选择不同 Python 版本。

发布成功后，每次执行均由 Scheduler 使用该版本环境的解释器启动独立 Python 子进程；进程结束后退出，但虚拟环境保留，下一次执行复用，不重复安装依赖。同一版本的并发执行各有进程，共享同一个环境；不同任务、不同版本的环境分开。回滚使用旧版本已经准备好的环境。

所有运行任务均来自已发布版本，并使用该版本的独立虚拟环境。旧目录任务需先通过[一次性迁移](platform-releases.md#旧任务的一次性迁移)完成依赖检查和发布，运行时不会回退到平台解释器。虚拟环境隔离 Python 依赖，不隔离操作系统权限；任务使用平台源码提供的 NewDB 时，也需要在自己的 requirements.txt 声明必要依赖。

## Nexus 配置与使用

管理员在“任务发布 → 任务依赖仓库”选择 Nexus 并保存：

```text
安装方式：Nexus 私有仓库
索引地址：http://nexus.immp.icbc/repository/pypi-hosted/simple/
认证账号：留空
认证密码：留空
CA：留空（此地址为 HTTP）
```

地址填写 `http://nexus.immp.icbc/repository/pypi-hosted` 时自动补全 `/simple/`，遵循 [Sonatype PyPI 配置方式](https://help.sonatype.com/en/configure-pypi-with-nexus.html)。生产仓库实际连通性需在可以访问内网的 Scheduler 主机上验证。这里没有声称已经访问或验收生产内网仓库。

任务包只需包含代码与 requirements.txt，不必再打包 wheels：

```text
main.py
requirements.txt
```

requirements.txt 示例：

```text
SQLAlchemy==2.0.46
configobj==5.0.8
cryptography==50.0.2
PyMySQL==1.1.0
```

完整流程：上传 ZIP → 查看文件 → 检查依赖环境 → 创建版本虚拟环境 → 从 Nexus 安装直接和间接依赖 → pip check → 记录 dependencies.lock.txt → 发布 → 手动执行确认 → 启用调度。准备阶段不会运行任务入口，失败的版本不能发布。依赖准备的状态和阶段在版本预览中显示，详细错误在版本目录 prepare.log 中。

Nexus 模式使用一个索引，不设置额外公共索引，不读取服务主机已有的 pip 配置，避免已有 extra-index 设置混入公共源。[pip 文档](https://pip.pypa.io/en/stable/cli/pip_install/)说明 extra-index 可能造成同名依赖选择问题。HTTP 仓库仅针对配置主机添加 pip trusted-host；HTTPS 保持证书校验，可配置内部 CA。

当前安装匹配 Python / 系统 / CPU 的 wheel，不在线编译源码包。pypi-hosted 仓库需要包含全部间接依赖的兼容 wheel；若内部 hosted 仓库没有这些依赖，应由管理员预先上传，或在 Nexus 侧提供包含 hosted / proxy 的 group 仓库，再调整索引地址。不会因私有仓库缺包而自动切到公网。

安装结果保存在版本目录 dependencies.lock.txt，便于核对实际版本；现有环境在运行和回滚时复用。若依赖文件使用范围而非精确版本，重新准备可能解析到不同间接版本；如需重建结果一致，应将验证后的完整版本锁定纳入下一任务包。

## 示例维护与数据保留

管理员可编辑类型名称、说明、提示、下载文件名、代码语言、源码，或新增示例类型。代码展示使用语法高亮和 HTML 转义，复制与下载保留原始文本；保存示例不会执行代码。当前编辑若遇到其他管理员已修改的版本，会返回冲突并保留本地草稿。

示例与仓库配置保存于共享 `WFS_DATA_DIR/task-publishing.sqlite3`。仓库配置使用从平台配置密钥派生的独立密钥加密；密码不回传前端。准备依赖时如需要认证，使用临时 netrc 文件，安装结束即清理，不把密码写入命令参数或任务环境；准备日志会隐藏已知认证密码。当前生产地址无需认证。

Web 和 Scheduler 必须挂载相同数据目录，仓库配置保存后无需重启，下次环境检查读取新设置。配置不会修改已发布版本的依赖环境。备份工具会一致备份该 SQLite 文件，恢复同时检查完整性；恢复时需要保留原配置密钥。升级代码不自动覆盖已保存的示例。
