CREATE TABLE IF NOT EXISTS wfs_executions (
    run_id varchar(64) PRIMARY KEY, pid varchar(200) NOT NULL,
    status varchar(30) NOT NULL, created_at timestamp NOT NULL, payload text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfs_exec_pid_created ON wfs_executions(pid, created_at);
CREATE TABLE IF NOT EXISTS wfs_config_versions (
    pid varchar(200) NOT NULL, version integer NOT NULL, changed_at timestamp NOT NULL,
    changed_by varchar(100) NOT NULL, payload text NOT NULL, PRIMARY KEY(pid, version)
);
CREATE TABLE IF NOT EXISTS wfs_config_application (
    pid varchar(200) PRIMARY KEY, version integer NOT NULL, status varchar(30) NOT NULL,
    message text, updated_at timestamp NOT NULL
);
CREATE TABLE IF NOT EXISTS wfs_audit (
    id varchar(64) PRIMARY KEY, actor varchar(100), action varchar(100), target varchar(200),
    outcome varchar(30), details text, created_at timestamp NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfs_audit_created ON wfs_audit(created_at);
CREATE TABLE IF NOT EXISTS wfs_users (
    username varchar(100) PRIMARY KEY, password_hash varchar(300) NOT NULL,
    role varchar(20) NOT NULL, enabled integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS wfs_login_limits (
    key_hash varchar(64) PRIMARY KEY, failures integer NOT NULL, window_start timestamp NOT NULL
);
