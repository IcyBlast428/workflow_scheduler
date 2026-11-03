-- 仅供本任务自有 SQLite 演示库，脚本会显式创建下列两张表。
CREATE TABLE IF NOT EXISTS demo_batch (business_date TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS demo_item (business_date TEXT NOT NULL, item_id INTEGER NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY (business_date,item_id));
