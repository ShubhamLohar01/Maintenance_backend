# Supervisor Reports section — design

## Purpose

Turn the Supervisor dashboard's "Reports" tile (currently a `ComingSoon`
placeholder) into a real section with two options: **Machines Reading** and
**Warehouse/Floor Readings** — read-only historical listings sourced from
`mt_machine_daily_kwh` and `mt_floor_utility_readings` respectively.

## Scope decisions (from brainstorming)

- **Supervisor only.** Head keeps its separate `ComingSoon` Reports tile for
  now (not touched). Technician's Reports tile also untouched.
- **Plant scope: both, with a filter.** Matches how Supervisors already see
  both A-185 and W-202 elsewhere (e.g. Schedule Electric Assets). Default
  shows both; a plant filter narrows to one.
- **Date range: last 30 days by default, filterable further back.** Not an
  unbounded "since day one" list — keeps the screen fast and scannable;
  supervisors who need the full history can widen the date filter.
- **Machines Reading browsing: one combined table**, not a per-machine
  drill-down (unlike Spare Parts) — every machine's daily rows in one
  newest-first list, filtered by plant/date.
- **Machines Reading row detail: compact.** Date · machine · building · kWh
  per row; tap to expand operator, run start/end time, status, and source
  (RUN vs SCHEDULE) inline.
- **Backend access: any authenticated user**, matching this app's existing
  GET-endpoint convention (role gating lives in the UI/nav, not the API) —
  same pattern as `/asset-schedules`, `/spare-parts`.

## Backend

### `GET /reports/machines`

Query params: `plant` (`A-185`/`W-202`/omitted = both, any spelling),
`from`/`to` (ISO `YYYY-MM-DD`; default `from` = today − 30 days, `to` = today,
same "yesterday-safe" IST-aware date handling already used elsewhere — actual
dates are just inclusive bounds here, no special default-day logic needed
since both ends are explicit query params).

Reads `mt_machine_daily_kwh` filtered by `building IN (scoped plants)` and
`reading_date BETWEEN from AND to`, newest first (`reading_date DESC, id DESC`).
Joins `mt_asset_list` for `asset_name` fallback only where the row's own
`asset_name` snapshot is null (legacy rows predating that column).

Response: `{ rows: [{ reading_date, machine_id, asset_name, building, floor,
operator_name, started_at, ended_at, status, source, daily_kwh }] }`.
`reading_date` is an ISO `YYYY-MM-DD` string (matches every other date field in
this API); `started_at`/`ended_at` are epoch-ms, null-safe (null while a RUN
row is still open) — matching `MachineDailyKwh`'s columns directly; no
aggregation, no dedup, one row per stored record.

### `GET /reports/floor-readings`

Same `plant`/`from`/`to` params. Reads `mt_floor_utility_readings` filtered the
same way, newest first (`reading_date DESC, id DESC`).

Response: `{ rows: [{ reading_date, building, floor, meter_reading,
daily_kwh }] }` — `meter_reading` (actual, technician-entered) and `daily_kwh`
(system-computed) side by side so a supervisor can spot discrepancies.

### Validation

`from`/`to` — 400 on unparseable date, same style as existing date-param
endpoints (`/floor-readings/system`, `/utilities/*`). `from > to` — 400.

## Android app

Mirrors the Spare Parts / Utilities layering:

- `data/remote/api/ReportsApi.kt` — one interface, two `@GET` methods.
- `data/remote/dto/ReportsDtos.kt` — response DTOs + domain mappers.
- `domain/model/reports/` — `MachineReadingRow`, `FloorReadingRow` (report
  variant — distinct from the existing Daily-Reading `FloorReadingRow`,
  namespaced under `reports` to avoid a name clash).
- `domain/repository/ReportsRepository.kt` +
  `data/repository/ReportsRepositoryImpl.kt`.
- `presentation/reports/`:
  - `ReportsHubScreen.kt` — chooser (same shape as `DailyReadingHubScreen`):
    two cards, "Machines Reading" / "Warehouse/Floor Readings".
  - `MachinesReadingScreen.kt` + ViewModel — plant filter chips (Both/A-185/
    W-202), date-range picker (defaults last 30 days), compact list,
    tap-to-expand row detail.
  - `FloorReadingsReportScreen.kt` + ViewModel — same filter bar, flat list
    (meter vs system reading per row).
- `navigation/Screen.kt` + `NavGraph.kt` — three new routes (hub + two report
  screens).
- `presentation/dashboard/DashboardTile.kt` — Supervisor's existing "Reports"
  tile switches from `DashboardAction.ComingSoon` to
  `DashboardAction.Open(Screen.ReportsHub.route)`. HEAD's tile list is
  otherwise untouched (still `ComingSoon` there, per scope decision).

## Testing

- Backend: pytest, TDD — plant filtering, date-range filtering/defaults, 400s
  on bad dates, empty-range behavior, full suite re-run for regressions.
- Android: ViewModel unit tests (filter changes re-triggering load, list
  population, error path) mirroring `SparePartsMachineListViewModelTest`;
  Gradle unit test run to confirm green.
