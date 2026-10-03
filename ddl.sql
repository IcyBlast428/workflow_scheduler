-- GaussDB Kernel 503.1.0.SPC2000c DDL
-- Application schema: wfs (aligns with default WFS_DB_ID=sysimemedb_wfs)

CREATE SCHEMA wfs;
SET search_path TO wfs;

CREATE TABLE wfs_run_history (
    id          varchar(50)  NOT NULL,
    pid         varchar(200) NOT NULL,
    taskname    varchar(500),
    dirname     varchar(200),
    group_name  varchar(100),
    folder_name varchar(100),
    state       integer,
    tasklog     text,
    start_time  timestamp(0) NOT NULL,
    end_time    timestamp(0) NOT NULL,
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
    datetime_info timestamp(0),
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
    updated_at     timestamp(0) NOT NULL,
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
    last_sms_alarm  timestamp(0),
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
