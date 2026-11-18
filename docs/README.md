# 文档索引

首次投产从 START-HERE.md 开始；全新安装不要求运行历史升级或修复脚本。已有实例维护、开发测试和历史设计分别查阅对应文档。

- [全新投产操作手册](../START-HERE.md)
- [数据库、Nacos 与完整表清单](../deploy/root-test/DATABASE.md)
- [独立 Nginx / Docker 代理](nginx-deployment.md)
- [架构图与新手使用说明（离线网页）](onboarding/index.html)
- [新人讲解手册（12 页 PDF）](onboarding/workflow-scheduler-guide.pdf)
- [系统架构图（PNG）](onboarding/architecture.png) · [可缩放 SVG](onboarding/architecture.svg)
- [服务结构与已有实例运维](systemd-deployment.md)
- [固定目录生产配置说明](../deploy/root-test/README.md)
- [本机协议测试](local-postgres-windows.md)
- [任务发布](task-packages.md)
- [GitLab 扫描与差异](gitlab-updates.md)
- [独立环境与私有 PyPI](task-environments-and-nexus.md)
- [输出与项目目录](task-outputs-and-projects.md)
- [DDL 与标签](task-schema-and-tags.md)
- [性能优化与数据库连接升级](performance-and-connections.md)
- [统一业务数据库连接 / NewDB](business-database-connections.md)
- [Nacos 2.x 配置管理与双向同步](nacos-connections.md)
- [数据库增删改查、事务与异步用法](database-usage.md)
- [日志摘要与历史归档](performance-storage.md)
- [排队与负载控制](task-dispatch.md)
- [导航与日志清理](navigation-and-log-storage.md)
- [执行矩阵](execution-matrix.md)
- [任务流程分析](task-flow.md)
- [全新架构检查](fresh-gauss-audit.md)
- [代码清理与性能优化](repository-cleanup.md)

历史架构图、PDF、审计和 archive 中的设计记录不作为当前首次安装步骤；已投产功能以当前代码和主操作手册为准。
