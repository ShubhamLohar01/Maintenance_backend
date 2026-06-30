"""Copy the real mt_asset_list (864 rows) from the RDS production DB into the
app's local SQLite DB (factoryops.db), so the app can serve the real asset list
via /mt-machines WITHOUT pointing the app at the shared production database.

Read-only on RDS; only writes to local SQLite.

    python -m scripts.sync_assets_to_sqlite --dry-run
    python -m scripts.sync_assets_to_sqlite
"""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]

# columns the SQLite model has (sub_category intentionally excluded)
COLS = [
    "asset_id", "building", "asset_name", "category", "sub_location",
    "quantity", "revised_count_2026", "model_no", "serial_no", "power_load",
    "purchase_date", "purchase_value", "condition", "assigned_to",
    "warranty_amc_expiry", "remarks",
]


def clean(row):
    d = dict(row)
    pv = d.get("purchase_value")
    if pv is not None:
        d["purchase_value"] = float(pv)
    pd = d.get("purchase_date")
    if pd is not None and hasattr(pd, "isoformat"):
        d["purchase_date"] = pd.isoformat()
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(BACKEND / "app" / ".env")
    rds = create_engine(os.environ["DATABASE_URL"], future=True)
    sq = create_engine("sqlite:///./factoryops.db", future=True)

    with rds.begin() as c:
        rows = c.execute(text(f"SELECT {', '.join(COLS)} FROM mt_asset_list ORDER BY id")).mappings().all()
    print(f"read from RDS mt_asset_list: {len(rows)} rows")

    if args.dry_run:
        print("sample:", clean(rows[0]) if rows else None)
        print("[dry-run] nothing written to SQLite.")
        return

    payload = [clean(r) for r in rows]
    ins = text(f"INSERT INTO mt_asset_list ({', '.join(COLS)}) "
               f"VALUES ({', '.join(':' + c for c in COLS)})")
    with sq.begin() as c:
        c.execute(text("DELETE FROM mt_asset_list"))
        c.execute(ins, payload)
        n = c.execute(text("SELECT COUNT(*) FROM mt_asset_list")).scalar()
        bycat = c.execute(text(
            "SELECT category, COUNT(*) FROM mt_asset_list GROUP BY category ORDER BY 2 DESC LIMIT 5")).all()
    print(f"written to SQLite mt_asset_list: {n} rows")
    print("top categories:", bycat)


if __name__ == "__main__":
    main()
