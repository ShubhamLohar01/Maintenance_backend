# FactoryOps Backend — API & DB Contract (for the Android/Kotlin team)

Generated from the live backend source on 2026-06-25. This is the authoritative
list of every endpoint, the exact request/response field names, and which DB table +
columns each one fills. Use the snake_case keys verbatim (the app already serializes
snake_case).

---

## 0. THE #1 THING TO GET RIGHT — machine identity

Everything energy/breakdown/kWh-related keys on **`mt_asset_list.asset_id`**
(e.g. `"A185-0001"`, `"W202-0042"`), NOT the old mock ids like `"mach-002"`.

- When you call `/energy/runs/start`, `/breakdowns/flag`,
  the `machine_id` / `asset_id` you send **must be a real `asset_id`** from
  `GET /mt-machines`. If it isn't in `mt_asset_list`, the backend returns **404**.
- The legacy `GET /machines/assigned` returns the old SQLite dev `machines` table
  (ids like `mach-001`). Treat the **real asset register as `GET /mt-machines`**.

---

## 1. Connection & Auth

**Base URL:** whatever `BASE_URL` you point at (tunnel / server). Health check: `GET /health` → `{"status":"ok"}` (no auth).

**Login:** `POST /auth/login`
```jsonc
// request
{ "username": "ravi", "password": "pass123" }   // username is lowercased server-side
// response 200
{ "token": "<JWT>", "user_id": "7", "name": "Ravi K",
  "role": "HEAD",            // OPERATOR | TECHNICIAN | SUPERVISOR | HEAD | QC  (normalized from mt_users.role; treat as a plain string — new roles may appear)
  "plant_id": "A-185",       // from mt_users.location
  "expires_at": 1750000000000 }  // epoch ms
```
- **All users currently share password `pass123`** (mt_users has no password column yet).
- **Every other endpoint requires** header `Authorization: Bearer <token>`.
- Missing/invalid token → **401**. (Dev shortcut: token `dev-bypass-token` logs in as the first mt_users row.)
- JWT carries `sub`=user_id, `role`, `plant_id`. Token TTL = 8h.

**Two databases** (you don't touch these directly, but for context):
| Engine | Used by | Tables |
|---|---|---|
| RDS Postgres (`DATABASE_URL`, `warehouse_db`) | auth + everything maintenance | `mt_users`, `mt_asset_list`, `mt_machine_daily_kwh` (runs + energy), `mt_breakdown_records` (live breakdowns), `mt_doc_breakdown` (F.06 form), `doc_preventive_maintenance`, `mt_machine_transfer` |
| Local SQLite (`factoryops.db`) | legacy/dev only | `machines`, `floors`, `users`, `user_machine_assignments`, `floor_utility_readings`, `plants` |

**Plant codes:** DB stores `"A-185"` / `"W-202"`; the API accepts either spelling
(`A185`/`A-185`) and Head views return the compact form (`A185`). A **HEAD sees both
plants**; others are scoped to their own `plant_id`.

---

## 2. Field/type conventions

| Convention | Where | Kotlin type |
|---|---|---|
| **epoch milliseconds** (int) | most timestamps in requests & operator-facing responses: `started_at`, `ended_at`, `raised_at`, `reported_at`, `acknowledged_at`, `decided_at`, `updated_at`, `expires_at` | `Long` |
| **ISO date `YYYY-MM-DD`** (string) | `reading_date`, `checklist_date`, `record_date`, transfer `date`, reports `from`/`to`, floor `from_date`/`to_date` | `String` |
| **ISO-8601 `...Z`** (string) | **Head** read views + checklist/transfer read-backs: `created_at`, `raised_at`, `resolved_at`, `qc_decided_at`, `run_started_at` | `String` |

⚠️ Note the split: operator endpoints (`/breakdowns/open`, `/energy/*`) use **epoch ms**;
the `/head/*` endpoints use **ISO-Z strings**. Per-field tables below are explicit.

---

## 3. Endpoints

### AUTH
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `{username, password}` | `{token, user_id, name, role, plant_id, expires_at}` |

### REAL ASSET REGISTER — `mt_asset_list` (RDS, read-only via API; seeded from Excel)
**`GET /mt-machines`** — query (all optional): `building` (`W-202`/`A-185`), `category`, `sub_location`
→ `List<MtMachineDto>`:
```
asset_id, asset_name, building, sub_location, category, model_no, serial_no,
power_load, rated_kw (parsed from power_load, may be null), quantity, condition, assigned_to
```

> **RETIRED 2026-06-25** — `POST /mt-machines/{asset_id}/daily-kwh` (the old
> `MachineDailyKwhUpsertRequest` upsert) is **deleted**. `mt_machine_daily_kwh` is
> now written **only** by the run Start/Stop flow below. Remove any client code
> that called `daily-kwh`.

### ENERGY / RUNS — `mt_machine_daily_kwh` (RDS)
> **CHANGED 2026-06-25** — production runs no longer live in a separate
> `mt_machine_runs` table; **each run is one row in `mt_machine_daily_kwh`**
> (`status` RUNNING→COMPLETE). The Start/Stop request & response shapes are
> UNCHANGED, so existing app calls keep working. Only two things changed for the
> client: (1) `run_id` is now a **numeric string** (e.g. `"4217"`, was
> `"run-<uuid>"`) — keep treating it as an opaque `String`; (2) `scheduled_end_at`
> is echoed back but no longer stored.

**`POST /energy/runs/start`** — body `RunStartRequest`, **inserts a RUNNING row in `mt_machine_daily_kwh`**:
| body field | req | → column |
|---|---|---|
| `machine_id` | yes | `machine_id` (= asset_id; 404 if not an asset) |
| `client_run_id` | yes | `client_run_id` (idempotency key — resend returns the same row) |
| `started_at` | yes (ms) | `started_at` (its calendar day → `reading_date`) |
| `scheduled_end_at` | yes (ms) | (echoed in the response; not stored) |

server fills `id`, `status='RUNNING'`, `operator_id = JWT user id`,
`operator_name = JWT user name`, `building`/`floor` from the asset register.
→ `RunStartResponse {run_id, client_run_id, started_at, scheduled_end_at}`

**`POST /energy/runs/{run_id}/stop`** — body `{ended_at(ms)}` → `{run_id, ended_at, computed_kwh}`
Stamps `ended_at`, sets `daily_kwh = rated_kw(power_load) × hours × power_factor`,
flips `status='COMPLETE'`. Idempotent — re-stopping a COMPLETE row returns the
stored kwh without recomputing. `computed_kwh` in the response **is** the row's `daily_kwh`.

**`GET /energy/runs/active`** → `List<ActiveRunDto> {asset_id, run_id, operator_id, operator_name, started_at(ms), building}` (all in-progress runs).

**`GET /energy/machines/{machine_id}/history`** — query `from`(ms), `to`(ms)
→ `List<DailyHistoryDto> {date, total_run_hours, total_kwh, estimated_cost, runs:[{id, started_at(ms), ended_at(ms?), duration_hours, kwh}]}`

### OPERATOR BREAKDOWNS — `mt_breakdown_records` (RDS, live-workflow table)
Lifecycle: `OPEN → ACKNOWLEDGED → PENDING_QC → CLOSED | REOPENED`. Machine is usable again **only at `CLOSED`**.
⚠️ **Status vocabulary changed 2026-06-26:** terminal state `QC_APPROVED`→**`CLOSED`**, and `qc_status` `DISAPPROVED`→**`REJECTED`**. Update any `when`/`switch` on those values. People are stored as **names** (server resolves the sent `operator_id`/`user_id` against `mt_users`, falling back to `user_name` when provided).

**`POST /breakdowns/flag`** — ⚠️ **multipart/form-data** (was JSON), **inserts a row**:
| form field | req | → column |
|---|---|---|
| `machine_id` | yes | `machine_id` (404 if not an asset) |
| `severity` | no (`MAJOR`) | `severity` (`CRITICAL`/`MAJOR`/`MINOR`) |
| `description` | no | `description` |
| `raised_at` | yes (ms) | `start_time` |
| `operator_id` | no | resolved to name → `operator_raise_person` (else JWT user's name) |
| `before_photo` (file) | no | uploaded to **S3** → `before_photo_url` (image/jpeg or image/png, ≤ 10 MB) |

server fills `machine_name` (from asset), `status='OPEN'`. → `BreakdownFlagResponse {id, sync_status}`

**Workflow transitions** (all → `QcUpdateResponse {id, ticket_status, machine_status, qc_status, sync_status}`):
| Method | Path | Body | Effect |
|---|---|---|---|
| POST | `/breakdowns/{id}/qc/acknowledge` | `QcAckRequest {user_id, user_name, acknowledged_at(ms), override?}` (JSON) | → `ACKNOWLEDGED` (sets `technician`, `ackn_at`) |
| POST | `/breakdowns/{id}/work-done` | ⚠️ **multipart/form-data**: `user_id, user_name, work_done, done_at(ms)` + optional `after_photo` (file → **S3**) | → `PENDING_QC`, `qc_status=PENDING` (sets `work_done_des`, `photo_url`=S3 URL) |
| POST | `/breakdowns/{id}/qc/approve` | `QcDecideRequest` | → `CLOSED`, `qc_status=APPROVED` (machine `AVAILABLE`; sets `qc_checked_by`, `end_time`) |
| POST | `/breakdowns/{id}/qc/disapprove` | `QcDecideRequest` | → `REOPENED`, `qc_status=REJECTED` (still `UNDER_BREAKDOWN`; sets `qc_reject_reason`) |

`QcDecideRequest {user_id, user_name, decided_at(ms), checklist_json, after_photo_path?, notes?, reason?}` (reject reason ← `reason`/`notes`). `machine_status` = `AVAILABLE` only when `CLOSED`, else `UNDER_BREAKDOWN`.

**`GET /breakdowns/open`** — query `plant_id` (`W202`/`A185`/`both`, default `both`)
→ `List<OpenBreakdownDto> {id, asset_id, asset_name, reported_by, reporter_name, severity, description, status, reported_at(ms), building}` (everything not yet `CLOSED`). Field names unchanged; `asset_id`←`machine_id`, `reporter_name`/`reported_by`←`operator_raise_person`, `reported_at`←`start_time`.

### PREVENTIVE MAINTENANCE — `doc_preventive_maintenance` (RDS, JSONB `rows`)
| Method | Path | Body / Query | Response |
|---|---|---|---|
| POST | `/preventive-maintenance/checklists` | `PmChecklistRequest` | `201 {id}` |
| PUT | `/preventive-maintenance/checklists/{id}` | `PmChecklistRequest` | `{id}` (draft re-save / finalize) |
| GET | `/preventive-maintenance/checklists` | — | `List<PmChecklistListItemDto>` |
| GET | `/preventive-maintenance/checklists/{id}` | — | `PmChecklistDetailDto` (with `items[]`) |

`PmChecklistRequest {form_type(MONTHLY|QUARTERLY), doc_no, status(DRAFT|SUBMITTED), checklist_date, done_by, checked_by, verified_by, remarks, items:[{section, equipment, sr_no?, equipment_date, checkpoint, status(OK|NOT_OK|UNSET), remarks}]}`.
Rules: `items` non-empty (400); a `SUBMITTED` checklist may not contain `UNSET` items and needs a valid `checklist_date` (400). `created_by` = JWT user (client value ignored). The whole payload + `plant_id`(from JWT) is stored in `rows`.

### BREAKDOWN FORM CFPLA.C4.F.06 — `mt_doc_breakdown` (RDS)
**`POST /preventive-maintenance/breakdowns`** — body `BreakdownSheetIn`, **one row per entry**:
```jsonc
{ "doc_no": "CFPLA.C4.F.06", "verified_by": "Ravi",
  "entries": [ { "record_date":"2026-06-22","location":"...","machine_name":"...",
    "equipment_model_no":"...","problem_in_brief":"...","type_of_maintenance":"...",
    "part_of_machine":"...","temporary_reason":"...","duration_start":"10:30",
    "duration_end":"12:00","machine_operator_sign":"...","maintenance_person_sign":"...",
    "qc_clearance_sign":"..." } ] }
```
All entry fields optional (lenient, won't 422); empty `record_date` → NULL. `sr_no`=index+1, `created_by`=JWT, `source='F06_RECORD'` filled server-side. → `201 {ids:[...]}`. Empty `entries` → 400.

### MACHINE TRANSFERS — `mt_machine_transfer` (RDS + S3 photo)
**`POST /machine-transfers`** — **multipart/form-data** (not JSON): `from_warehouse`*, `to_warehouse`*, `machine_name`* (required, must differ), `asset_id?`, `date?`, `machine_code?`, `condition?`, `reason?`, `authorised_person?`, `remarks?`, `proof_photo?` (jpeg/png ≤10MB). → `201 {id, proof_photo_url}`. `created_by`=JWT.
⚠️ **Side effect (2026-07-03):** the transfer also **moves the asset's `building` in `mt_asset_list`** to `to_warehouse`. Send `asset_id` (the picked register row's id) for a precise move. If it's omitted, the backend falls back to a UNIQUE `asset_name` match **within `from_warehouse`** and skips the move when the name is ambiguous (0 or >1 rows) — the transfer still saves either way. So the app should attach `asset_id` whenever the user picked a machine from the register autocomplete, and refresh `GET /mt-machines` after a transfer to show the new building.
**`GET /machine-transfers`** → `List<MachineTransferListItemDto> {id, date, from_warehouse, to_warehouse, machine_name, condition, created_at(ISO-Z), proof_photo_url}`

### HEAD VIEWS (token-scoped; HEAD = both plants) — `/head/*`
| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/head/machines/live` | — | `List<LiveMachineDto>` |
| GET | `/head/breakdowns` | — | `List<HeadBreakdownDto>` |
| GET | `/head/qc` | — | `HeadQcActivityDto {awaiting[], decided[]}` |
| GET | `/head/checklists` | — | `List<PmChecklistListItemDto>` (SUBMITTED only) |
| GET | `/head/transfers` | — | `List<HeadTransferDto>` |
| GET | `/head/escalations` | `min_tier` (1-3, default 3) | `List<EscalationItemDto>` |
| GET | `/head/reports/power` | `from`, `to` (ISO date) | `HeadPowerReportDto` |

- `LiveMachineDto {machine_id, name, building, plant_id, status(RUNNING|PENDING_QC|IDLE), current_operator_id?, current_operator_name?, run_started_at?(ISO-Z)}` — `FLAGGED` retired 2026-06-25 (breakdowns drive `PENDING_QC`)
- `HeadBreakdownDto {id, machine_id, machine_name, plant_id, severity, status, description, raised_at(ISO-Z), acknowledged_by_name?, resolved_by_name?, qc_status?}`
- `EscalationItemDto {type, flag_id, machine_id, machine_name, plant_id, severity, status, raised_at(ISO-Z), days_overdue, tier(1-3), tier_role(TECHNICIAN|SUPERVISOR|HEAD), proof_photo_url?}`
- `HeadPowerReportDto {from, to, warehouses:[{plant_id, total_kwh, by_day:[{date,kwh}], by_machine:[{machine_id,name,kwh}]}]}`

### TECHNICIAN DAILY READING — `mt_floor_utility_readings` (RDS)
Per-floor "actual meter reading vs system-generated reading" for the technician
home screen. Scoped to the caller's **own building** (`building_for(plant_id)`); a
HEAD writes to their home building too (meter reading is a single-building task).
Floors = `DISTINCT mt_asset_list.sub_location` for that building.

**`GET /floor-readings/system`** — query `date?` (ISO `YYYY-MM-DD`, default today), `building?` (`A-185`/`W-202`)
→ `FloorReadingsResponse {building, reading_date, floors:[{floor, system_reading, meter_reading?}]}`
- OPERATOR/TECHNICIAN: omit `building` — resolved from their own plant (`mt_users.location`).
- HEAD/SUPERVISOR oversee both plants: the **GET** defaults to the first plant (A-185) if `building` is omitted so the screen loads; pass `building` to pick. The **POST requires** `building` for them (no silent write to the wrong plant). **Echo the `building` from the GET response into the POST body** — then it works for every role.
- `system_reading` = sum of that day's run kWh on the floor (from `mt_machine_daily_kwh`), `0` if idle.
- `meter_reading` = the actual reading already saved for that floor/date (else `null`) — so the form re-opens pre-filled.

**`POST /floor-readings`** — body `FloorReadingsSubmitRequest`, **batch upsert** (one call, all floors):
```jsonc
{ "reading_date": "2026-06-25",          // optional; default today
  "rows": [ {"floor":"Ground floor","meter_reading":100.5},
            {"floor":"1st floor","meter_reading":250.0} ] }
```
Per floor: server **recomputes** `system_reading` from the run table (client value ignored), upserts on `(building, floor, reading_date)`. → `{building, reading_date, saved}`.

### LEGACY (SQLite, dev) — likely NOT for production app
| Method | Path | Response |
|---|---|---|
| GET | `/machines/assigned` | `List<MachineDto>` (old dev `machines` table) |
| GET | `/floors/` | `List<FloorSummaryDto>` |
| GET | `/floors/{floor_id}/utility` | `List<FloorUtilityReadingDto>` |

---

## 4. DB tables → who fills each column

**`mt_breakdown_records`** (live breakdown workflow; one row per breakdown):
machine_id, machine_name, operator_raise_person, start_time, description, severity, before_photo_url, status (via `POST /breakdowns/flag`); technician, ackn_at (via `/qc/acknowledge`); work_done_des, photo_url (via `/work-done`); qc_checked_by, qc_status, qc_reject_reason, end_time (via `/qc/approve`|`/qc/disapprove`). created_at/updated_at server-set.

**`mt_doc_breakdown`** (CFPLA.C4.F.06 paper form; one row per sheet entry):
doc_no, sr_no, record_date, location, machine_name, equipment_model_no, problem_in_brief, type_of_maintenance, part_of_machine, temporary_reason, duration_start, duration_end, machine_operator_sign, maintenance_person_sign, qc_clearance_sign, verified_by, created_by (via `POST /preventive-maintenance/breakdowns`).

**`mt_machine_daily_kwh`** (one row per RUN; `mt_machine_runs` retired 2026-06-25):
id, machine_id, reading_date, building, floor, client_run_id, operator_id,
operator_name, started_at, status (RUNNING|COMPLETE), source — set on START;
ended_at, daily_kwh — filled on STOP. No UNIQUE(machine_id, reading_date) — a
machine may have several rows per day.
**`mt_floor_utility_readings`**: building, floor (= asset sub_location), reading_date, meter_reading (actual, technician), daily_kwh (system-generated total) — UNIQUE(building, floor, reading_date), upsert via `POST /floor-readings`.
**`doc_preventive_maintenance`**: month, checked_by, verified_by, created_by, rows(JSONB full payload).
**`mt_machine_transfer`**: transfer_date, from_warehouse, to_warehouse, machine_name, machine_code, condition, reason, authorised_person, remarks, proof_photo_url, created_by, created_at.
**`mt_asset_list`**, **`mt_users`**: read-only via API (managed in pgAdmin / seeded from Excel).

---

## 5. Errors
- `401` missing/invalid Bearer. `404` unknown asset_id/run/flag/id. `400` validation
  (e.g. empty entries, bad date, path/body mismatch, same from/to warehouse). `422`
  Pydantic body validation (`{"detail":[...]}`). All errors are JSON.
