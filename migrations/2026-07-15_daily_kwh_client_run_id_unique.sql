-- ============================================================================
-- 2026-07-15  UNIQUE constraint on mt_machine_daily_kwh.client_run_id
--
-- Closes a race: generate_due_rows() (the Schedule Electric Assets sweep) only
-- checked "does a row with this client_run_id exist?" in application code before
-- inserting — no DB-level constraint backed that check. Two concurrent sweeps (the
-- new in-process 21:00 cron in app/scheduler.py firing at the same moment a
-- supervisor's GET /asset-schedules also triggers the lazy sweep) could both pass
-- the check before either commits, and both insert -> a duplicate row for the same
-- (asset, day), double-counting kWh.
--
-- This adds the real constraint the app logic was assuming existed. Verified zero
-- duplicate non-null client_run_id values in RDS before adding it (safe to run).
-- Postgres allows multiple NULLs under a plain UNIQUE index (NULL <> NULL), so this
-- does not affect RUN-sourced rows (client_run_id is NULL there — see
-- mt_machine_run_segment for the RUN flow's own already-unique client_run_id).
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the app.scheduler.py
-- change. Idempotent. Companion app-code fix: app/api/asset_schedules.py now
-- catches the (now possible) IntegrityError per-row via a SAVEPOINT and skips
-- gracefully instead of crashing the request.
-- ============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_mt_daily_client_run_id
    ON mt_machine_daily_kwh (client_run_id);

-- The old non-unique index (superseded by the constraint above) can be dropped —
-- Postgres uses the unique index for lookups just as well.
DROP INDEX IF EXISTS idx_mt_daily_client_run;
