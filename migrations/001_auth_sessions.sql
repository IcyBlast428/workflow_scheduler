CREATE TABLE IF NOT EXISTS wfs_auth_sessions (
    sid_hash varchar(64) PRIMARY KEY,
    created_at timestamp NOT NULL,
    expires_at timestamp NOT NULL
);
