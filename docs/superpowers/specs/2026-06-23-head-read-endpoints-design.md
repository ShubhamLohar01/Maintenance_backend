# Head-facing read endpoints — design (2026-06-23)

Three additive, read-only GET endpoints for the Head interface. Bearer auth, JSON,
mirroring existing router/DTO conventions. (Repo is not under git, so no commit.)

## Shared helpers (`app/utils.py`)
- `norm_plant(s)` — compact comparable plant code: `"A-185"/"a185"/" A185 " -> "A185"`.
- `building_for(plant)` — resolve any spelling to the canonical DB building form
  (`"A-185"` / `"W-202"`) or `None`. `ALL_BUILDINGS = ["A-185","W-202"]`.
- `scoped_buildings(user, requested)` — buildings this request may see (DB form):
  HEAD → all buildings (optionally narrowed by `requested`); others → just their own
  (`building_for(user.plant_id)`), `requested` ignored.
- `iso_z(dt)` — naive-UTC datetime → ISO 8601 `...Z`, or `None` for `None` (JSON null).

## #1 — `GET /machines/live`
Source: `mt_asset_list` (RDS) as the machine universe (same DB as `production_runs`,
whose `machine_id = asset_id`). Per asset, find the **open** run (`ended_at IS NULL`,
latest `started_at`):
- open run → `RUNNING`; if that run's `flag_status` is set → `FLAGGED`; operator from
  `mt_users` where `id = run.operator_id` (operator_id is `str(MtUser.id)`);
  `run_started_at = started_at`.
- no open run → `IDLE`, operator + start = `null`.

Scoped to caller's plant(s). Element: `machine_id`(asset_id), `name`(asset_name),
`building`(asset.building), `plant_id`(normalized), `status`, `current_operator_id`,
`current_operator_name` (null when idle), `run_started_at` (iso_z, null when idle).

## #2 — `GET /reports/power?plant_id=&from=&to=`
Source: `mt_machine_daily_kwh` (RDS), `building` = plant, `reading_date` in `[from,to]`.
`total_kwh = Σ daily_kwh`; `by_day` grouped by `reading_date`; `by_machine` grouped by
`machine_id` with `name` joined from `mt_asset_list`. `?plant_id` accepts `A185` or
`A-185`, comma-separated. **One plant → the object; multiple → JSON array of objects.**
HEAD may query any plant; non-HEAD auto-scoped to own. `from`/`to` are ISO `YYYY-MM-DD`
(400 on bad). Response keys: `plant_id`, `from`, `to`, `total_kwh`, `by_day[]{date,kwh}`,
`by_machine[]{machine_id,name,kwh}`.

## #3 — `GET /head/escalations`
Read-only (no push/scheduler — deferred). Items: `breakdown_flags` with
`status IN (OPEN, ACKNOWLEDGED)`. `days_overdue = (now - raised_at).days`.
Tiers (tunable constants in module): ≥1d → tier 1 `TECHNICIAN`; ≥2d → tier 2
`SUPERVISOR`; ≥3d → tier 3 `HEAD`. `<1d` excluded. Default returns **tier-3 (HEAD)**
items; `?min_tier=1` widens. Plant-scoped (HEAD → both). Item: `type`("BREAKDOWN"),
`flag_id`, `machine_id`, `machine_name`(from mt_asset_list), `plant_id`, `severity`,
`status`, `raised_at`(iso_z), `days_overdue`, `tier`, `tier_role`.

> NOTE: `SUPERVISOR` has no backing users in `mt_users` (roles are OPERATOR/TECHNICIAN/
> HEAD). `tier_role` is descriptive metadata only; real role→user resolution is for the
> deferred push build.

## Testing
Extend `tests/conftest.py` to create the RDS-form tables on SQLite and provide a richer
auth stub (`norm_role`/`plant_id`/`id`/`name`) plus a `login_as(**kwargs)` factory.
Cover: #1 status derivation + plant scope; #2 date-range aggregation + multi-plant +
non-HEAD scope; #3 tier thresholds + default filter + RESOLVED exclusion + 401.
