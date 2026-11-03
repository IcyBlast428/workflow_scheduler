# 业务连接查询模板（需配置，不自动安装）

1. 在数据库连接中新建 demo_business 测试连接，连接到 PostgreSQL 或实际 GaussDB 测试库。
2. 按 ddl/schema.sql 在业务测试库手工准备演示表及测试数据。
3. 本目录 requirements.txt 与项目依赖清单一致，包含 PostgreSQL 与 ODBC 入口依赖；GaussDB/DWS 仍需系统 ODBC 驱动与产品版本适配。通过私有 PyPI 或离线 wheel 准备与目标数据库驱动匹配的依赖；参考 docs/task-environments-and-nexus.md。NewDB 依赖 SQLAlchemy、configobj、cryptography 及对应数据库驱动，版本需按项目的数据库依赖清单准备。
4. 复制本目录到 GitLab app/jobs/功能示例/business_connection，合并、审查并发布。
5. 在任务连接授权中仅授权 demo_business；运行策略中声明该连接。试运行映射到独立测试连接，勿授予平台库。
6. 默认参数 connection=demo_business、business_date=2026-01-05；手动执行后查看 query.json。再演示业务日期补跑、源码、DDL 修改历史和 GitLab 分支提交。

该模板使用平台 SDK，适合演示数据库授权、私有依赖仓库、不可变版本与 GitLab；实际 GaussDB/DWS 驱动与 SQL 兼容性须在目标测试环境验证。
