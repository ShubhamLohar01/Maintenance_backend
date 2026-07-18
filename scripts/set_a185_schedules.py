"""Set the daily recording schedule for Tubelight / AC / Fan / Fly catcher assets
in warehouse A-185.

  - Tubelight, AC, Fan  -> 09:00-19:00 (9 to 7), every day
  - Fly catcher         -> full 24h, every day

Only category='Electric Asset' rows are touched — that's what the scheduler /
daily generator (app/api/asset_schedules.py) actually reads; a matching asset_name
under any other category would silently never generate rows even with these
columns set, so those are reported separately instead of written.

Name matching (building='A-185', category='Electric Asset'):
  tubelight : asset_name ILIKE '%tube%light%'
  ac        : asset_name ~* '\\yac\\y' OR asset_name ILIKE '%a/c%', excluding '%panel%'
              (excludes 'Acrylic glass' / 'Acryclic ...' and 'Cold storage AC panel')
  fan       : asset_name ILIKE '%fan%'
  flycatcher: asset_name ILIKE '%fly%catch%'

Defaults to a dry run (lists matches + current schedule, changes nothing).
Pass --apply to actually write; a CSV backup of prior values is saved either way
is NOT taken automatically here (see set_light_power_load.py for that pattern) —
this print output IS the record of prior state, redirect it to a file if wanted.

Usage:
    python -m scripts.set_a185_schedules            # dry run
    python -m scripts.set_a185_schedules --apply     # writes the schedule
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

BUILDING = "A-185"
DAY_9_TO_7 = (9 * 60, 19 * 60)  # 540, 1140

GROUPS = {
    "tubelight": {
        "cond": "asset_name ILIKE '%tube%light%'",
        "start_min": DAY_9_TO_7[0], "end_min": DAY_9_TO_7[1], "is_24h": False,
    },
    "ac": {
        "cond": r"(asset_name ~* '\yac\y' OR asset_name ILIKE '%a/c%') AND asset_name NOT ILIKE '%panel%'",
        "start_min": DAY_9_TO_7[0], "end_min": DAY_9_TO_7[1], "is_24h": False,
    },
    "fan": {
        "cond": "asset_name ILIKE '%fan%'",
        "start_min": DAY_9_TO_7[0], "end_min": DAY_9_TO_7[1], "is_24h": False,
    },
    "flycatcher": {
        "cond": "asset_name ILIKE '%fly%catch%'",
        "start_min": 0, "end_min": 1440, "is_24h": True,
    },
}

SELECT_SQL = """
    SELECT asset_id, asset_name, category, schedule_start_min, schedule_end_min,
           schedule_active, schedule_is_24h
    FROM mt_asset_list
    WHERE building = :building AND {cond}
    ORDER BY category, asset_name
"""

UPDATE_SQL = """
    UPDATE mt_asset_list
    SET schedule_start_min = :start_min,
        schedule_end_min = :end_min,
        schedule_active = true,
        schedule_is_24h = :is_24h,
        schedule_updated_by = :updated_by,
        schedule_updated_at = now()
    WHERE building = :building AND category = 'Electric Asset' AND ({cond})
"""

UPDATED_BY = "bulk-script:set_a185_schedules"


def main():
    apply = "--apply" in sys.argv
    with rds_engine.begin() as c:
        for label, g in GROUPS.items():
            rows = c.execute(
                text(SELECT_SQL.format(cond=g["cond"])), {"building": BUILDING}
            ).mappings().all()
            electric = [r for r in rows if r["category"] == "Electric Asset"]
            other = [r for r in rows if r["category"] != "Electric Asset"]

            print(f"--- {label}: {len(electric)} 'Electric Asset' row(s) to schedule "
                  f"(start_min={g['start_min']}, end_min={g['end_min']}, is_24h={g['is_24h']}) ---")
            for r in electric:
                print(f"  {r['asset_id']:<12} {r['asset_name']:<24} "
                      f"current: start={r['schedule_start_min']} end={r['schedule_end_min']} "
                      f"active={r['schedule_active']} is_24h={r['schedule_is_24h']}")
            if other:
                print(f"  SKIPPED (not category='Electric Asset', can't be scheduled -> "
                      f"won't generate daily rows even if written):")
                for r in other:
                    print(f"    {r['asset_id']:<12} {r['asset_name']:<24} category={r['category']!r}")
            print()

            if apply and electric:
                res = c.execute(
                    text(UPDATE_SQL.format(cond=g["cond"])),
                    {
                        "building": BUILDING,
                        "start_min": g["start_min"],
                        "end_min": g["end_min"],
                        "is_24h": g["is_24h"],
                        "updated_by": UPDATED_BY,
                    },
                )
                print(f"  -> updated {res.rowcount} row(s)\n")

        if not apply:
            print("Dry run only — nothing written. Re-run with --apply to write the schedule.")


if __name__ == "__main__":
    main()
