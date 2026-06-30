# Split DB: Maintenance runs & readings → RDS (auth stays on SQLite)

**Date:** 2026-06-20
**Status:** Approved (design); pending implementation plan
**Owner:** ai.1@candorfoods.in

## 1. Problem

The FactoryOps maintenance backend currently builds a **single** SQLAlchemy
engine from `settings.database_url`. The user wants production runs and
daily-kWh readings to land in the **RDS PostgreSQL** production database so they
are visible in pgAdmin alongside the company ERP — while **login/users stays on
SQLite**, because the RDS `users` table belongs to the ERP and is schema-incompatible
with the app's `User` model.

### Current state (verified 2026-06-20)

- `settings.database_url` resolves to the **RDS Postgres URL** (root `.env`
  `DATABASE_URL=postgresql+psycopg2://...`). All app data, however, lives in the
  local `factoryops.db` SQLite file (users:3, machines:214, mt_asset_list:864,
  floor_utility_readings:2859, production_runs:1, mt_machine_daily_kwh:1, ...).
  The app is mid-transition and the current config is **unsafe** (see §6).
- RDS `public` schema has **541 tables** (the ERP). Of the app's tables:
  - `users` — **EXISTS, 19 rows, incompatible schema**
    (`id:uuid, email, password_hash, display_name, is_active, name, is_developer, created_by`).
    No `username` / `role` / `plant_id`. The app's login cannot use it.
  - `mt_asset_list` — **EXISTS, 864 rows, schema matches** the `MtAsset` model.
  - `mt_machine_daily_kwh` — **EXISTS, 0 rows, schema matches** the `MachineDailyKwh` model.
  - `plants`, `floors`, `machines`, `user_machine_assignments`,
    `production_runs`, `breakdown_flags`, `floor_utility_readings` — **all MISSING** in RDS.
- `psycopg2` 2.9.10 is installed; RDS is reachable read-only from this machine.

### Router → model boundaries (verified)

| Router | Models touched | Target DB |
|---|---|---|
| `auth` | `User` | SQLite |
| `machines` | `Machine`, `UserMachineAssignment`, `User` | SQLite |
| `breakdowns` | `Machine`, `BreakdownFlag`, `User` | SQLite |
| `floors` | `Floor`, `Machine`, `FloorUtilityReading`, `User` | SQLite |
| `energy` | `MtAsset`, `ProductionRun`, `User` (via `get_current_user`) | **RDS** (+ SQLite for the user lookup) |
| `mt_machines` | `MtAsset`, `MachineDailyKwh`, `User` (via `get_current_user`) | **RDS** (+ SQLite for the user lookup) |

No endpoint ever queries a SQLite-only model and an RDS model **in the same
query/session**. `operator_id` is stored as a plain string and never joined to
`users`. This is what makes a clean two-engine split possible.

## 2. Goals / Non-goals

**Goals (Phase 1 — this pass)**
- Runs (`production_runs`) and daily-kWh readings (`mt_machine_daily_kwh`) write
  to **RDS**, visible in pgAdmin.
- The machine list (`mt_asset_list`) is **read from RDS** (source of truth);
  the SQLite copy is no longer used by the app.
- Login and all other app data remain on **SQLite**.
- The app **does not pollute** the 541-table ERP: it creates **only**
  `production_runs` in RDS (the two other maintenance tables already exist).
- Remove the live hazard in §6.

**Non-goals (deferred to Phase 2 / out of scope)**
- Migrating `machines`, `floors`, `breakdowns`, `floor_utility_readings`, or
  their ~4,000 seed/utility rows to RDS. (User will "add tables in RDS later".)
- Moving `users`/auth to RDS.
- Dual-write or offline reconciliation. Writes are **RDS-only**.
- Any change to the mobile-app API contract (request/response shapes unchanged).

## 3. Chosen approach

**Two engines, routed per-endpoint.** One SQLite engine for auth + app-internal
data, one RDS Postgres engine for the maintenance tables. Each router depends on
whichever session it needs.

Alternatives considered and rejected:
- *One engine, per-table bind routing* — implicit/"magic", still needs the
  cross-DB FK stripped, harder failure semantics.
- *Everything on RDS now (incl. users)* — breaks login against the ERP `users`
  table and dumps app tables + seed data into the production schema.

## 4. Architecture

### 4.1 Configuration (`config.py` + `.env`)

Two named connection URLs:

- `local_database_url` — SQLite, default `sqlite:///./factoryops.db`. Auth +
  app-internal tables.
- `rds_database_url` — Postgres RDS. Maintenance tables. **Sourced from the
  existing `.env` `DATABASE_URL`** (reused as-is). Decision: keep the env var
  named `DATABASE_URL` so `scripts/sync_assets_to_sqlite.py` and the `DB_*` vars
  keep working untouched; the `Settings` field is named `rds_database_url` with
  a validation alias of `DATABASE_URL`. `local_database_url` needs no env entry
  (it uses the SQLite default unless explicitly overridden).

`rds_database_url` is **required at startup** — the `energy` and `mt_machines`
routers cannot function without it. Startup fails fast with a clear message if
it is missing.

### 4.2 Engines & sessions (`database.py`)

- `LocalBase` (declarative base) + `local_engine` (SQLite,
  `connect_args={"check_same_thread": False}`) + `SessionLocal` + `get_db()`.
- `RdsBase` (declarative base) + `rds_engine` (Postgres) + `SessionRds` +
  `get_rds()`.

`get_db` and `get_rds` are FastAPI dependencies that yield a session and close
it in `finally`, mirroring the existing `get_db`.

### 4.3 Models (`models.py`)

Split across the two bases:

- **`LocalBase`:** `User`, `Plant`, `Floor`, `Machine`,
  `UserMachineAssignment`, `BreakdownFlag`, `FloorUtilityReading`.
- **`RdsBase`:** `MtAsset`, `MachineDailyKwh`, `ProductionRun`.

`ProductionRun.operator_id`: **drop** the `ForeignKey("users.id")` (a FK cannot
span two databases). Keep it as `String(64)` indexed; it still stores the
operator's id, just unconstrained. `machine_id` is already a plain string. No
other RDS model has a FK into a SQLite-only table.

### 4.4 App startup (`main.py`)

- `LocalBase.metadata.create_all(bind=local_engine)` — app tables on SQLite (idempotent).
- `RdsBase.metadata.create_all(bind=rds_engine)` — creates **only** the 3
  maintenance tables on RDS. `mt_asset_list` + `mt_machine_daily_kwh` already
  exist (skipped); `production_runs` is created. **No ERP table is touched.**

### 4.5 Routers

- `energy.py`: `Depends(get_db)` → `Depends(get_rds)` for the `MtAsset` /
  `ProductionRun` work.
- `mt_machines.py`: `Depends(get_db)` → `Depends(get_rds)` for the `MtAsset` /
  `MachineDailyKwh` work.
- `get_current_user` (in `auth.py`) **keeps `get_db`** (SQLite). An operator
  authenticates against SQLite; their `user.id` (a string) is written into the
  RDS run/reading rows. The two sessions never share ORM objects.
- `auth`, `machines`, `breakdowns`, `floors` routers: **unchanged** (SQLite).

## 5. Data flow (after change)

1. `POST /auth/login` → SQLite `users` → JWT.
2. `GET /mt-machines` → RDS `mt_asset_list` (864 rows).
3. `POST /energy/runs/start` / `/stop` → RDS `production_runs`
   (operator id from the SQLite-authenticated user).
4. `POST /mt-machines/{id}/daily-kwh` → RDS `mt_machine_daily_kwh` (upsert on
   `(machine_id, reading_date)`).
5. `GET /machines/assigned`, `/breakdowns`, `/floors/*` → SQLite (unchanged).

## 6. Hazard being fixed

The present `.env` points the **single** engine at RDS, so launching the app
runs `Base.metadata.create_all()` against RDS and would: (a) create app tables
(`plants`, `floors`, `machines`, `breakdown_flags`, `floor_utility_readings`,
`production_runs`, `user_machine_assignments`) inside the ERP `public` schema,
and (b) map the app's `User` model onto the ERP `users` table, breaking login.
The two-engine design eliminates both.

## 7. Error handling

- RDS unreachable → `energy` / `mt_machines` endpoints return a 5xx with a clear
  error; **no silent data loss**. Login and SQLite-backed endpoints keep working.
- `rds_database_url` missing at startup → fail fast with an explicit message.

## 8. Testing / verification

Manual end-to-end (the definitive acceptance check):

1. Start the app; `POST /auth/login` with a seeded SQLite user → 200 + token.
2. `GET /mt-machines` → 864 assets returned (from RDS).
3. `POST /energy/runs/start` then `/stop` → 200; row appears in **RDS**
   `production_runs` (confirm in pgAdmin).
4. `POST /mt-machines/{id}/daily-kwh` → 200; row appears in **RDS**
   `mt_machine_daily_kwh` (confirm in pgAdmin).
5. Confirm **no** new app tables (`plants`/`floors`/`machines`/…) were created
   in RDS beyond `production_runs`.
6. `GET /machines/assigned`, `/breakdowns`, `/floors/` still return SQLite data.

Automated (if added): unit test that `LocalBase` and `RdsBase` contain the
expected, disjoint table sets, and that `ProductionRun` has no FK to `users`.

## 9. Risks & mitigations

- **Cross-DB FK removal** loses referential integrity on `operator_id`.
  Acceptable — the value is informational and validated at write time via the
  authenticated user. Documented.
- **RDS as a runtime dependency** for runs/readings. Mitigated by fail-fast +
  clear errors; auth path is unaffected.
- **Two engines / connection pools.** Minor resource cost; standard SQLAlchemy.

## 10. Phase 2 (later, not now)

When the user is ready: migrate `machines`, `floors`, `breakdowns`,
`floor_utility_readings` (+ seed/utility rows) to RDS by moving those models to
`RdsBase` and copying data, and eventually reconcile `users`/auth with the ERP.
The two-engine architecture makes each move a localized change.
