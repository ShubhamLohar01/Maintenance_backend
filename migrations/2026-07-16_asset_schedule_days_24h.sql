-- ============================================================================
-- 2026-07-16  mt_asset_list.schedule_days + schedule_is_24h
--
-- Schedule Electric Assets: per-weekday toggles + a full-24h flag, alongside the
-- existing schedule_start_min/end_min/active columns. See app/api/asset_schedules.py.
--
-- schedule_days: comma-separated 3-letter weekday codes (SUN,MON,TUE,WED,THU,FRI,SAT),
--                e.g. 'MON,WED,FRI'. NULL/empty = every day (old rows keep firing daily).
-- schedule_is_24h: when true, the daily generator uses a full 24h window and ignores
--                  schedule_start_min/schedule_end_min.
--
-- Idempotent — safe to re-run.
-- ============================================================================

ALTER TABLE mt_asset_list ADD COLUMN IF NOT EXISTS schedule_days VARCHAR(32);
ALTER TABLE mt_asset_list ADD COLUMN IF NOT EXISTS schedule_is_24h BOOLEAN NOT NULL DEFAULT false;
