CREATE TABLE IF NOT EXISTS wfs_run_history_archive (
    id varchar(50) NOT NULL, pid varchar(200) NOT NULL,
    taskname varchar(500), dirname varchar(200), group_name varchar(100), folder_name varchar(100),
    state integer, tasklog text, start_time timestamp NOT NULL, end_time timestamp NOT NULL,
    PRIMARY KEY(id,end_time)
);
CREATE INDEX IF NOT EXISTS idx_wfs_run_seek ON wfs_run_history(end_time,id);
CREATE INDEX IF NOT EXISTS idx_wfs_run_pid_seek ON wfs_run_history(pid,end_time,id);
CREATE INDEX IF NOT EXISTS idx_wfs_archive_seek ON wfs_run_history_archive(end_time,id);
CREATE INDEX IF NOT EXISTS idx_wfs_archive_pid_seek ON wfs_run_history_archive(pid,end_time,id);
CREATE TABLE IF NOT EXISTS wfs_history_rollup (
    pid varchar(200) PRIMARY KEY, archived_failures bigint NOT NULL DEFAULT 0
);
