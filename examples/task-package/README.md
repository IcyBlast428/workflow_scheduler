# 多文件任务包示例

main.py 调用 helpers.py，将结果写入 WFS_TASK_DATA_DIR，并输出一行日志。
sql/query.sql 演示资源文件，不会建立数据库连接。此包只使用 Python 标准库。

将此目录下的文件复制到 GitLab 的 `app/jobs/<分类>/<任务>`，添加 `.wfs-task.json` 指定稳定 task_id 和 main_file（main.py）。合并到目标分支后，在「任务列表」审查差异、检查依赖并发布；初始任务没有自动调度。平台不再接收 ZIP 上传。
