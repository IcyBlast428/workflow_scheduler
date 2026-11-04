-- Apply explicitly to the authorized business schema before running the example.
CREATE TABLE demo_batch (business_date VARCHAR(10) PRIMARY KEY,status VARCHAR(20) NOT NULL);
CREATE TABLE demo_item (business_date VARCHAR(10) NOT NULL,item_id INTEGER NOT NULL,amount INTEGER NOT NULL,PRIMARY KEY(business_date,item_id));
