-- GaussDB Kernel 503.1.0.SPC2000c DDL
-- Application schema: immpdb

CREATE SCHEMA immpdb;
SET search_path TO immpdb;

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
