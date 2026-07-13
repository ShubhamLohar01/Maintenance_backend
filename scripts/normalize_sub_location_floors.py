"""Normalize the standalone floor names in RDS `mt_asset_list.sub_location`.

Collapses casing/whitespace variants of the three floor names to a single
canonical Title-Case value each:

    1st Floor / First Floor            -> 'First Floor'
    2nd floor / 2nd Floor / Second Floor -> 'Second Floor'
    Service floor / Service Floor (+trailing newline) -> 'Service Floor'

Matching is case-insensitive and whitespace-trimmed (btrim), so it also catches
the 'Service Floor\\n' row. Compound values that merely *contain* a floor phrase
(e.g. '1st floor passage', 'Cabin 2nd floor', 'Main packing area 2nd floor') are
NOT touched, because the WHERE clause matches the whole trimmed value, not a
substring. Idempotent (rows already canonical are skipped). Run once:

    python -m scripts.normalize_sub_location_floors
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

# (canonical value, list of lower-cased trimmed source variants to collapse)
MAPPINGS = [
    ("First Floor", ["1st floor", "first floor"]),
    ("Second Floor", ["2nd floor", "second floor"]),
    ("Service Floor", ["service floor"]),
]

UPDATE = text(
    """
    UPDATE mt_asset_list
    SET sub_location = :canonical
    WHERE lower(btrim(sub_location, E' \t\n\r')) = ANY(:variants)
      AND sub_location <> :canonical
    """
)


def main():
    with rds_engine.begin() as c:
        for canonical, variants in MAPPINGS:
            res = c.execute(UPDATE, {"canonical": canonical, "variants": variants})
            print(f"{canonical:15} <- updated {res.rowcount} row(s)")
    print("done.")


if __name__ == "__main__":
    main()
