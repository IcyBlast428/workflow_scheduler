# 多文件任务包示例

main.py 调用 helpers.py，将结果写入 WFS_TASK_DATA_DIR，并输出一行日志。
sql/query.sql 演示资源文件，不会建立数据库连接。此包只使用 Python 标准库。

将此目录下的文件压缩为 ZIP 后，可以在「任务发布」新增任务、检查依赖环境并发布；初始任务没有自动调度。
