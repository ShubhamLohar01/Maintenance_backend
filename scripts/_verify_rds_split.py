"""One-time acceptance check for the SQLite/RDS split (Phase 1).

Exercises the real endpoints against the real SQLite + RDS and confirms runs and
daily-kWh land in RDS, while the ERP's other app tables are NOT created.

    python -m scripts._verify_rds_split
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient          # noqa: E402
from sqlalchemy import text                        # noqa: E402
from app.main import app                           # noqa: E402  (import triggers create_all on both engines)
from app.database import rds_engine                # noqa: E402

H = {"Authorization": "Bearer dev-bypass-token"}
NOW = int(datetime.now(timezone.utc).timestamp() * 1000)
client = TestClient(app)


def main():
    # 1) assets are served from RDS
    r = client.get("/mt-machines", headers=H)
    if r.status_code == 401:
        raise SystemExit("401 from /mt-machines — no SQLite OPERATOR user. "
                         "Run `python -m scripts.seed` first, then re-run.")
    assert r.status_code == 200, r.text
    assets = r.json()
    print(f"GET /mt-machines -> {len(assets)} assets (from RDS)")
    asset = next(a for a in assets if a.get("sub_location"))
    mid = asset["asset_id"]
    print(f"using asset_id={mid} (sub_location={asset['sub_location']})")

    # 2) start + stop a run -> one row in RDS mt_machine_daily_kwh
    today = datetime.now(timezone.utc).date().isoformat()
    crid = f"verify-{NOW}"
    start = client.post("/energy/runs/start", headers=H, json={
        "machine_id": mid, "client_run_id": crid,
        "started_at": NOW, "scheduled_end_at": NOW + 3_600_000,
    })
    assert start.status_code == 200, start.text
    run_id = start.json()["run_id"]
    stop = client.post(f"/energy/runs/{run_id}/stop", headers=H,
                       json={"ended_at": NOW + 3_600_000})
    assert stop.status_code == 200, stop.text
    print(f"run {run_id} stopped, computed_kwh={stop.json()['computed_kwh']}")

    # 3) confirm the run row really exists in RDS, and the ERP is not polluted
    with rds_engine.connect() as c:
        run_row = c.execute(
            text("SELECT id, machine_id, operator_name, status, daily_kwh "
                 "FROM mt_machine_daily_kwh WHERE id=:i"),
            {"i": int(run_id)}).first()
        kwh_row = run_row
        assert run_row is not None, "run NOT found in RDS mt_machine_daily_kwh"
        print("RDS mt_machine_daily_kwh row:", tuple(run_row))

        must_be_absent = ["plants", "floors", "machines", "user_machine_assignments",
                          "breakdown_flags", "floor_utility_readings"]
        present = []
        for t in must_be_absent:
            row = c.execute(
                text("SELECT 1 FROM information_schema.tables "
                     "WHERE table_schema='public' AND table_name=:t"), {"t": t}).first()
            if row:
                present.append(t)
        assert not present, f"ERP POLLUTED: app tables created in RDS public schema: {present}"
        print("ERP clean: none of", must_be_absent, "exist in RDS public schema")

    print("\nACCEPTANCE PASS — run row is in RDS; ERP untouched.")
    print(f"(test row left behind: mt_machine_daily_kwh.id={run_id} "
          f"({mid}/{today}) — delete in pgAdmin if undesired)")


if __name__ == "__main__":
    main()
