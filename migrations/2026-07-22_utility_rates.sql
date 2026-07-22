-- ============================================================================
-- 2026-07-22  mt_utility_rates — supervisor-managed current utility prices.
--
-- One row per plant. The rate stamped onto each mt_utility_* reading is copied
-- from here at submit time (app/api/utilities.py); a technician submit cannot
-- change it. Only SUPERVISOR/HEAD/ADMIN edit via PUT /utilities/rates.
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the code. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mt_utility_rates (
    plant            VARCHAR(16) PRIMARY KEY,   -- 'A-185' | 'W-202'
    diesel_rate      NUMERIC(10,2),
    gas_rate         NUMERIC(10,4),
    water_rate       NUMERIC(10,4),
    electricity_rate NUMERIC(10,4),
    set_by           VARCHAR(64),
    set_at           TIMESTAMP DEFAULT now()
);

-- Seed both plants from each plant's most recent existing reading row, so the
-- authoritative rate matches what was already in use. Diesel falls back to 95
-- (its column default) when a plant has no diesel row yet. Re-runnable: existing
-- rows are left untouched (ON CONFLICT DO NOTHING).
INSERT INTO mt_utility_rates (plant, diesel_rate, gas_rate, water_rate, electricity_rate, set_by)
SELECT p.plant,
       COALESCE((SELECT d.diesel_rate       FROM mt_utility_diesel      d WHERE d.plant = p.plant ORDER BY d.reading_date DESC, d.id DESC LIMIT 1), 95),
                (SELECT g.gas_rate           FROM mt_utility_gas         g WHERE g.plant = p.plant ORDER BY g.reading_date DESC, g.id DESC LIMIT 1),
                (SELECT w.water_rate         FROM mt_utility_water       w WHERE w.plant = p.plant ORDER BY w.reading_date DESC, w.id DESC LIMIT 1),
                (SELECT e.electricity_rate   FROM mt_utility_electricity e WHERE e.plant = p.plant ORDER BY e.reading_date DESC, e.id DESC LIMIT 1),
       'seed'
FROM (VALUES ('A-185'), ('W-202')) AS p(plant)
ON CONFLICT (plant) DO NOTHING;
