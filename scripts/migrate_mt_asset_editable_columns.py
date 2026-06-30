"""Idempotently add the editable asset-register columns to the existing RDS
`mt_asset_list` table. The model declares `model_no`, `serial_no`, `remarks` and
the GET + PUT /mt-machines endpoints read/write them, but if the table was created
before a column was added, SELECT/UPDATE fail with 'column ... does not exist'.
Safe to run repeatedly (ADD COLUMN IF NOT EXISTS). Run once (RDS must be reachable):

    python -m scripts.migrate_mt_asset_editable_columns
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

DDL = [
    "ALTER TABLE mt_asset_list ADD COLUMN IF NOT EXISTS model_no varchar(255)",
    "ALTER TABLE mt_asset_list ADD COLUMN IF NOT EXISTS serial_no varchar(255)",
    "ALTER TABLE mt_asset_list ADD COLUMN IF NOT EXISTS remarks text",
]


def main():
    with rds_engine.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
            print("ok:", stmt[:80])
    print("done — mt_asset_list.model_no / serial_no / remarks present.")


if __name__ == "__main__":
    main()
