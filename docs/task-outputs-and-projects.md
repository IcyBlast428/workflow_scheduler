# 复杂项目投产与执行输出

## 每次执行的输出文件

报表、CSV、JSON、业务日志等应写入 `WFS_OUTPUT_DIR`：

```python
import json
import os
from pathlib import Path

output = Path(os.environ['WFS_OUTPUT_DIR'])
(output / 'summary.json').write_text(
    json.dumps({'count': 100}, ensure_ascii=False, indent=2), encoding='utf-8')
```

路径为 `<WFS_DATA_DIR>/task-data/<任务编号>/runs/<执行编号>/`，平台在启动子进程前创建。每次执行和并发实例独立，使用相同文件名也不会相互覆盖。平台同时提供 `WFS_TASK_ID`、`WFS_RUN_ID`，可写进报表或记录用于追溯。允许在输出目录中创建子目录，如 `reports/2026-10/report.csv`。

进入「执行记录 → 详情」或「任务详情 → 执行记录 → 查看执行」，切换到「输出文件」：

- 按目录浏览、分页，预览 CSV / TSV 表格，以及 JSON、JSONL、log、txt、SQL、Markdown 等文本。
- 预览只读取前 256 KiB；文本最多 2000 行，表格最多 200 行、50 列，截断时明确提示。UTF-8 和 GB18030 文本可读取。
- 执行结束后可下载完整文件，下载使用附件和流式响应。其他二进制文件仅提供下载；HTML 也只作为文本/附件处理，不在页面运行。
- 运行中可以刷新目录和预览，文件可能尚未写完；完整下载等待执行结束。任务失败、超时或取消前已生成的文件也会保留，需结合执行状态判断结果是否完整。

输出读取需要登录，沿用当前任务/日志的查看权限；普通用户只读，无法上传、覆盖或删除输出文件。路径仅限该执行目录，拒绝越界、符号链接、目录链接、硬链接与特殊文件。Web 与 Scheduler 必须共享同一个 `WFS_DATA_DIR`，下载直接读取共享文件，不把大文件全部转发进 Web 内存。

## 三种目录的区别

| 用途 | 路径入口 | 生命周期 |
| --- | --- | --- |
| 源码、SQL、模板、静态资源 | `WFS_TASK_ROOT` | 当前发布版本只读，更新和回滚切换版本 |
| 本次执行的可下载输出 | `WFS_OUTPUT_DIR` | 每个执行编号独立，代码发布不覆盖 |
| 跨执行状态、检查点、缓存 | `WFS_TASK_DATA_DIR` | 同一任务共用，任务自己处理并发和覆盖 |

已有 `WFS_TASK_DATA_DIR` 中的文件不会被自动归属到某次执行或暴露在输出浏览器中。旧历史执行尚无独立输出目录时会提示不可用；新执行使用新目录。不要把数据库口令、密钥等写入可下载产物。

输出保存在持久存储，不放在代码目录、临时容器层或平台元数据表中。现有备份工具会包含 `task-data`，因此也包含这些输出。当前不自动删除业务产物；生产需按业务保留期、备份和磁盘容量制定清理计划。单文件大小受现有 Linux 文件资源限制控制，磁盘余量不足时平台拒绝新执行；这些限制不等于完整的每任务总容量配额。

## 多层目录任务包

在 GitLab 的任务目录内保留完整 Python 模块、SQL、配置模板和资源。例如 `app/jobs/reports/daily_report/` 内的文件结构：

```text
requirements.txt             # 有第三方依赖时放在包根目录
report_job/
  __init__.py
  main.py                    # 可以选择此文件作为入口
  helpers.py
resources/input.json
sql/report.sql
README.md
```

在任务根目录添加 `.wfs-task.json`，指定稳定编号及实际入口：

```json
{"task_id":"daily_report","task_name":"日报汇总","main_file":"report_job/main.py"}
```

发布步骤：代码合并到配置的 GitLab 目标分支 → 在「任务列表」审查新增或更新 → 获取固定提交并核对文件差异 → 检查依赖环境 → 确认发布。任务根目录以内的层级原样保留，不再需要选择 ZIP 外层目录处理方式。「任务示例」可下载完整示例 ZIP，解压后将文件提交到 GitLab；平台不再接收 ZIP 上传。版本发布与保护规则见[任务发布手册](task-packages.md)。

工作目录统一为处理后的包根目录。平台将包根目录、入口所在目录和常见 `src/` 目录加入模块搜索路径；对于带 `__init__.py` 的包入口，按 Python 模块方式执行，支持 `from .helpers import ...`。普通脚本仍按文件执行。`src/report_job/main.py` 这种布局也可以使用；选择对应的实际入口，`requirements.txt` 仍放在整个任务包根目录。

读取资源推荐明确从 `WFS_TASK_ROOT` 定位，或用 `Path(__file__)` 定位相邻资源，不依赖服务器上的绝对路径。任务根目录只维护一份 requirements.txt；仅在子目录发现依赖文件时会拒绝准备该版本并提示合并，防止环境检查漏装依赖。依赖经 Nexus 或离线 wheels 安装到本版本独立环境，不继承平台包。

多个入口有不同调度和并发要求时，应在 GitLab 中组织为多个任务目录，每个任务指定自己的入口。不要提交虚拟环境、缓存、历史输出或本地凭据。任务版本是完整替换，更新时应包含全部仍需要的资源文件；预览会列出缺失文件的删除差异。
