# 执行回执的 GaussDB 空字符串兼容性

若 `SELECT '' IS NULL` 返回 true，数据库会把空字符串当作 NULL。旧版在任务真正启动前，用空字符串填写尚未生成的 `run_id`，而回执表要求该列非空，因此手动执行会在启动确认前报 `23502`。队列的编号/消息、已清理的日志路径也属于可空字段。

本版新建表已修正；安装器处理已有本版 schema 时会在事务内重复检查并应用相同修正，不改动任务数据或执行主键。直接修改源码并重启不会自动执行安装器，需要先修正已有表。

## 已部署平台的独立修复

1. 在没有业务任务运行时，在平台服务器执行 `systemctl stop wfs.service`。
2. 用表所有者或有修改表权限的账号连接平台数据库；当前部署为 `immpdb`，schema 为 `wfs`。
3. 执行 [修复 SQL](../schema/upgrade_optional_execution_fields.sql) 全部内容。该文件仅修改三张表的五个可空字段，不删表、不删记录、不修改 `wfs_executions.run_id` 或其他主键。若执行报错，执行 `ROLLBACK`，处理报错后重新执行，不能忽略错误继续提交。
4. 查询确认下列五个字段的 `is_nullable` 均为 `YES`，且不再有空字符串默认值：

```sql
SELECT table_name, column_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'wfs'
  AND ((table_name IN ('wfs_state_admission_receipts',
                      'wfs_state_admission_work_requests')
        AND column_name IN ('run_id', 'message'))
       OR (table_name = 'wfs_state_journal_journal' AND column_name = 'log_path'))
ORDER BY table_name, column_name;
```

5. 执行 `systemctl start wfs.service`。回到任务列表，手动发起一次新的执行，检查这一次执行记录及日志。对于此前标为“未确认”的其他请求，应先核对已有记录，不要批量重试。

该修复不改变 `immpdb` 的兼容模式，也不要求重新发布业务任务。后续完整更新平台时仍须保留现有密钥、运行配置和 `data/`。

本地回归在隔离 PostgreSQL 上通过触发器复现空字符串转 NULL，覆盖旧错误、保留数据的重复升级、手动执行去重、队列状态及日志清理。该验证不替代目标 GaussDB/DWS 环境验收。
