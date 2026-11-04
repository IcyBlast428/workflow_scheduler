# 多表事务与 DDL

建立 demo_business 业务连接并授权给任务，先审查并在独立业务库执行 ddl/schema.sql。平台只展示、记录 DDL，不自动执行。
connection_id 指定授权连接；simulate_rollback=true 演示回滚。同一天重复执行替换当天两行数据；生产并行写入需按业务增加锁。
依赖通过私有 PyPI 准备。本示例需要业务库，故不随无外部依赖的示例自动安装。
