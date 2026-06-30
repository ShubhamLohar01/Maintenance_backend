# Split DB: Maintenance runs & readings → RDS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make production runs and daily-kWh readings persist to the RDS Postgres database (visible in pgAdmin) while login/users and the rest of the app stay on local SQLite.

**Architecture:** Two SQLAlchemy engines built from two config URLs — `local_engine` (SQLite, auth + app-internal tables) and `rds_engine` (Postgres, maintenance tables). Models are split across two declarative bases (`LocalBase`, `RdsBase`); the `energy` and `mt_machines` routers use the RDS session (`get_rds`) while every other router and `get_current_user` stay on SQLite (`get_db`). The cross-database `ProductionRun.operator_id → users.id` foreign key is dropped.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, pydantic-settings, psycopg2, pytest, SQLite + AWS RDS PostgreSQL.

**Spec:** [docs/superpowers/specs/2026-06-20-split-db-rds-maintenance-design.md](../specs/2026-06-20-split-db-rds-maintenance-design.md)

---

## ⚠️ Environment notes (read first)

- **Working directory for all commands is the backend root:** `d:\Maintenance module\backend`. The `.env` file (which supplies the RDS `DATABASE_URL`) lives there and pydantic reads it relative to the current directory. Run every command from there.
- **This project is NOT a git repository.** "Checkpoint" steps below are verification pauses, not commits. If you want commits, run `git init` once first; otherwise just confirm the checkpoint state and continue.
- **RDS network access is required** for Task 3 (the verification connects to RDS). The same machine already reaches RDS read-only.
- These files already exist and will be modified: `app/config.py`, `app/database.py`, `app/models.py`, `app/main.py`, `app/api/energy.py`, `app/api/mt_machines.py`, `scripts/seed.py`, `requirements.txt`.

---

## File structure

| File | Responsibility after this change |
|---|---|
| `app/config.py` | Two connection URLs: `local_database_url` (SQLite), `rds_database_url` (Postgres, aliased to env `DATABASE_URL`). |
| `app/database.py` | Two engines, two sessionmakers, two bases (`LocalBase`/`RdsBase`), two deps (`get_db`/`get_rds`). |
| `app/models.py` | Auth/internal models on `LocalBase`; maintenance models (`MtAsset`, `MachineDailyKwh`, `ProductionRun`) on `RdsBase`; no cross-DB FK. |
| `app/main.py` | `create_all` on **both** engines (RDS gets only the 3 maintenance tables). |
| `app/api/energy.py` | Runs endpoints use `get_rds`. |
| `app/api/mt_machines.py` | Asset/daily-kWh endpoints use `get_rds`. |
| `scripts/seed.py` | Seeds SQLite via the renamed local symbols. |
| `tests/test_db_split.py` | (new) Structural invariants of the split. |
| `scripts/_verify_rds_split.py` | (new) One-time end-to-end RDS acceptance check. |

---

## Task 1: Two engines + two bases (structural refactor)

This is one atomic unit: renaming `Base`/`engine` touches five files at once, and the app will not import until all are consistent. Do the steps in order.

**Files:**
- Test: `tests/test_db_split.py` (create)
- Modify: `app/config.py` (full rewrite of the `Settings` class)
- Modify: `app/database.py` (full rewrite)
- Modify: `app/models.py:5`, and the `class X(Base)` declarations + `ProductionRun.operator_id`
- Modify: `app/main.py:4`, `app/main.py:9`
- Modify: `scripts/seed.py:19`, `scripts/seed.py:251`
- Modify: `requirements.txt` (add psycopg2)

- [ ] **Step 1: Write the failing structural test**

Create `tests/test_db_split.py`:

```python
from app.database import LocalBase, RdsBase
from app.models import ProductionRun

LOCAL_EXPECTED = {
    "users", "plants", "floors", "machines",
    "user_machine_assignments", "breakdown_flags", "floor_utility_readings",
}
RDS_EXPECTED = {"mt_asset_list", "mt_machine_daily_kwh", "production_runs"}


def test_local_base_owns_auth_and_internal_tables():
    assert set(LocalBase.metadata.tables) == LOCAL_EXPECTED


def test_rds_base_owns_only_maintenance_tables():
    assert set(RdsBase.metadata.tables) == RDS_EXPECTED


def test_production_run_has_no_cross_db_fk():
    # operator_id must not carry a FK to the SQLite-only users table
    assert len(ProductionRun.__table__.c.operator_id.foreign_keys) == 0
    all_fks = [fk for col in ProductionRun.__table__.columns for fk in col.foreign_keys]
    assert all_fks == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `d:\Maintenance module\backend`):
```
python -m pytest tests/test_db_split.py -v
```
Expected: **collection error / FAIL** — `ImportError: cannot import name 'LocalBase' from 'app.database'`.

- [ ] **Step 3: Rewrite `app/config.py`**

Replace the entire file with:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Local SQLite — auth/login + app-internal data (machines, floors, breakdowns, utility).
    local_database_url: str = "sqlite:///./factoryops.db"

    # RDS Postgres — maintenance tables visible in pgAdmin (assets, runs, daily-kWh).
    # Reuses the existing `.env` DATABASE_URL value.
    rds_database_url: str = Field(validation_alias="DATABASE_URL")

    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expires_hours: int = 8
    dev_bypass_token: str = "dev-bypass-token"
    cost_per_kwh: float = 8.5
    power_factor: float = 0.99  # fixed; used for kWh = rated_kw * hours * power_factor


settings = Settings()
```

- [ ] **Step 4: Rewrite `app/database.py`**

Replace the entire file with:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from .config import settings


# --- Local SQLite engine: auth + app-internal tables ---
_local_connect_args = (
    {"check_same_thread": False}
    if settings.local_database_url.startswith("sqlite")
    else {}
)
local_engine = create_engine(
    settings.local_database_url, connect_args=_local_connect_args, future=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=local_engine, future=True)


# --- RDS Postgres engine: maintenance tables (visible in pgAdmin) ---
rds_engine = create_engine(settings.rds_database_url, future=True)
SessionRds = sessionmaker(autocommit=False, autoflush=False, bind=rds_engine, future=True)


class LocalBase(DeclarativeBase):
    """Tables that live in the local SQLite DB (auth + app-internal)."""
    pass


class RdsBase(DeclarativeBase):
    """Tables that live in the RDS Postgres DB (maintenance, pgAdmin-visible)."""
    pass


def get_db():
    """SQLite session — auth and app-internal data."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_rds():
    """RDS Postgres session — maintenance tables (runs, readings, assets)."""
    db: Session = SessionRds()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 5: Update `app/models.py` — split bases + drop the cross-DB FK**

5a. Change the import on line 5:
```python
from .database import Base
```
to:
```python
from .database import LocalBase, RdsBase
```

5b. Change the base class on each model declaration. **LocalBase** for these seven:
```python
class Plant(LocalBase):
class Floor(LocalBase):
class Machine(LocalBase):
class User(LocalBase):
class UserMachineAssignment(LocalBase):
class BreakdownFlag(LocalBase):
class FloorUtilityReading(LocalBase):
```
**RdsBase** for these three:
```python
class MtAsset(RdsBase):
class MachineDailyKwh(RdsBase):
class ProductionRun(RdsBase):
```
(Each currently reads `class X(Base):` — change only the base name in the parentheses; leave everything else untouched.)

5c. In `class ProductionRun`, drop the foreign key on `operator_id`. Change:
```python
    operator_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
```
to:
```python
    operator_id: Mapped[str] = mapped_column(String(64), index=True)
```
Leave the `ForeignKey` import — it is still used by `Floor`, `Machine`, `User`, `UserMachineAssignment`, and `BreakdownFlag`.

- [ ] **Step 6: Update `app/main.py` — create_all on both engines**

6a. Change the import on line 4:
```python
from .database import Base, engine
```
to:
```python
from .database import LocalBase, RdsBase, local_engine, rds_engine
```

6b. Change the create_all line (line 9) inside `create_app()`:
```python
    Base.metadata.create_all(bind=engine)
```
to:
```python
    LocalBase.metadata.create_all(bind=local_engine)
    RdsBase.metadata.create_all(bind=rds_engine)  # RDS gets only the 3 maintenance tables
```

- [ ] **Step 7: Update `scripts/seed.py` — use the local symbols**

7a. Change line 19:
```python
from app.database import Base, engine, SessionLocal  # noqa: E402
```
to:
```python
from app.database import LocalBase, local_engine, SessionLocal  # noqa: E402
```

7b. Change line 251 inside `main()`:
```python
    Base.metadata.create_all(bind=engine)
```
to:
```python
    LocalBase.metadata.create_all(bind=local_engine)
```

- [ ] **Step 8: Pin the Postgres driver in `requirements.txt`**

Append this line to `requirements.txt`:
```
psycopg2-binary==2.9.10
```
(psycopg2 is already installed in the environment; this records it for reproducibility.)

- [ ] **Step 9: Run the structural test — expect PASS**

Run (from backend root):
```
python -m pytest tests/test_db_split.py -v
```
Expected: **3 passed** — `test_local_base_owns_auth_and_internal_tables`, `test_rds_base_owns_only_maintenance_tables`, `test_production_run_has_no_cross_db_fk`.

- [ ] **Step 10: Import smoke (no RDS side effects)**

Run (from backend root):
```
python -c "import app.config, app.database, app.models; print('import ok:', app.config.settings.local_database_url, '|', app.config.settings.rds_database_url.split('@')[-1])"
```
Expected: `import ok: sqlite:///./factoryops.db | wms-postgres-db.cpis084golp7.ap-south-1.rds.amazonaws.com:5432/warehouse_db`
(Importing these three modules does **not** trigger `create_all`, so no RDS writes happen here — that is deliberate.)

- [ ] **Step 11: Checkpoint**

State: models split across two bases, app imports cleanly, structural test green. No endpoint behavior changed yet (energy/mt_machines still use `get_db` → SQLite). Proceed to Task 2.

---

## Task 2: Point the maintenance endpoints at RDS

**Files:**
- Modify: `app/api/energy.py:8` and its 3 `Depends(get_db)` occurrences
- Modify: `app/api/mt_machines.py:7` and its 2 `Depends(get_db)` occurrences

- [ ] **Step 1: Repoint `app/api/energy.py`**

1a. Change the import (line 8):
```python
from ..database import get_db
```
to:
```python
from ..database import get_rds
```

1b. Replace **all** occurrences of `Depends(get_db)` with `Depends(get_rds)` in this file (there are 3: `start_run`, `stop_run`, `machine_history`). Each looks like:
```python
    db: Session = Depends(get_db),
```
→
```python
    db: Session = Depends(get_rds),
```
Leave the `user: User = Depends(get_current_user)` lines unchanged — `get_current_user` stays on SQLite.

- [ ] **Step 2: Repoint `app/api/mt_machines.py`**

2a. Change the import (line 7):
```python
from ..database import get_db
```
to:
```python
from ..database import get_rds
```

2b. Replace **all** occurrences of `Depends(get_db)` with `Depends(get_rds)` in this file (there are 2: `list_mt_machines`, `upsert_asset_daily_kwh`). Leave the `get_current_user` dependency unchanged.

- [ ] **Step 3: Verify no `get_db` remains in the two maintenance routers**

Run (from backend root):
```
python -c "import re,io; [print(f, 'get_db:', open(f).read().count('get_db'), '| get_rds:', open(f).read().count('get_rds')) for f in ['app/api/energy.py','app/api/mt_machines.py']]"
```
Expected:
```
app/api/energy.py get_db: 0 | get_rds: 4
app/api/mt_machines.py get_db: 0 | get_rds: 3
```
(`get_rds` count = 1 import + N `Depends(...)`. energy = 1+3, mt_machines = 1+2.)

- [ ] **Step 4: Confirm the other routers still use SQLite (unchanged)**

Run (from backend root):
```
python -c "[print(f, 'get_db:', open(f).read().count('get_db')) for f in ['app/api/auth.py','app/api/machines.py','app/api/breakdowns.py','app/api/floors.py']]"
```
Expected: each still references `get_db` (non-zero); they were not touched.

- [ ] **Step 5: Checkpoint**

State: maintenance endpoints now bind to RDS; all imports resolve. Verified end-to-end in Task 3.

---

## Task 3: End-to-end RDS acceptance check

Proves that login works on SQLite, runs/readings write to RDS, and the ERP schema is not polluted. Uses FastAPI's in-process `TestClient` and the dev-bypass token (so no real passwords are needed). Importing the app triggers `create_all`, which creates `production_runs` in RDS (the only new table).

**Files:**
- Create: `scripts/_verify_rds_split.py`

- [ ] **Step 1: Create the verification script**

Create `scripts/_verify_rds_split.py`:

```python
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
    asset = next(a for a in assets if a.get("sub_location"))  # floor is NOT NULL in mt_machine_daily_kwh
    mid = asset["asset_id"]
    print(f"using asset_id={mid} (sub_location={asset['sub_location']})")

    # 2) start + stop a run -> RDS production_runs
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

    # 3) daily-kWh upsert -> RDS mt_machine_daily_kwh
    today = datetime.now(timezone.utc).date().isoformat()
    kwh = client.post(f"/mt-machines/{mid}/daily-kwh", headers=H, json={
        "machine_id": mid, "reading_date": today, "daily_kwh": 12.5, "source": "CALCULATED",
    })
    assert kwh.status_code == 200, kwh.text
    print(f"daily-kWh saved for {mid} on {today}")

    # 4) confirm the rows really exist in RDS, and the ERP is not polluted
    with rds_engine.connect() as c:
        run_row = c.execute(
            text("SELECT id, machine_id, computed_kwh FROM production_runs WHERE id=:i"),
            {"i": run_id}).first()
        kwh_row = c.execute(
            text("SELECT machine_id, reading_date, daily_kwh FROM mt_machine_daily_kwh "
                 "WHERE machine_id=:m AND reading_date=:d"), {"m": mid, "d": today}).first()
        assert run_row is not None, "run NOT found in RDS production_runs"
        assert kwh_row is not None, "reading NOT found in RDS mt_machine_daily_kwh"
        print("RDS production_runs row:", tuple(run_row))
        print("RDS mt_machine_daily_kwh row:", tuple(kwh_row))

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

    print("\nACCEPTANCE PASS — runs + readings are in RDS; ERP untouched.")
    print(f"(test rows left behind: production_runs.id={run_id}; "
          f"mt_machine_daily_kwh {mid}/{today} — delete in pgAdmin if undesired)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ensure a SQLite operator exists (only if Step 3 reports 401)**

`factoryops.db` already has operator users, so this is normally unnecessary. If Step 3 raises the 401 message, run:
```
python -m scripts.seed
```
Expected: `[seed] done -- machines=..., floors=..., utility_rows=...`.

- [ ] **Step 3: Run the end-to-end acceptance**

Run (from backend root):
```
python -m scripts._verify_rds_split
```
Expected (machine_id/run_id/kWh values will vary):
```
GET /mt-machines -> 864 assets (from RDS)
using asset_id=... (sub_location=...)
run run-... stopped, computed_kwh=...
daily-kWh saved for ... on 2026-06-20
RDS production_runs row: ('run-...', '...', ...)
RDS mt_machine_daily_kwh row: ('...', datetime.date(2026, 6, 19), Decimal('12.5000'))
ERP clean: none of ['plants', 'floors', 'machines', 'user_machine_assignments', 'breakdown_flags', 'floor_utility_readings'] exist in RDS public schema
ACCEPTANCE PASS — runs + readings are in RDS; ERP untouched.
```

- [ ] **Step 4: Confirm visually in pgAdmin**

In pgAdmin, run against the RDS `warehouse_db` / `public` schema:
```sql
SELECT id, machine_id, operator_id, computed_kwh, started_at, ended_at
FROM production_runs ORDER BY created_at DESC LIMIT 5;

SELECT machine_id, reading_date, building, floor, daily_kwh, source
FROM mt_machine_daily_kwh ORDER BY updated_at DESC LIMIT 5;
```
Expected: the run and reading written by Step 3 are present.

- [ ] **Step 5: Checkpoint — done**

State: Phase 1 complete. Runs and daily-kWh readings persist to RDS and are visible in pgAdmin; login and the other modules remain on SQLite; the 541-table ERP gained only `production_runs`. Delete the two test rows in pgAdmin if you don't want them.

---

## Self-review notes (author)

- **Spec coverage:** config two URLs (T1/S3) ✓; two engines+bases+deps (T1/S4) ✓; model split + FK drop (T1/S5) ✓; create_all both engines, RDS-only 3 tables (T1/S6) ✓; energy+mt_machines → get_rds, auth stays SQLite (T2) ✓; hazard fix — single-engine-on-RDS removed (T1/S4+S6) ✓; error behavior verified live (T3) ✓; manual e2e acceptance + no-ERP-pollution assertion (T3) ✓; structural automated test for disjoint table sets + no users FK (T1/S1) ✓.
- **Out of scope (Phase 2), intentionally not in plan:** migrating machines/floors/breakdowns/utility + seed rows to RDS; moving users/auth to RDS; dual-write.
- **Type/name consistency:** `LocalBase`/`RdsBase`/`local_engine`/`rds_engine`/`get_db`/`get_rds`/`SessionLocal`/`SessionRds` used identically across config, database, models, main, seed, energy, mt_machines, and both new files.
