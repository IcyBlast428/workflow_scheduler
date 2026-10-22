-- PolarDB for MySQL / MySQL 8.0+, InnoDB, UTF-8. Use a dedicated database.
-- DDL implicitly commits; this baseline never drops or alters existing tables.
CREATE TABLE IF NOT EXISTS wfs_platform_lock (
 id int PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
INSERT IGNORE INTO wfs_platform_lock(id) VALUES(1);
CREATE TABLE IF NOT EXISTS wfs_auth_sessions (
 sid_hash varchar(64) PRIMARY KEY, created_at datetime(6) NOT NULL, expires_at datetime(6) NOT NULL,
 INDEX idx_auth_expiry(expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_task_config (
 pid varchar(200) PRIMARY KEY, group_name varchar(200), folder_name varchar(200), task_name varchar(500),
 main_file varchar(500), enabled varchar(10) DEFAULT 'false', max_instances int DEFAULT 1,
 timeout_seconds int DEFAULT 0, trigger_type varchar(30), schedule_type varchar(50),
 schedule_json longtext, trigger_json longtext, version int DEFAULT 1,
 updated_by varchar(100), updated_at datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_job_stats (
 pid varchar(200) PRIMARY KEY, group_name varchar(200), folder_name varchar(200), task_name varchar(500) NOT NULL,
 scheduling_stat varchar(30), sms_receiver text, email_receiver text,
 last_status int, last_sms_alarm varchar(100), failed_times int DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_run_history (
 id varchar(64) NOT NULL, pid varchar(200) NOT NULL, taskname varchar(500), dirname varchar(500),
 group_name varchar(200), folder_name varchar(200), state int, tasklog longtext,
 start_time datetime(6) NOT NULL, end_time datetime(6) NOT NULL, summary_version int NOT NULL DEFAULT 0,
 PRIMARY KEY(id,end_time), INDEX idx_run_end(end_time,id), INDEX idx_run_pid_end(pid,end_time,id),
 INDEX idx_run_state_end(state,end_time,id), INDEX idx_summary_pending(summary_version,end_time,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_run_history_archive (
 id varchar(64) NOT NULL, pid varchar(200) NOT NULL, taskname varchar(500), dirname varchar(500),
 group_name varchar(200), folder_name varchar(200), state int, tasklog longtext,
 start_time datetime(6) NOT NULL, end_time datetime(6) NOT NULL,
 PRIMARY KEY(id,end_time), INDEX idx_archive_end(end_time,id), INDEX idx_archive_pid_end(pid,end_time,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_history_rollup (
 pid varchar(200) PRIMARY KEY, archived_failures bigint NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_schedule_history (
 id varchar(64) PRIMARY KEY, pid varchar(200) NOT NULL, taskname varchar(500),
 system_info longtext, datetime_info datetime(6), INDEX idx_schedule_time(datetime_info,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_executions (
 run_id varchar(64) PRIMARY KEY, pid varchar(200) NOT NULL, status varchar(30) NOT NULL,
 created_at datetime(6) NOT NULL, payload longtext NOT NULL,
 INDEX idx_exec_pid_created(pid,created_at), INDEX idx_exec_status_created(status,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_config_versions (
 pid varchar(200) NOT NULL, version int NOT NULL, changed_at datetime(6) NOT NULL,
 changed_by varchar(100) NOT NULL, payload longtext NOT NULL, PRIMARY KEY(pid,version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_config_application (
 pid varchar(200) PRIMARY KEY, version int NOT NULL, status varchar(30) NOT NULL,
 message text, updated_at datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_audit (
 id varchar(64) PRIMARY KEY, actor varchar(100), action varchar(100), target varchar(200),
 outcome varchar(30), details text, created_at datetime(6) NOT NULL, INDEX idx_audit_created(created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_users (
 username varchar(100) PRIMARY KEY, password_hash varchar(300) NOT NULL,
 role varchar(20) NOT NULL, enabled int NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_login_limits (
 key_hash varchar(64) PRIMARY KEY, failures int NOT NULL, window_start datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_run_summary (
 pid varchar(200) NOT NULL, bucket datetime(6) NOT NULL, status varchar(30) NOT NULL,
 executions bigint NOT NULL DEFAULT 0, PRIMARY KEY(pid,bucket,status), INDEX idx_summary_bucket(bucket,pid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_run_totals (
 pid varchar(200) PRIMARY KEY, failures bigint NOT NULL DEFAULT 0, archived_failures bigint NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_notifications (
 id varchar(100) PRIMARY KEY, pid varchar(200) NOT NULL, channel varchar(20) NOT NULL,
 status varchar(30) NOT NULL, attempts int NOT NULL DEFAULT 0, created_at datetime(6) NOT NULL,
 due_at datetime(6) NOT NULL, payload longtext NOT NULL, message text,
 kind varchar(20) NOT NULL, incident varchar(64) NOT NULL,
 INDEX idx_notification_due(status,due_at), INDEX idx_notification_pid(pid,channel,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_alert_incidents (
 pid varchar(200) PRIMARY KEY, incident varchar(64) NOT NULL, opened_at datetime(6) NOT NULL,
 last_alert_at datetime(6) NOT NULL, failures int NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_package_tasks (
 pid varchar(200) PRIMARY KEY, revision int NOT NULL, payload longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_task_releases (
 pid varchar(200) NOT NULL, version varchar(64) NOT NULL, created_at datetime(6) NOT NULL,
 payload longtext NOT NULL, PRIMARY KEY(pid,version), INDEX idx_release_created(pid,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS wfs_schema_migrations (
 name varchar(200) PRIMARY KEY, applied_at datetime(6) NOT NULL, checksum varchar(64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
