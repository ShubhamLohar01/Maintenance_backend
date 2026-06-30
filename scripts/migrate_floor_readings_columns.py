"""Idempotently add the missing `daily_kwh` column (the system-generated reading)
to the existing RDS `mt_floor_utility_readings` table. The model + the
/floor-readings endpoints read and write it, but the table was created without it,
so SELECT/INSERT fail with 'column daily_kwh does not exist'. Run once (RDS must be
reachable):

    python -m scripts.migrate_floor_readings_columns
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

DDL = [
    # actual physical meter reading + system-generated daily kWh (both Numeric(14,4))
    "ALTER TABLE mt_floor_utility_readings ADD COLUMN IF NOT EXISTS meter_reading numeric(14,4)",
    "ALTER TABLE mt_floor_utility_readings ADD COLUMN IF NOT EXISTS daily_kwh numeric(14,4)",
]


def main():
    with rds_engine.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
            print("ok:", stmt[:80])
    print("done — mt_floor_utility_readings.daily_kwh present.")


if __name__ == "__main__":
    main()
