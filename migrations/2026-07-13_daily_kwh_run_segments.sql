-- ============================================================================
-- 2026-07-13  One mt_machine_daily_kwh row per (machine, date); runs -> segments
--
-- Before: POST /energy/runs/start inserted a NEW mt_machine_daily_kwh row per
-- client_run_id, so every pause->resume / stop->start on the same machine on the
-- same day produced a duplicate daily row (e.g. W202-0052 on 2026-06-27 showed as
-- 3 rows: 0.007 + 0.034 + 12.213 kWh).
--
-- After: there is ONE RUN row per (machine_id, reading_date). Each start->stop is a
-- row in the new child table mt_machine_run_segment; the daily row's daily_kwh is the
-- SUM of its segments, started_at the earliest segment start, ended_at the latest end.
-- SCHEDULE rows (source='SCHEDULE') are untouched.
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the new code. Idempotent
-- (safe to re-run). Back up first if you want a safety net:
--   CREATE TABLE mt_machine_daily_kwh_bak_20260713 AS TABLE mt_machine_daily_kwh;
-- ============================================================================

-- 1) Child table: one row per START->STOP segment ------------------------------
CREATE TABLE IF NOT EXISTS mt_machine_run_segment (
    id            SERIAL PRIMARY KEY,
    daily_id      INTEGER      NOT NULL REFERENCES mt_machine_daily_kwh(id),
    machine_id    VARCHAR(64)  NOT NULL,
    client_run_id VARCHAR(64)  NOT NULL,           -- idempotency key from the app
    operator_id   VARCHAR(64),
    operator_name VARCHAR(128),
    started_at    TIMESTAMP    NOT NULL,
    ended_at      TIMESTAMP,                        -- NULL while open
    status        VARCHAR(16)  NOT NULL DEFAULT 'RUNNING',   -- RUNNING | COMPLETE
    kwh           NUMERIC(14,4),                    -- this segment's kWh (NULL while open)
    source        VARCHAR(16)  NOT NULL DEFAULT 'RUN',
    created_at    TIMESTAMP    DEFAULT now(),
    updated_at    TIMESTAMP    DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_run_segment_client_run ON mt_machine_run_segment (client_run_id);
CREATE INDEX        IF NOT EXISTS idx_run_segment_daily     ON mt_machine_run_segment (daily_id);
CREATE INDEX        IF NOT EXISTS idx_run_segment_machine   ON mt_machine_run_segment (machine_id);
CREATE INDEX        IF NOT EXISTS idx_run_segment_status    ON mt_machine_run_segment (status);
CREATE INDEX        IF NOT EXISTS idx_run_segment_started   ON mt_machine_run_segment (started_at);

-- 2) Audit: turn every existing RUN daily row into a segment, linked to the row that
--    will SURVIVE the collapse (keeper = MIN(id) per machine+date). Re-runnable: skips
--    any client_run_id already present. NULL client_run_ids get a synthetic legacy key.
INSERT INTO mt_machine_run_segment
    (daily_id, machine_id, client_run_id, operator_id, operator_name,
     started_at, ended_at, status, kwh, source, created_at, updated_at)
SELECT
    k.keeper_id,
    d.machine_id,
    COALESCE(d.client_run_id, 'legacy-run-' || d.id),
    d.operator_id,
    d.operator_name,
    COALESCE(d.started_at, now()),
    d.ended_at,
    CASE WHEN d.status = 'RUNNING' THEN 'RUNNING' ELSE 'COMPLETE' END,
    d.daily_kwh,
    'RUN',
    now(), now()
FROM mt_machine_daily_kwh d
JOIN (
    SELECT machine_id, reading_date, MIN(id) AS keeper_id
    FROM mt_machine_daily_kwh
    WHERE source = 'RUN'
    GROUP BY machine_id, reading_date
) k ON k.machine_id = d.machine_id AND k.reading_date = d.reading_date
WHERE d.source = 'RUN'
  AND NOT EXISTS (
      SELECT 1 FROM mt_machine_run_segment s
      WHERE s.client_run_id = COALESCE(d.client_run_id, 'legacy-run-' || d.id)
  );

-- 3) Collapse: fold each group's totals into the keeper row ---------------------
WITH agg AS (
    SELECT machine_id, reading_date,
           MIN(id)                        AS keeper_id,
           SUM(COALESCE(daily_kwh, 0))    AS sum_kwh,
           MIN(started_at)                AS min_start,
           MAX(ended_at)                  AS max_end,
           BOOL_OR(status = 'RUNNING')    AS any_running
    FROM mt_machine_daily_kwh
    WHERE source = 'RUN'
    GROUP BY machine_id, reading_date
)
UPDATE mt_machine_daily_kwh d
SET daily_kwh  = agg.sum_kwh,
    started_at = agg.min_start,
    ended_at   = agg.max_end,
    status     = CASE WHEN agg.any_running THEN 'RUNNING' ELSE 'COMPLETE' END,
    updated_at = now()
FROM agg
WHERE d.id = agg.keeper_id;

-- ...then delete the non-keeper duplicates (their kWh is now in the keeper + segments).
DELETE FROM mt_machine_daily_kwh d
USING (
    SELECT machine_id, reading_date, MIN(id) AS keeper_id
    FROM mt_machine_daily_kwh
    WHERE source = 'RUN'
    GROUP BY machine_id, reading_date
) k
WHERE d.source = 'RUN'
  AND d.machine_id   = k.machine_id
  AND d.reading_date = k.reading_date
  AND d.id <> k.keeper_id;

-- 4) Enforce one RUN row per (machine, date) going forward. PARTIAL so SCHEDULE rows
--    (and any future source) are exempt. The Start flow relies on this for concurrency.
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_run_machine_date
    ON mt_machine_daily_kwh (machine_id, reading_date)
    WHERE source = 'RUN';
