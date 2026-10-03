CREATE TABLE IF NOT EXISTS wfs_package_tasks (
    pid varchar(200) PRIMARY KEY, revision integer NOT NULL, payload text NOT NULL
);
CREATE TABLE IF NOT EXISTS wfs_task_releases (
    pid varchar(200) NOT NULL, version varchar(64) NOT NULL, created_at timestamp NOT NULL,
    payload text NOT NULL, PRIMARY KEY(pid, version)
);
CREATE INDEX IF NOT EXISTS idx_wfs_release_created ON wfs_task_releases(pid, created_at);
