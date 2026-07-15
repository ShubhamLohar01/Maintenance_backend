-- ============================================================================
-- 2026-07-15  mt_breakdown_records.technician_id — acknowledger's user id
--
-- GET /breakdowns/open previously returned only the acknowledging technician's NAME
-- (`technician`), not their user id — so the Android app couldn't match "my active
-- tickets" by id on a device other than the one that tapped Acknowledge. This adds
-- the id column; POST /breakdowns/{id}/qc/acknowledge (technician path) now stamps
-- it, and GET /breakdowns/open returns it as `acknowledged_by` (+ `acknowledged_by_name`).
--
-- Existing already-acknowledged rows keep technician_id NULL (name-only) — no
-- backfill needed; they naturally get an id the next time that ticket is
-- acknowledged again (e.g. after a QC disapprove -> re-acknowledge cycle).
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the code. Idempotent.
-- ============================================================================

ALTER TABLE mt_breakdown_records
    ADD COLUMN IF NOT EXISTS technician_id VARCHAR(64);
