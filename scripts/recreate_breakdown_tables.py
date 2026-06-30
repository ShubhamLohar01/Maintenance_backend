"""DESTRUCTIVE — drop the old mt_breakdown_records and recreate it as the slimmed
live-workflow table, plus the new mt_doc_breakdown (F.06 paper form). Existing rows
are test data and are discarded (per the redesign spec). Run once (RDS reachable):

    python -m scripts.recreate_breakdown_tables
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

DDL = [
    "DROP TABLE IF EXISTS mt_breakdown_records",
    """
    CREATE TABLE mt_breakdown_records (
        id                     SERIAL PRIMARY KEY,
        machine_id             VARCHAR(64),
        machine_name           VARCHAR(255),
        operator_raise_person  VARCHAR(128),
        start_time             TIMESTAMP,
        description            TEXT,
        severity               VARCHAR(16),
        before_photo_url       TEXT,
        status                 VARCHAR(16),
        technician             VARCHAR(128),
        ackn_at                TIMESTAMP,
        work_done_des          TEXT,
        photo_url              TEXT,
        qc_checked_by          VARCHAR(128),
        qc_status              VARCHAR(16),
        qc_reject_reason       TEXT,
        end_time               TIMESTAMP,
        created_at             TIMESTAMP NOT NULL DEFAULT now(),
        updated_at             TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX idx_mt_breakdown_status     ON mt_breakdown_records (status)",
    "CREATE INDEX idx_mt_breakdown_machine_id ON mt_breakdown_records (machine_id)",
    """
    CREATE TABLE IF NOT EXISTS mt_doc_breakdown (
        id                       SERIAL PRIMARY KEY,
        doc_no                   VARCHAR(32) NOT NULL DEFAULT 'CFPLA.C4.F.06',
        sr_no                    INTEGER,
        record_date              DATE,
        location                 VARCHAR(128),
        machine_name             VARCHAR(128),
        equipment_model_no       VARCHAR(128),
        problem_in_brief         TEXT,
        type_of_maintenance      VARCHAR(32),
        part_of_machine          VARCHAR(128),
        temporary_reason         TEXT,
        duration_start           VARCHAR(32),
        duration_end             VARCHAR(32),
        machine_operator_sign    VARCHAR(128),
        maintenance_person_sign  VARCHAR(128),
        qc_clearance_sign        VARCHAR(128),
        verified_by              VARCHAR(128),
        created_by               VARCHAR(128),
        created_at               TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
]


def main():
    with rds_engine.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
            print("ok:", " ".join(stmt.split())[:70])
    print("done — mt_breakdown_records recreated (slim) + mt_doc_breakdown created.")


if __name__ == "__main__":
    main()
