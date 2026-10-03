-- Local development only. Production continues to use GaussDB.
CREATE TABLE IF NOT EXISTS wfs_auth_sessions (
    sid_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wfs_task_config (
    pid TEXT PRIMARY KEY, group_name TEXT, folder_name TEXT, task_name TEXT,
    main_file TEXT, enabled TEXT DEFAULT 'false', max_instances INTEGER DEFAULT 1,
    timeout_seconds INTEGER DEFAULT 0, trigger_type TEXT, schedule_type TEXT,
    schedule_json TEXT, trigger_json TEXT, version INTEGER DEFAULT 1,
    updated_by TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wfs_job_stats (
    pid TEXT PRIMARY KEY, group_name TEXT, folder_name TEXT, task_name TEXT NOT NULL,
    scheduling_stat TEXT, sms_receiver TEXT, email_receiver TEXT,
    last_status INTEGER, last_sms_alarm TEXT, failed_times INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wfs_run_history (
    id TEXT NOT NULL, pid TEXT NOT NULL, taskname TEXT, dirname TEXT,
    group_name TEXT, folder_name TEXT, state INTEGER, tasklog TEXT,
    start_time TEXT NOT NULL, end_time TEXT NOT NULL,
    PRIMARY KEY (id, end_time)
);
CREATE INDEX IF NOT EXISTS idx_local_run_end ON wfs_run_history(end_time);
CREATE INDEX IF NOT EXISTS idx_local_run_pid_end ON wfs_run_history(pid, end_time);
CREATE TABLE IF NOT EXISTS wfs_run_history_archive (
    id TEXT NOT NULL, pid TEXT NOT NULL, taskname TEXT, dirname TEXT,
    group_name TEXT, folder_name TEXT, state INTEGER, tasklog TEXT,
    start_time TEXT NOT NULL, end_time TEXT NOT NULL, PRIMARY KEY(id,end_time)
);
CREATE INDEX IF NOT EXISTS idx_wfs_run_seek ON wfs_run_history(end_time,id);
CREATE INDEX IF NOT EXISTS idx_wfs_run_pid_seek ON wfs_run_history(pid,end_time,id);
CREATE INDEX IF NOT EXISTS idx_wfs_archive_seek ON wfs_run_history_archive(end_time,id);
CREATE INDEX IF NOT EXISTS idx_wfs_archive_pid_seek ON wfs_run_history_archive(pid,end_time,id);
CREATE TABLE IF NOT EXISTS wfs_history_rollup (
    pid TEXT PRIMARY KEY, archived_failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wfs_schedule_history (
    id TEXT PRIMARY KEY, pid TEXT NOT NULL, taskname TEXT,
    system_info TEXT, datetime_info TEXT
);

CREATE TABLE IF NOT EXISTS wfs_executions (
    run_id varchar(64) PRIMARY KEY, pid varchar(200) NOT NULL,
    status varchar(30) NOT NULL, created_at timestamp NOT NULL, payload text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfs_exec_pid_created ON wfs_executions(pid, created_at);
CREATE INDEX IF NOT EXISTS idx_wfs_exec_status_created ON wfs_executions(status, created_at);
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

CREATE TABLE IF NOT EXISTS wfs_run_summary (
 pid varchar(200) NOT NULL, bucket timestamp NOT NULL, status varchar(30) NOT NULL,
 executions bigint NOT NULL DEFAULT 0, PRIMARY KEY(pid,bucket,status)
);
CREATE INDEX IF NOT EXISTS idx_wfs_summary_bucket ON wfs_run_summary(bucket,pid);
CREATE TABLE IF NOT EXISTS wfs_run_totals (
 pid varchar(200) PRIMARY KEY, failures bigint NOT NULL DEFAULT 0, archived_failures bigint NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wfs_notifications (
 id varchar(100) PRIMARY KEY, pid varchar(200) NOT NULL, channel varchar(20) NOT NULL,
 status varchar(30) NOT NULL, attempts integer NOT NULL DEFAULT 0,
 created_at timestamp NOT NULL, due_at timestamp NOT NULL, payload text NOT NULL,
 message text, kind varchar(20) NOT NULL, incident varchar(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfs_notification_due ON wfs_notifications(status,due_at);
CREATE INDEX IF NOT EXISTS idx_wfs_notification_pid ON wfs_notifications(pid,channel,created_at);
CREATE TABLE IF NOT EXISTS wfs_alert_incidents (
 pid varchar(200) PRIMARY KEY, incident varchar(64) NOT NULL, opened_at timestamp NOT NULL,
 last_alert_at timestamp NOT NULL, failures integer NOT NULL DEFAULT 1
);
