-- ============================================================================
-- 2026-07-15  Utility Consumption tables (Diesel / Gas / Electricity / Water)
--
-- One row per (plant, reading_date). Sourced from "Utility Consumption 2026-2027.xlsx"
-- (A-185 + W-202 blocks folded into `plant`). Derived columns are PLAIN (not GENERATED):
-- the Android app computes them client-side and POSTs them; the backend (app/api/
-- utilities.py) upserts on (plant, reading_date) and stores what it receives.
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the code. Idempotent.
-- Formulas (for reference; enforced client-side):
--   diesel: total_consumption=final-initial; total_run_hour=stop-start;
--           total_diesel_l=diesel_l_per_hour*total_run_hour; total_fuel_cost=total_diesel_l*diesel_rate
--   gas:    gas_consumed_m3=(close-open)*gas_conversion_factor; daily_gas_cost=gas_consumed_m3*gas_rate;
--           cost_per_unit=daily_gas_cost/production_units
--   elec:   consumed_kwh=(close_kwh-open_kwh)*ct_multiplier; consumed_kvah=close_kvah-open_kvah;
--           daily_cost=consumed_kwh*rate; cost_per_unit=daily_cost/production_units
--   water:  water_consumed=close-open; daily_water_cost=water_consumed*water_rate;
--           cost_per_unit=daily_water_cost/production_units
-- ============================================================================

CREATE TABLE IF NOT EXISTS mt_utility_diesel (
    id                  SERIAL PRIMARY KEY,
    plant               VARCHAR(16) NOT NULL,
    reading_date        DATE        NOT NULL,
    initial_kwh_reading NUMERIC(14,2),
    final_kwh_reading   NUMERIC(14,2),
    start_dg_run_hour   NUMERIC(10,2),
    stop_dg_run_hour    NUMERIC(10,2),
    diesel_l_per_hour   NUMERIC(10,3) DEFAULT 37.5,
    diesel_rate         NUMERIC(10,2) DEFAULT 95,
    diesel_received_l   NUMERIC(12,2),
    remark              TEXT,
    total_consumption   NUMERIC(14,2),   -- app-computed
    total_run_hour      NUMERIC(10,2),   -- app-computed
    total_diesel_l      NUMERIC(14,3),   -- app-computed
    total_fuel_cost     NUMERIC(16,2),   -- app-computed
    created_by          VARCHAR(64),
    created_at          TIMESTAMP DEFAULT now(),
    updated_at          TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_utility_diesel UNIQUE (plant, reading_date)
);
CREATE INDEX IF NOT EXISTS idx_utility_diesel_date ON mt_utility_diesel (reading_date);

CREATE TABLE IF NOT EXISTS mt_utility_gas (
    id                    SERIAL PRIMARY KEY,
    plant                 VARCHAR(16) NOT NULL,
    reading_date          DATE        NOT NULL,
    gas_meter_opening     NUMERIC(14,3),
    gas_meter_closing     NUMERIC(14,3),
    gas_conversion_factor NUMERIC(8,4) DEFAULT 1.44,
    gas_rate              NUMERIC(10,4),
    production_units      NUMERIC(14,3),
    remark                TEXT,
    gas_consumed_m3       NUMERIC(16,4),   -- app-computed
    daily_gas_cost        NUMERIC(16,4),   -- app-computed
    cost_per_unit         NUMERIC(16,4),   -- app-computed
    created_by            VARCHAR(64),
    created_at            TIMESTAMP DEFAULT now(),
    updated_at            TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_utility_gas UNIQUE (plant, reading_date)
);
CREATE INDEX IF NOT EXISTS idx_utility_gas_date ON mt_utility_gas (reading_date);

CREATE TABLE IF NOT EXISTS mt_utility_electricity (
    id                        SERIAL PRIMARY KEY,
    plant                     VARCHAR(16) NOT NULL,
    reading_date              DATE        NOT NULL,
    department                VARCHAR(64),
    energy_meter_opening_kwh  NUMERIC(14,2),
    energy_meter_closing_kwh  NUMERIC(14,2),
    energy_meter_opening_kvah NUMERIC(14,2),
    energy_meter_closing_kvah NUMERIC(14,2),
    ct_multiplier             NUMERIC(8,3) DEFAULT 4,
    electricity_rate          NUMERIC(10,4),
    production_units          NUMERIC(14,3),
    remark                    TEXT,
    electricity_consumed_kwh  NUMERIC(16,3),   -- app-computed
    electricity_consumed_kvah NUMERIC(16,3),   -- app-computed
    daily_electricity_cost    NUMERIC(16,2),   -- app-computed
    cost_per_unit             NUMERIC(16,4),   -- app-computed
    created_by                VARCHAR(64),
    created_at                TIMESTAMP DEFAULT now(),
    updated_at                TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_utility_electricity UNIQUE (plant, reading_date)
);
CREATE INDEX IF NOT EXISTS idx_utility_electricity_date ON mt_utility_electricity (reading_date);

CREATE TABLE IF NOT EXISTS mt_utility_water (
    id                  SERIAL PRIMARY KEY,
    plant               VARCHAR(16) NOT NULL,
    reading_date        DATE        NOT NULL,
    water_meter_opening NUMERIC(14,3),
    water_meter_closing NUMERIC(14,3),
    water_rate          NUMERIC(10,4),
    production_units    NUMERIC(14,3),
    remark              TEXT,
    water_consumed      NUMERIC(16,3),   -- app-computed
    daily_water_cost    NUMERIC(16,2),   -- app-computed
    cost_per_unit       NUMERIC(16,4),   -- app-computed
    created_by          VARCHAR(64),
    created_at          TIMESTAMP DEFAULT now(),
    updated_at          TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_utility_water UNIQUE (plant, reading_date)
);
CREATE INDEX IF NOT EXISTS idx_utility_water_date ON mt_utility_water (reading_date);

-- Safe to re-run: if these tables were already created (by an earlier run of this
-- file, before `created_by` was added below), backfill the column on each.
ALTER TABLE mt_utility_diesel       ADD COLUMN IF NOT EXISTS created_by VARCHAR(64);
ALTER TABLE mt_utility_gas          ADD COLUMN IF NOT EXISTS created_by VARCHAR(64);
ALTER TABLE mt_utility_electricity  ADD COLUMN IF NOT EXISTS created_by VARCHAR(64);
ALTER TABLE mt_utility_water        ADD COLUMN IF NOT EXISTS created_by VARCHAR(64);
