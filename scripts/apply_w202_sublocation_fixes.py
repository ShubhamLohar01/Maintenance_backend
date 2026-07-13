"""Apply the 'correct w202 list.xlsx' sub_location corrections to RDS mt_asset_list.

Only the unambiguous, unique-name matches are applied (keyed by asset_id, so no
fuzzy matching at write time). Ambiguous names (same asset spread across many
floors, no asset_id in the sheet) are intentionally NOT touched. Three assets the
sheet marks 'Removed' are deleted (verified to have no references in
mt_machine_daily_kwh / mt_machine_transfer / mt_breakdown_records / mt_pm_plan /
mt_pm_work_order). Idempotent: updates re-set the same value; deletes are no-ops
once the rows are gone. Run once:

    python -m scripts.apply_w202_sublocation_fixes
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

# asset_id -> canonical sub_location (unique-name matches from correct w202 list.xlsx)
UPDATES = {
    "W202-0031": "Service Floor",        # Environmental Test Chamber
    "W202-0113": "Service Floor",        # HOT AIR OVEN 1
    "W202-0091": "Service Floor",        # Soxhlet Heating Mantle
    "W202-0114": "Service Floor",        # Vacuum Leak test machine
    "W202-0002": "Ground Floor",         # Lift 2 New
    "W202-0129": "Ground Floor",         # Fire Hydrant Main Pump - 20 HP
    "W202-0131": "Ground Floor",         # MIDC Water Supply Pump
    "W202-0132": "Ground Floor",         # UG Tank 1 (MIDC Water) Submersible Pump
    "W202-0133": "Ground Floor",         # UG Tank 2 (Borewell Water) Submersible Pump
    "W202-0279": "Ground Floor Office",  # Printer
    "W202-0281": "Ground Floor Office",  # Epson colour P7000 Printer
    "W202-0280": "Ground Floor Office",  # Skycut Cutting Plotter
    "W202-0283": "Ground Floor Office",  # Sofa
    "W202-0284": "Ground Floor Office",  # TV Unit
    "W202-0291": "Ground Floor Office",  # Ceiling Fan
    "W202-0293": "Ground Floor Office",  # Notice Board
    "W202-0301": "Ground Floor Office",  # Key Cupboard
    "W202-0306": "Ground Floor Office",  # Metal dust bin
    "W202-0304": "Ground Floor Office",  # Sliding Gate
    "W202-0305": "Ground Floor Office",  # Single door gate
}

# asset_ids the sheet marks 'Removed' -> delete (verified no references)
DELETES = ["W202-0128", "W202-0184", "W202-0289"]

UPD = text("UPDATE mt_asset_list SET sub_location=:s WHERE asset_id=:a AND building='W-202'")
DEL = text("DELETE FROM mt_asset_list WHERE asset_id=:a AND building='W-202'")


def main():
    with rds_engine.begin() as c:
        upd = 0
        for aid, sub in UPDATES.items():
            r = c.execute(UPD, {"s": sub, "a": aid})
            if r.rowcount != 1:
                raise SystemExit(f"ABORT: {aid} matched {r.rowcount} rows (expected 1) — rolled back")
            upd += r.rowcount
        print(f"updated {upd} row(s)")
        deleted = 0
        for aid in DELETES:
            r = c.execute(DEL, {"a": aid})
            deleted += r.rowcount
            print(f"  delete {aid}: {r.rowcount} row(s)")
        print(f"deleted {deleted} row(s)")
    print("done.")


if __name__ == "__main__":
    main()
