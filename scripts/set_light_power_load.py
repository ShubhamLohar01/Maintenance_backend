"""Set mt_asset_list.power_load = '0.04kW' for every light-type asset.

Matches by asset_name containing 'light' (case-insensitive) — covers 'Tubelight',
'Tube Light', 'LED Light', 'Flood Light', etc. Only rows whose power_load actually
differs are touched (idempotent, safe to re-run).

Defaults to a dry run (lists matches, changes nothing) so the match list can be
eyeballed before writing. Pass --apply to actually update.

Usage:
    python -m scripts.set_light_power_load            # dry run
    python -m scripts.set_light_power_load --apply     # writes power_load
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

POWER_LOAD = "0.04kW"

SELECT = text(
    """
    SELECT asset_id, asset_name, building, category, power_load
    FROM mt_asset_list
    WHERE asset_name ILIKE '%light%'
    ORDER BY building, asset_name
    """
)

UPDATE = text(
    """
    UPDATE mt_asset_list
    SET power_load = :power_load
    WHERE asset_name ILIKE '%light%'
      AND power_load IS DISTINCT FROM :power_load
    """
)


def main():
    apply = "--apply" in sys.argv
    with rds_engine.begin() as c:
        rows = c.execute(SELECT).mappings().all()
        print(f"{len(rows)} asset(s) match asset_name ILIKE '%light%':")
        for r in rows:
            print(
                f"  {r['asset_id'] or '':<14} {r['asset_name']:<30} {r['building']:<8} "
                f"category={r['category']!r:<25} power_load={r['power_load']!r} -> {POWER_LOAD!r}"
            )

        if not apply:
            print("\nDry run only — nothing written. Re-run with --apply to update.")
            return

        res = c.execute(UPDATE, {"power_load": POWER_LOAD})
        print(f"\nupdated {res.rowcount} row(s) -> power_load = {POWER_LOAD!r}")


if __name__ == "__main__":
    main()
