# 多层目录任务

将 report_job、resources、sql 等完整目录复制到 GitLab 的一个任务目录，在平台发布页面填写任务名称、选择入口 `report_job/main.py` 或 `main.py`，无需编写配置文件或任务编号。合并到目标分支后在任务列表审查、准备环境并发布，目录层级原样保留；不再上传 ZIP 或选择外层目录处理方式。

平台以包根目录为工作目录，并为有 __init__.py 的包入口保留 Python 包语义，所以 report_job/main.py 中可使用 `from .helpers import total`。读取资源推荐 `Path(os.environ['WFS_TASK_ROOT']) / 'resources/input.json'`。

此示例不需要第三方依赖，不执行 sql/report.sql，只读取本地 JSON 示例数据。每次执行将 reports/details.csv、summary.json 和 report.log 写入 WFS_OUTPUT_DIR，可在线预览和下载。

实际任务将唯一一份 requirements.txt 放在包根目录，通过管理员配置的 Nexus 安装依赖。打包源码与资源，不要打包本地 .venv、.git、缓存、凭据或历史输出。
