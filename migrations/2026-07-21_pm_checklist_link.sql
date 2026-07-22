-- Links a PM asset to its row in a controlled checklist form (50a/50b) so a QC-closed
-- PM work order can flip that row's cells in the month/quarter document.
-- (Already applied to RDS by the seed script; this file documents the DDL for other envs.)

CREATE TABLE IF NOT EXISTS pm_checklist_link (
    id        SERIAL PRIMARY KEY,
    asset_id  VARCHAR(32)  NOT NULL,          -- = mt_asset_list.asset_id
    form_type VARCHAR(16)  NOT NULL,          -- MONTHLY | QUARTERLY
    section   VARCHAR(255) NOT NULL,
    sr_no     INTEGER,                         -- the form row this asset fills
    equipment VARCHAR(255) NOT NULL,          -- checklist equipment name
    CONSTRAINT uq_pm_link_asset_form UNIQUE (asset_id, form_type)
);
CREATE INDEX IF NOT EXISTS ix_pm_checklist_link_asset_id ON pm_checklist_link (asset_id);

-- Seed rows are generated from the asset<->checklist fuzzy match (high-confidence only);
-- see scratchpad/seed_links.py. 68 rows seeded 2026-07-21 (47 MONTHLY, 21 QUARTERLY).
