-- PostgreSQL / GaussDB 兼容测试库参考定义，需管理员核对目标版本后手动执行。
CREATE TABLE demo_task_metrics (business_date VARCHAR(10) PRIMARY KEY, total INTEGER NOT NULL);
-- 测试数据：INSERT INTO demo_task_metrics VALUES ('2026-01-05',100);
