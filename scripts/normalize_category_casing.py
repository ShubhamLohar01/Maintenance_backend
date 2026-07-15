"""Normalize casing variants in RDS `mt_asset_list.category`.

Collapses lower/other-cased spellings of a category to its canonical Title-Case
value. Two known casing errors as of 2026-07-13:

    Production equipment -> 'Production Equipment'
    Production machine   -> 'Production Machine'

Matching is case-insensitive and whitespace-trimmed (btrim), and only rows whose
value differs from the canonical are updated, so it's idempotent (safe to re-run;
already-canonical rows are skipped). NOT touched: 'Machine handling' (a suspected
typo for 'Material Handling' — a semantic change, left for manual confirmation).

Run once:

    python -m scripts.normalize_category_casing
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

# (canonical value, list of lower-cased trimmed source variants to collapse)
MAPPINGS = [
    ("Production Equipment", ["production equipment"]),
    ("Production Machine", ["production machine"]),
]

UPDATE = text(
    """
    UPDATE mt_asset_list
    SET category = :canonical
    WHERE lower(btrim(category, E' \t\n\r')) = ANY(:variants)
      AND category <> :canonical
    """
)


def main():
    with rds_engine.begin() as c:
        for canonical, variants in MAPPINGS:
            res = c.execute(UPDATE, {"canonical": canonical, "variants": variants})
            print(f"{canonical:22} <- updated {res.rowcount} row(s)")
    print("done.")


if __name__ == "__main__":
    main()
