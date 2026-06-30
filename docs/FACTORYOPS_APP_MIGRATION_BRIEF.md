# FactoryOps app — migrate the production/energy flow to `mt_asset_list`

> **Hand this whole file to the Claude Code session running in the FactoryOps Android project** (`D:\Maintenance module\FactoryOps`, package `com.candorfoods.factoryops`). It is self-contained. Run it through brainstorm → plan → TDD as usual; the contract below is authoritative (verified against the live FastAPI backend on 2026-06-20).

## Why

"Stop production" fails with **HTTP 404**. The app posts the day's kWh to
`POST machines/{id}/daily-kwh` using a machine id like `MCH-0182` (from
`GET machines/assigned`). That route does not exist on the backend, and that
id-space is the **old `machines` catalog (214 rows)**. The backend's energy +
reading endpoints are keyed to the **`mt_asset_list` asset register (864 rows,
ids like `W202-0005` / `A185-0001`)**. The two catalogs do **not** overlap
(no `MCH-*` ids exist in `mt_asset_list`).

**Decision (approved by the product owner):** move the **production-run / energy
flow** onto the asset register. Operators select from the asset register
(`assetId`), and runs + daily-kWh are keyed by `assetId`. The app already has
full `mt-machines` plumbing (the "Machine Master" screen — `MtMachineApi`,
`MtMachineDto`, `MtMachineRepositoryImpl`, `MachineMasterViewModel`); **reuse it**
rather than building new. The Home/production screen will now show assets from
`/mt-machines` instead of the 214 `machines/assigned` machines.

## Authoritative backend contract (current)

All endpoints require `Authorization: Bearer <jwt>` from `POST auth/login`.
Base path is the Retrofit `baseUrl`. JSON is snake_case.

### List assets
`GET /mt-machines?building=&category=&sub_location=` (all query params optional)
```json
[
  { "asset_id": "W202-0005", "asset_name": "Shrink Wrap - L sealer",
    "building": "W-202", "sub_location": "2nd Floor", "category": "Production Equipment",
    "model_no": null, "serial_no": null, "power_load": "3 kW", "rated_kw": 3.0,
    "quantity": 1, "condition": null, "assigned_to": null }
]
```
- Filter param is **`category`** (NOT `sub_category`). Response field is **`category`**.
- `rated_kw` is the backend-parsed kW from `power_load` (may be null).

### Save daily kWh  ← fixes the 404
`POST /mt-machines/{asset_id}/daily-kwh`
```json
{ "machine_id": "W202-0005", "reading_date": "2026-06-20", "daily_kwh": 12.5, "source": "CALCULATED" }
```
- `machine_id` **must equal** the `{asset_id}` in the path → else **400**.
- `asset_id` **must exist** in `mt_asset_list` → else **404**.
- `reading_date` = ISO `YYYY-MM-DD` (device-local day).
- `source` ∈ `CALCULATED | MEASURED | MANUAL` (default `CALCULATED`).
- `building`/`floor` are **ignored if sent** — the server fills them from the
  asset register. (You may send them or omit them.)
- Idempotent upsert on `(machine_id, reading_date)` — last write wins.
- Response:
```json
{ "machine_id": "W202-0005", "reading_date": "2026-06-20", "building": "W-202",
  "floor": "2nd Floor", "daily_kwh": 12.5, "source": "CALCULATED", "updated_at": 1750000000000 }
```

### Start run
`POST /energy/runs/start`
```json
{ "machine_id": "W202-0005", "client_run_id": "<uuid-from-device>",
  "started_at": 1750000000000, "scheduled_end_at": 1750003600000 }
```
- `machine_id` must be an **`asset_id`**. `client_run_id` is **required**
  (idempotency key; resending the same one returns the existing run).
- Response: `{ "run_id": "...", "client_run_id": "...", "started_at": 1750000000000, "scheduled_end_at": 1750003600000 }`
  — **no `operator_id` field.**

### Stop run
`POST /energy/runs/{run_id}/stop`
```json
{ "ended_at": 1750003600000 }
```
- Response: `{ "run_id": "...", "ended_at": 1750003600000, "computed_kwh": 0.119 }`
  (`computed_kwh = rated_kw × hours × 0.99`, server-computed from the asset's `power_load`.)

### History
`GET /energy/machines/{asset_id}/history?from=<ms>&to=<ms>`
- Returns a **list of daily summaries**, NOT `{ runs: [...] }`:
```json
[
  { "date": "2026-06-20", "total_run_hours": 1.0, "total_kwh": 0.12, "estimated_cost": 1.02,
    "runs": [ { "id": "run-...", "started_at": 1750000000000, "ended_at": 1750003600000,
                "duration_hours": 1.0, "kwh": 0.12 } ] }
]
```

## Exact app change points (file : line)

1. **Daily-kWh path + identifier** — `data/remote/api/MachineDailyKwhApi.kt:15-20`
   change path `machines/{machine_id}/daily-kwh` → `mt-machines/{machine_id}/daily-kwh`.
   In `data/.../MachineDailyKwhRepositoryImpl.kt:20-47`, the id passed
   (`machineId`) must be the selected **`assetId`**, and `MachineDailyKwhUpsertDto.machineId`
   must equal it. `building`/`floor` can be `MtMachine.building` / `MtMachine.subLocation`
   (or omitted — server overwrites). The GET-list variant
   (`machines/{id}/daily-kwh`) has **no backend equivalent** — drop it or repoint
   reads to the history endpoint.

2. **Production selection moves to the asset register** —
   `presentation/.../HomeViewModel.kt` + `HomeScreen` and
   `data/.../EnergyRepositoryImpl.kt:71`. The run's `machineId` must come from
   `MtMachine.assetId` (via `MtMachineRepository`/`GetMachineMasterUseCase`), not
   `Machine.id` from `machines/assigned`. Decide whether Home now *is* the asset
   list or links into the existing `MachineMasterScreen` for selection.

3. **Start-run DTOs** — `data/remote/dto/EnergyDtos.kt`:
   - `RunStartRequestDto`: **add `@SerialName("client_run_id") val clientRunId: String`**
     (generate a UUID per run on the device; reuse it on retries for idempotency).
   - `RunStartResponseDto`: **remove `operator_id`**, **add `client_run_id`**.

4. **Asset DTO/query field name** — `data/remote/dto/MtMachineDto.kt` +
   `data/remote/api/MtMachineApi.kt`: backend uses **`category`**, app currently
   uses `@SerialName("sub_category")` / `@Query("sub_category")` → category comes
   back blank and the filter no-ops. Rename to `category`. Also add the fields the
   backend returns and the flow needs: `rated_kw` (Double?), `condition` (String?),
   `assigned_to` (String?). (Note: backend response has no `quantity`-only payload
   issues; keep existing fields that still match.)

5. **History DTO shape** — `data/remote/dto/EnergyDtos.kt`: replace
   `MachineHistoryDto { runs: List<ProductionRunDto> }` with a
   `List<DailyHistoryDto>` where `DailyHistoryDto = { date, total_run_hours,
   total_kwh, estimated_cost, runs: List<DailyRunDto> }` and `DailyRunDto =
   { id, started_at, ended_at, duration_hours, kwh }`. Update
   `EnergyApi.getMachineHistory` return type and any history screen mapping.

6. **SyncWorker** — `sync/SyncWorker.kt:40-51` (`retryFailedDailyKwhUpserts`):
   ensure the retried upsert uses the new path + `assetId`.

## Acceptance criteria

- Selecting an asset, running, and stopping a production cycle results in
  `POST /mt-machines/{asset_id}/daily-kwh` returning **200**, with the reading
  visible in the backend RDS table `mt_machine_daily_kwh` (and runs in
  `production_runs`).
- `POST /energy/runs/start` returns 200 (no 422), `…/stop` returns 200 with a
  non-null `computed_kwh`.
- The Home/production list shows assets from `/mt-machines` (filterable by
  building / category / sub_location).
- No call to `machines/{id}/daily-kwh` remains.

## Testing notes

- Point the app at the running backend: in `local.properties` set
  `USE_MOCK_API=false`, `USE_MOCK_AUTH=false`, and `BASE_URL` to the backend
  (emulator: `http://10.0.2.2:8000/`; real device: the host LAN IP or the App
  Runner URL). The backend must be the updated one (it already serves these
  endpoints — no backend change is needed for this migration).
- Add/adjust unit tests for the DTO (de)serialization (esp. `client_run_id`,
  `category`, the history list shape) and for the repository building the
  daily-kWh request with `assetId`.

## Out of scope / cautions

- **No backend changes** are required — the contract above is what the live
  backend already exposes.
- Don't try to map old `MCH-*` ids to `asset_id`s — there is no correspondence.
- The old `machines/assigned` + `MachineApi` path can stay for now (e.g. if any
  other screen uses it), but the **production/energy flow must not use it**.
- Unrelated: backend logs a trapped `bcrypt __about__` warning — harmless, ignore.
```
