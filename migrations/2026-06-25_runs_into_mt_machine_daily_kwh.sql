-- ============================================================================
-- 2026-06-25  Fold production runs INTO mt_machine_daily_kwh; retire mt_machine_runs
--
-- One row per RUN (not one row per machine/day). On START the app inserts a
-- RUNNING row; on STOP the backend fills ended_at + daily_kwh and sets
-- status = 'COMPLETE'. Because a machine can run several times a day, the old
-- UNIQUE(machine_id, reading_date) constraint is DROPPED.
--
-- Run this once against the RDS Postgres DB (pgAdmin). It is idempotent — safe
-- to re-run. Back up the table first if you want a safety net:
--   CREATE TABLE mt_machine_daily_kwh_bak_20260625 AS TABLE mt_machine_daily_kwh;
-- ============================================================================

-- 1) New run / lifecycle columns ------------------------------------------------
ALTER TABLE mt_machine_daily_kwh
    ADD COLUMN IF NOT EXISTS client_run_id  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS operator_id    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS operator_name  VARCHAR(128),
    ADD COLUMN IF NOT EXISTS started_at      TIMESTAMP,
    ADD COLUMN IF NOT EXISTS ended_at        TIMESTAMP,
    ADD COLUMN IF NOT EXISTS status          VARCHAR(16) NOT NULL DEFAULT 'RUNNING';

-- 2) daily_kwh is now NULL while a run is in progress (filled on STOP) ----------
ALTER TABLE mt_machine_daily_kwh ALTER COLUMN daily_kwh DROP NOT NULL;

-- 3) floor may be unknown (was NOT NULL) ---------------------------------------
ALTER TABLE mt_machine_daily_kwh ALTER COLUMN floor DROP NOT NULL;

-- 4) source default flips from 'CALCULATED' to 'RUN' (run rows) -----------------
ALTER TABLE mt_machine_daily_kwh ALTER COLUMN source SET DEFAULT 'RUN';

-- 5) Drop the one-row-per-day uniqueness — multiple runs per day are allowed ----
ALTER TABLE mt_machine_daily_kwh DROP CONSTRAINT IF EXISTS uq_mt_machine_daily;

-- 6) Indexes the Start/Stop/active/live queries rely on ------------------------
CREATE INDEX IF NOT EXISTS idx_mt_daily_client_run ON mt_machine_daily_kwh (client_run_id);
CREATE INDEX IF NOT EXISTS idx_mt_daily_operator   ON mt_machine_daily_kwh (operator_id);
CREATE INDEX IF NOT EXISTS idx_mt_daily_started    ON mt_machine_daily_kwh (started_at);
CREATE INDEX IF NOT EXISTS idx_mt_daily_status     ON mt_machine_daily_kwh (status);

-- 7) Backfill: any pre-existing manual rows were COMPLETE, not RUNNING ----------
--    (they already have a daily_kwh and no run lifecycle). Adjust if undesired.
UPDATE mt_machine_daily_kwh
   SET status = 'COMPLETE'
 WHERE started_at IS NULL AND daily_kwh IS NOT NULL;

-- 8) Retire the old runs table (data already migrated / not needed) -------------
DROP TABLE IF EXISTS mt_machine_runs;
