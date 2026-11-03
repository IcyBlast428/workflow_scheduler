# 多表事务与 DDL

默认自动调度关闭，在任务列表手动执行。参数配置、建议标签见 settings.json；此文件供安装工具读取，不会被平台自动当成运行策略。

DDL 与标签页展示 ddl/schema.sql；可编辑定义、保存历史，并在关联 GitLab 后提交独立分支。参考 DDL 不代表数据库已经建表。输出查看：详情 → 执行与输出 → 查看执行。流程查看：详情 → 执行流程。

演示库仅位于本任务 WFS_TASK_DATA_DIR/demo.sqlite3，不使用平台 PostgreSQL。simulate_rollback=true 可观察事务回滚；恢复 false 后同一业务日重新执行仍只有两行。
