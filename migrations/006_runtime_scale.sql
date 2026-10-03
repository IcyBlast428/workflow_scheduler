ALTER TABLE wfs_run_history ADD COLUMN summary_version integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_wfs_summary_pending ON wfs_run_history(summary_version,end_time,id);
CREATE TABLE IF NOT EXISTS wfs_run_summary (
 pid varchar(200) NOT NULL, bucket timestamp NOT NULL, status varchar(30) NOT NULL,
 executions bigint NOT NULL DEFAULT 0, PRIMARY KEY(pid,bucket,status)
);
CREATE INDEX IF NOT EXISTS idx_wfs_summary_bucket ON wfs_run_summary(bucket,pid);
CREATE TABLE IF NOT EXISTS wfs_run_totals (
 pid varchar(200) PRIMARY KEY, failures bigint NOT NULL DEFAULT 0, archived_failures bigint NOT NULL DEFAULT 0
);
INSERT INTO wfs_run_totals(pid,failures,archived_failures) SELECT pid,archived_failures,archived_failures FROM wfs_history_rollup;
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
