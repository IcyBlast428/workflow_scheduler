# 部署与存储边界

正式应用使用 systemd：Web 与单实例 Scheduler。平台主库固定为 GaussDB/DWS，账户、任务、队列、版本、审计、连接密文、GitLab/依赖配置、DDL 修改记录和标签统一存入平台库。平台不提供其他主库选项。

共享目录保存日志、指标、任务版本、独立依赖环境、输出与数据库故障恢复暂存。任务输出通过 WFS_TASK_DATA_DIR/WFS_OUTPUT_DIR 与源码分离，Git 删除源码不会删除业务输出。

全新部署使用新数据库/schema 和新数据目录，无旧数据迁移。任务只能经 GitLab 审查与显式发布进入调度器，默认未开启调度、默认未授权业务数据库。MySQL、PostgreSQL 协议与 ClickHouse 均属于任务业务连接。

备份包括 GaussDB 原生 dump 和共享文件，固定密钥、Nacos/驱动配置单独保管。恢复先到新数据库与新目录核对。详见 [部署手册](systemd-deployment.md)。
