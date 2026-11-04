# 文件输出任务

只使用 Python 标准库，不需要 requirements.txt。复制源码到 GitLab 任务目录，添加稳定任务身份文件，合并后在任务列表检查独立环境并发布；执行结束，在「查看执行 → 输出文件」中预览或下载 report.csv、summary.json 和 report.log。下载的示例 ZIP 用于解压参考，不再通过平台上传。

每次运行自动分配独立 WFS_OUTPUT_DIR，同一文件名不会覆盖其他执行的文件。需要跨执行保存检查点时使用 WFS_TASK_DATA_DIR。
