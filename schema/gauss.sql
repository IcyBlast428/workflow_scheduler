-- Fresh GaussDB/DWS schema. Initialize only an empty target schema.

CREATE SCHEMA wfs;

SET search_path TO wfs;

CREATE TABLE wfs_run_history (
    id          varchar(50)  NOT NULL,
    pid         varchar(200) NOT NULL,
    taskname    varchar(500),
    dirname     varchar(200),
    group_name  varchar(100),
    folder_name varchar(100),
    summary_version integer NOT NULL DEFAULT 0,
    state       integer,
    tasklog     text,
    start_time  timestamp NOT NULL,
    end_time    timestamp NOT NULL,
    CONSTRAINT pk_wfs_run_history PRIMARY KEY (id, end_time)
);

CREATE INDEX idx_wfs_run_pid
    ON wfs_run_history (pid);

CREATE INDEX idx_wfs_run_pid_start_time
    ON wfs_run_history (pid, start_time);

CREATE INDEX idx_wfs_run_end_time
    ON wfs_run_history (end_time);

CREATE INDEX idx_wfs_run_pid_end_time
    ON wfs_run_history (pid, end_time);

CREATE INDEX idx_wfs_run_state_end_time
    ON wfs_run_history (state, end_time);

CREATE INDEX idx_wfs_run_group_folder
    ON wfs_run_history (group_name, folder_name);

CREATE TABLE wfs_schedule_history (
    id            varchar(50)  NOT NULL,
    pid           varchar(200) NOT NULL,
    taskname      varchar(200),
    system_info   text,
    datetime_info timestamp,
    CONSTRAINT pk_wfs_schedule_history PRIMARY KEY (id)
);

CREATE INDEX idx_wfs_schedule_datetime
    ON wfs_schedule_history (datetime_info);

CREATE INDEX idx_wfs_schedule_pid_datetime
    ON wfs_schedule_history (pid, datetime_info);

CREATE TABLE wfs_task_config (
    pid            varchar(200) NOT NULL,
    group_name     varchar(100),
    folder_name    varchar(100),
    task_name      varchar(200),
    main_file      varchar(500),
    enabled        varchar(10) DEFAULT 'false',
    max_instances  integer DEFAULT 1,
    timeout_seconds integer DEFAULT 0,
    trigger_type   varchar(20),
    schedule_type  varchar(50),
    schedule_json  text,
    trigger_json   text,
    version        integer DEFAULT 1,
    updated_by     varchar(100),
    updated_at     timestamp NOT NULL,
    CONSTRAINT pk_wfs_task_config PRIMARY KEY (pid)
);

CREATE INDEX idx_wfs_task_config_group
    ON wfs_task_config (group_name);

CREATE INDEX idx_wfs_task_config_group_folder
    ON wfs_task_config (group_name, folder_name);

CREATE INDEX idx_wfs_task_config_updated_at
    ON wfs_task_config (updated_at);

CREATE INDEX idx_wfs_task_config_enabled
    ON wfs_task_config (enabled);

CREATE TABLE wfs_job_stats (
    pid             varchar(200) NOT NULL,
    group_name      varchar(100),
    folder_name     varchar(100),
    task_name       varchar(200) NOT NULL,
    scheduling_stat varchar(10),
    sms_receiver    varchar(500),
    email_receiver  varchar(500),
    last_status     smallint,
    last_sms_alarm  timestamp,
    failed_times    integer DEFAULT 0,
    CONSTRAINT pk_wfs_job_stats PRIMARY KEY (pid)
);

CREATE INDEX idx_wfs_job_group_name
    ON wfs_job_stats (group_name);

CREATE INDEX idx_wfs_job_group_folder
    ON wfs_job_stats (group_name, folder_name);

CREATE TABLE wfs_auth_sessions (
    sid_hash varchar(64) PRIMARY KEY,
    created_at timestamp NOT NULL,
    expires_at timestamp NOT NULL
);

CREATE TABLE wfs_executions (
    run_id varchar(64) PRIMARY KEY, pid varchar(200) NOT NULL,
    status varchar(30) NOT NULL, created_at timestamp NOT NULL, payload text NOT NULL
);

CREATE INDEX idx_wfs_exec_pid_created ON wfs_executions(pid, created_at);

CREATE TABLE wfs_config_versions (
    pid varchar(200) NOT NULL, version integer NOT NULL, changed_at timestamp NOT NULL,
    changed_by varchar(100) NOT NULL, payload text NOT NULL, PRIMARY KEY(pid, version)
);

CREATE TABLE wfs_config_application (
    pid varchar(200) PRIMARY KEY, version integer NOT NULL, status varchar(30) NOT NULL,
    message text, updated_at timestamp NOT NULL
);

CREATE TABLE wfs_audit (
    id varchar(64) PRIMARY KEY, actor varchar(100), action varchar(100), target varchar(200),
    outcome varchar(30), details text, created_at timestamp NOT NULL
);

CREATE INDEX idx_wfs_audit_created ON wfs_audit(created_at);

CREATE TABLE wfs_users (
    username varchar(100) PRIMARY KEY, password_hash varchar(300) NOT NULL,
    role varchar(20) NOT NULL, enabled integer NOT NULL DEFAULT 1
);

CREATE TABLE wfs_login_limits (
    key_hash varchar(64) PRIMARY KEY, failures integer NOT NULL, window_start timestamp NOT NULL
);

CREATE TABLE wfs_run_history_archive (
    id varchar(50) NOT NULL, pid varchar(200) NOT NULL,
    taskname varchar(500), dirname varchar(200), group_name varchar(100), folder_name varchar(100),
    state integer, tasklog text, start_time timestamp NOT NULL, end_time timestamp NOT NULL,
    PRIMARY KEY(id,end_time)
);

CREATE INDEX idx_wfs_run_seek ON wfs_run_history(end_time,id);

CREATE INDEX idx_wfs_run_pid_seek ON wfs_run_history(pid,end_time,id);

CREATE INDEX idx_wfs_archive_seek ON wfs_run_history_archive(end_time,id);

CREATE INDEX idx_wfs_archive_pid_seek ON wfs_run_history_archive(pid,end_time,id);

CREATE TABLE wfs_history_rollup (
    pid varchar(200) PRIMARY KEY, archived_failures bigint NOT NULL DEFAULT 0
);

CREATE INDEX idx_wfs_exec_status_created ON wfs_executions(status,created_at);

CREATE INDEX idx_wfs_summary_pending ON wfs_run_history(summary_version,end_time,id);

CREATE TABLE wfs_run_summary (
 pid varchar(200) NOT NULL, bucket timestamp NOT NULL, status varchar(30) NOT NULL,
 executions bigint NOT NULL DEFAULT 0, PRIMARY KEY(pid,bucket,status)
);

CREATE INDEX idx_wfs_summary_bucket ON wfs_run_summary(bucket,pid);

CREATE TABLE wfs_run_totals (
 pid varchar(200) PRIMARY KEY, failures bigint NOT NULL DEFAULT 0, archived_failures bigint NOT NULL DEFAULT 0
);

CREATE TABLE wfs_notifications (
 id varchar(100) PRIMARY KEY, pid varchar(200) NOT NULL, channel varchar(20) NOT NULL,
 status varchar(30) NOT NULL, attempts integer NOT NULL DEFAULT 0,
 created_at timestamp NOT NULL, due_at timestamp NOT NULL, payload text NOT NULL,
 message text, kind varchar(20) NOT NULL, incident varchar(64) NOT NULL
);

CREATE INDEX idx_wfs_notification_due ON wfs_notifications(status,due_at);

CREATE INDEX idx_wfs_notification_pid ON wfs_notifications(pid,channel,created_at);

CREATE TABLE wfs_alert_incidents (
 pid varchar(200) PRIMARY KEY, incident varchar(64) NOT NULL, opened_at timestamp NOT NULL,
 last_alert_at timestamp NOT NULL, failures integer NOT NULL DEFAULT 1
);

CREATE TABLE wfs_package_tasks (
    pid varchar(200) PRIMARY KEY, revision integer NOT NULL, payload text NOT NULL
);

CREATE TABLE wfs_task_releases (
    pid varchar(200) NOT NULL, version varchar(64) NOT NULL, created_at timestamp NOT NULL,
    payload text NOT NULL, PRIMARY KEY(pid, version)
);

CREATE INDEX idx_wfs_release_created ON wfs_task_releases(pid, created_at);

CREATE TABLE wfs_state_admission_settings (
 key VARCHAR(1024) NOT NULL DEFAULT '',
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(key)
);

CREATE TABLE wfs_state_admission_receipts (
 actor VARCHAR(1024) NOT NULL DEFAULT '',
 key VARCHAR(1024) NOT NULL DEFAULT '',
 pid VARCHAR(1024) NOT NULL DEFAULT '',
 status VARCHAR(1024) NOT NULL DEFAULT '',
 run_id VARCHAR(1024) NOT NULL DEFAULT '',
 message VARCHAR(1024) NOT NULL DEFAULT '',
 created_at VARCHAR(1024) NOT NULL DEFAULT '',
 PRIMARY KEY(actor,key)
);

CREATE TABLE wfs_state_admission_work_requests (
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

CREATE TABLE wfs_state_admission_ddl_history (
 pid VARCHAR(1024) NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(pid,revision)
);

CREATE TABLE wfs_state_admission_hook_events (
 id VARCHAR(1024) NOT NULL DEFAULT '',
 at DOUBLE PRECISION NOT NULL DEFAULT 0,
 PRIMARY KEY(id)
);

CREATE TABLE wfs_state_connections_profiles (
 id VARCHAR(1024) NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(id)
);

CREATE TABLE wfs_state_publishing_settings (
 name VARCHAR(1024) NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(name)
);

CREATE TABLE wfs_state_gitlab_configuration (
 id INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(id)
);

CREATE TABLE wfs_state_gitlab_snapshot (
 id INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(id)
);

CREATE TABLE wfs_state_gitlab_scan_lease (
 id INTEGER NOT NULL DEFAULT 0,
 token VARCHAR(1024) NOT NULL DEFAULT '',
 expires DOUBLE PRECISION NOT NULL DEFAULT 0,
 PRIMARY KEY(id)
);

CREATE TABLE wfs_state_gitlab_acknowledgements (
 username VARCHAR(1024) NOT NULL DEFAULT '',
 fingerprint VARCHAR(1024) NOT NULL DEFAULT '',
 PRIMARY KEY(username)
);

CREATE TABLE wfs_state_journal_journal (
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

CREATE INDEX wfs_state_journal_pid_time ON wfs_state_journal_journal(pid,created_at DESC);

CREATE INDEX wfs_state_journal_time ON wfs_state_journal_journal(created_at);

CREATE INDEX wfs_state_journal_pending ON wfs_state_journal_journal(pending,retry_at,created_at);

CREATE INDEX wfs_state_journal_status ON wfs_state_journal_journal(status,created_at);

CREATE INDEX wfs_state_requests_due ON wfs_state_admission_work_requests(status,due_at);

CREATE INDEX wfs_state_requests_pid ON wfs_state_admission_work_requests(pid,status);

CREATE INDEX wfs_state_requests_expiry ON wfs_state_admission_work_requests(status,expires_at);

CREATE TABLE wfs_schema_version (version INTEGER PRIMARY KEY, installed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);

INSERT INTO wfs_schema_version(version) VALUES(1);
