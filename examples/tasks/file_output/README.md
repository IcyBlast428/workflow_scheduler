# 文件输出任务

只使用 Python 标准库，不需要 requirements.txt。上传 ZIP，检查独立环境后发布；执行结束，在「查看执行 → 输出文件」中预览或下载 report.csv、summary.json 和 report.log。

每次运行自动分配独立 WFS_OUTPUT_DIR，同一文件名不会覆盖其他执行的文件。需要跨执行保存检查点时使用 WFS_TASK_DATA_DIR。
