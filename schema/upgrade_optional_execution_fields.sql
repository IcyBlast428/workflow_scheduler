-- Connect to the existing platform database (immpdb in this deployment).
-- Stop wfs.service first. This changes only optional fields, never task data.
-- The deployed schema is wfs; use the configured schema if different.
-- Repeat execution is safe. On any error, ROLLBACK; do not continue to COMMIT.
BEGIN;
ALTER TABLE wfs.wfs_state_admission_receipts ALTER COLUMN run_id DROP NOT NULL;
ALTER TABLE wfs.wfs_state_admission_receipts ALTER COLUMN run_id DROP DEFAULT;
ALTER TABLE wfs.wfs_state_admission_receipts ALTER COLUMN message DROP NOT NULL;
ALTER TABLE wfs.wfs_state_admission_receipts ALTER COLUMN message DROP DEFAULT;
ALTER TABLE wfs.wfs_state_admission_work_requests ALTER COLUMN run_id DROP NOT NULL;
ALTER TABLE wfs.wfs_state_admission_work_requests ALTER COLUMN run_id DROP DEFAULT;
ALTER TABLE wfs.wfs_state_admission_work_requests ALTER COLUMN message DROP NOT NULL;
ALTER TABLE wfs.wfs_state_admission_work_requests ALTER COLUMN message DROP DEFAULT;
ALTER TABLE wfs.wfs_state_journal_journal ALTER COLUMN log_path DROP NOT NULL;
ALTER TABLE wfs.wfs_state_journal_journal ALTER COLUMN log_path DROP DEFAULT;
COMMIT;
