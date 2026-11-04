-- Fresh-install GaussDB state tables; no SQLite data import.
CREATE TABLE IF NOT EXISTS wfs_state_admission_settings (
 key VARCHAR(1024) NOT NULL DEFAULT '',
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(key)
);
CREATE TABLE IF NOT EXISTS wfs_state_admission_receipts (
 actor VARCHAR(1024) NOT NULL DEFAULT '',
 key VARCHAR(1024) NOT NULL DEFAULT '',
 pid VARCHAR(1024) NOT NULL DEFAULT '',
 status VARCHAR(1024) NOT NULL DEFAULT '',
 run_id VARCHAR(1024) NOT NULL DEFAULT '',
 message VARCHAR(1024) NOT NULL DEFAULT '',
 created_at VARCHAR(1024) NOT NULL DEFAULT '',
 PRIMARY KEY(actor,key)
);
CREATE TABLE IF NOT EXISTS wfs_state_admission_work_requests (
 id VARCHAR(1024) NOT NULL DEFAULT '',
 pid VARCHAR(1024) NOT NULL DEFAULT '',
 kind VARCHAR(1024) NOT NULL DEFAULT '',
 status VARCHAR(1024) NOT NULL DEFAULT '',
 payload TEXT NOT NULL DEFAULT '{}',
 created_at VARCHAR(1024) NOT NULL DEFAULT '',
 due_at VARCHAR(1024) NOT NULL DEFAULT '',
 run_id VARCHAR(1024) NOT NULL DEFAULT '',
 message VARCHAR(1024) NOT NULL DEFAULT '',
 expires_at VARCHAR(1024) NOT NULL DEFAULT '',
 PRIMARY KEY(id)
);
CREATE TABLE IF NOT EXISTS wfs_state_admission_ddl_history (
 pid VARCHAR(1024) NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(pid,revision)
);
CREATE TABLE IF NOT EXISTS wfs_state_admission_hook_events (
 id VARCHAR(1024) NOT NULL DEFAULT '',
 at DOUBLE PRECISION NOT NULL DEFAULT 0,
 PRIMARY KEY(id)
);
CREATE TABLE IF NOT EXISTS wfs_state_connections_profiles (
 id VARCHAR(1024) NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(id)
);
CREATE TABLE IF NOT EXISTS wfs_state_publishing_settings (
 name VARCHAR(1024) NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(name)
);
CREATE TABLE IF NOT EXISTS wfs_state_gitlab_configuration (
 id INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(id)
);
CREATE TABLE IF NOT EXISTS wfs_state_gitlab_snapshot (
 id INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(id)
);
CREATE TABLE IF NOT EXISTS wfs_state_gitlab_scan_lease (
 id INTEGER NOT NULL DEFAULT 0,
 token VARCHAR(1024) NOT NULL DEFAULT '',
 expires DOUBLE PRECISION NOT NULL DEFAULT 0,
 PRIMARY KEY(id)
);
CREATE TABLE IF NOT EXISTS wfs_state_gitlab_acknowledgements (
 username VARCHAR(1024) NOT NULL DEFAULT '',
 fingerprint VARCHAR(1024) NOT NULL DEFAULT '',
 PRIMARY KEY(username)
);
CREATE TABLE IF NOT EXISTS wfs_state_journal_journal (
 run_id VARCHAR(1024) NOT NULL DEFAULT '',
 pid VARCHAR(1024) NOT NULL DEFAULT '',
 status VARCHAR(1024) NOT NULL DEFAULT '',
 created_at VARCHAR(1024) NOT NULL DEFAULT '',
 pending INTEGER NOT NULL DEFAULT 0,
 retry_at DOUBLE PRECISION NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 log_path VARCHAR(1024) NOT NULL DEFAULT '',
 PRIMARY KEY(run_id)
);
CREATE INDEX IF NOT EXISTS wfs_state_journal_pid_time ON wfs_state_journal_journal(pid,created_at DESC);
CREATE INDEX IF NOT EXISTS wfs_state_journal_time ON wfs_state_journal_journal(created_at);
CREATE INDEX IF NOT EXISTS wfs_state_journal_pending ON wfs_state_journal_journal(pending,retry_at,created_at);
CREATE INDEX IF NOT EXISTS wfs_state_journal_status ON wfs_state_journal_journal(status,created_at);
CREATE INDEX IF NOT EXISTS wfs_state_requests_due ON wfs_state_admission_work_requests(status,due_at);
CREATE INDEX IF NOT EXISTS wfs_state_requests_pid ON wfs_state_admission_work_requests(pid,status);
CREATE INDEX IF NOT EXISTS wfs_state_requests_expiry ON wfs_state_admission_work_requests(status,expires_at);
