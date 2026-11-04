# 执行记录与容量

执行索引、持久队列、完成事件、小时汇总和告警记录统一保存于 GaussDB。详情日志按执行编号分目录保存；数据库不可用时，JSON 仅作为临时恢复暂存。恢复后有界补写，不导入任何旧平台数据。

完成记录与统计在同一事务写入，summary_version 防止重复计数。维护工具 scripts/backfill_summaries.py 用于重试尚未生成的汇总；分批执行，失败回滚。历史归档先复制并核对再删除在线明细，归档至少保留原始追溯需要的代码版本。

调度并发、启动速率、队列容量、任务分组配额和 CPU 负载保护详见 [调度容量](task-dispatch.md)。生产仅单个 Scheduler，不通过增加调度副本扩容。

后端性能/一致性验证使用真实隔离数据库，命令为 python scripts/test_backend.py test_runtime_read_model test_scale test_fresh_gauss。scripts/benchmark_journal.py 只在独立测试 schema 生成合成数据，不应连接生产环境。本机 PostgreSQL 性能不代表目标 GaussDB 集群吞吐。

部署与备份统一见 [systemd 手册](systemd-deployment.md)，不使用任何历史库升级或文件数据库入口。
