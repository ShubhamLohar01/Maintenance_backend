-- ============================================================================
-- 2026-07-16  mt_machine_daily_kwh.asset_name (denormalized snapshot)
--
-- Same pattern as the existing `building` / `floor` / `operator_name` columns on
-- this table: a copy of mt_asset_list.asset_name taken at row-creation time (see
-- app/api/energy.py start_run() and app/api/asset_schedules.py _try_insert_schedule_row()),
-- so reads never need to join back to the asset register. Idempotent — safe to re-run.
-- ============================================================================

ALTER TABLE mt_machine_daily_kwh ADD COLUMN IF NOT EXISTS asset_name VARCHAR(255);

-- Backfill rows that already exist (created before this column was added).
-- No-op once every row has asset_name set.
UPDATE mt_machine_daily_kwh d
SET asset_name = a.asset_name
FROM mt_asset_list a
WHERE d.machine_id = a.asset_id
  AND d.asset_name IS NULL;
