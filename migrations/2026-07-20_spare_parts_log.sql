-- ============================================================================
-- 2026-07-20  mt_202_spareparts_log — usage/restock audit trail
--
-- mt_202_spareparts (pre-existing, W-202 only, 113 rows) gets a quantity write
-- path (POST /spare-parts/{id}/use, /restock — see app/api/spare_parts.py). This
-- table records every such action (who/when/how much) so stock discrepancies
-- can be traced later; no dedicated history screen ships yet, but the data is
-- captured from day one.
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the code. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mt_202_spareparts_log (
    id                SERIAL PRIMARY KEY,
    spare_part_id     INTEGER NOT NULL REFERENCES mt_202_spareparts(id),
    machine_name      VARCHAR(255),
    part_name         VARCHAR(255),
    action            VARCHAR(16) NOT NULL,   -- 'USE' | 'RESTOCK'
    quantity          INTEGER NOT NULL,       -- always positive; sign implied by action
    note              TEXT,
    performed_by      VARCHAR(64),
    performed_by_name VARCHAR(128),
    performed_at      TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_spareparts_log_part ON mt_202_spareparts_log (spare_part_id);
