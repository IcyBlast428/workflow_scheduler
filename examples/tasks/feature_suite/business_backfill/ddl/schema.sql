-- 本任务不依赖业务数据库，以下为结果归档的参考表定义；平台编辑 DDL 不会执行 SQL。
CREATE TABLE demo_result (business_date VARCHAR(10) PRIMARY KEY, result_text TEXT);
