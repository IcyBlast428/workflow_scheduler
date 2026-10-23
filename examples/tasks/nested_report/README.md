# 多层目录任务

ZIP 中的 report_job、resources、sql 等层级全部保留，目录处理选择「保留全部目录层级」。Python 入口选择 `report_job/main.py`，或者兼容入口 `main.py`。

平台以包根目录为工作目录，并为有 __init__.py 的包入口保留 Python 包语义，所以 report_job/main.py 中可使用 `from .helpers import total`。读取资源推荐 `Path(os.environ['WFS_TASK_ROOT']) / 'resources/input.json'`。

此示例不需要第三方依赖，不执行 sql/report.sql，只读取本地 JSON 示例数据。每次执行将 reports/details.csv、summary.json 和 report.log 写入 WFS_OUTPUT_DIR，可在线预览和下载。

实际任务将唯一一份 requirements.txt 放在包根目录，通过管理员配置的 Nexus 安装依赖。打包源码与资源，不要打包本地 .venv、.git、缓存、凭据或历史输出。
