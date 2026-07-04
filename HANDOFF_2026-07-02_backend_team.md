# Backend Handoff — 2026-07-02

Two change sets landed in this backend (`D:\Maintenance module\backend`). Both are
**required by the new Android APK** and must be deployed to
`maintenance-backend-pj31.onrender.com`. **The app and backend must ship together** —
the app now sends multipart for breakdown photos and calls new schedule endpoints; the
current production backend will reject those until this is deployed.

---

## 0. Do this, in order

1. **Run the DB migration** (section 3) on the RDS Postgres DB (`DATABASE_URL`). Safe/idempotent.
2. **Confirm S3 env vars** are set on Render (section 4).
3. **Deploy** the updated backend code.
4. **Verify** with the smoke tests in section 6.
5. Only then ship/relay the new APK to users.

Run the test suite before deploying: `python -m pytest -q` (expect the new suites green;
see section 7 for a pre-existing, unrelated failure).

---

## 1. Change set A — Breakdown photos + reliable persistence

**Why:** technician "Mark Resolved" (work-done) and QC decisions were not persisting to
`mt_breakdown_records`, and the "photo" was a device-local file path, never an S3 URL.
Root cause was app-side (best-effort calls silently swallowed), but the endpoints were
also JSON-only with no S3 upload. Fixed on both sides.

**Files changed**
- `app/api/breakdowns.py` — `/breakdowns/flag` and `/breakdowns/{id}/work-done` converted
  from JSON to **multipart/form-data**; optional image part uploaded to S3 via a shared
  `_upload_photo()` helper (mirrors the machine-transfer flow). Upload runs **before**
  `commit`, so a failed upload rolls back the row (no orphan record / no work_done without photo).
- `app/schemas.py` — removed the now-unused `BreakdownFlagRequest` / `BreakdownWorkDoneRequest`
  JSON bodies.
- `tests/test_breakdowns.py` — updated to post multipart; added photo/S3 assertions.
- `docs/API_CONTRACT_FOR_ANDROID.md` — updated to the new multipart contract.

**BREAKING API contract changes** (clients other than this Android app, if any, must update):

`POST /breakdowns/flag` — was JSON, now **multipart/form-data**:
| field | type | notes |
|---|---|---|
| `machine_id` | form (str, required) | = `mt_asset_list.asset_id` |
| `operator_id` | form (str, optional) | resolved to a name |
| `severity` | form (str) | default `MAJOR` |
| `description` | form (str) | |
| `raised_at` | form (int, required) | epoch ms |
| `before_photo` | file (optional) | image/jpeg or image/png, ≤10 MB → S3 → `before_photo_url` |

`POST /breakdowns/{id}/work-done` — was JSON, now **multipart/form-data**:
| field | type | notes |
|---|---|---|
| `user_id` | form (str) | |
| `user_name` | form (str) | |
| `work_done` | form (str) | → `work_done_des` |
| `done_at` | form (int, required) | epoch ms |
| `after_photo` | file (optional) | image → S3 → `photo_url` |

S3 object keys: `breakdowns/{record_id}/before.<ext>` and `breakdowns/{record_id}/after.<ext>`.
The QC approve/disapprove endpoints are unchanged (still JSON); the app now calls them
authoritatively (no behavior change server-side).

---

## 2. Change set B — Schedule Electric Assets (new feature)

**Why:** "Electric Asset" rows (lights, fans, etc.) aren't operator-runnable, so they logged
zero energy. A SUPERVISOR now gives each a recurring daily window; the backend records one
estimated-kWh row per elapsed day. HEAD is read-only.

**Files changed / added**
- `app/models.py` — 6 new columns on `MtAsset` / `mt_asset_list` (see migration).
- `app/schemas.py` — `AssetScheduleDto`, `AssetScheduleUpsertRequest`.
- `app/api/asset_schedules.py` — **new router** (registered in `app/main.py`).
- `tests/test_asset_schedules.py` — 13 tests.

**New endpoints** (prefix `/asset-schedules`):
- `GET /asset-schedules?plant_id=both` — every `Electric Asset` row + its schedule + derived
  `hours` / `est_daily_kwh`. Runs a lazy backfill first. **Any authenticated role.**
- `PUT /asset-schedules/{machine_id}` — body `{start_min, end_min, active}` (minute-of-day,
  IST; `0 <= start_min < end_min <= 1440`). **SUPERVISOR only (403 otherwise).**
- `DELETE /asset-schedules/{machine_id}` — clears schedule, keeps past rows. **SUPERVISOR only.**
- `POST /asset-schedules/generate` — force a backfill sweep. `{generated: n}`.

**Recording model (no cron):** on each `GET` (and the `generate` endpoint), for every active
schedule the backend inserts missing `mt_machine_daily_kwh` rows — one per day whose window
has **fully elapsed in IST** — with:
`daily_kwh = rated_kw(power_load) × window_hours × power_factor(0.99)`, `status='COMPLETE'`,
`source='SCHEDULE'`, `client_run_id='sched-{asset_id}-{YYYY-MM-DD}'` (idempotent — never
double-counts). Editing `power_load` only affects **future** rows; pausing stops future
generation but keeps history. No always-on scheduler needed (survives Render sleeping).

**Only `category == 'Electric Asset'` rows are schedulable** (others → 400). Reads/writes are
all-plant (per product decision). Asset-detail edits reuse the existing
`PUT /mt-machines/{asset_id}`.

---

## 3. DB migration — run on RDS Postgres BEFORE deploy

```sql
ALTER TABLE mt_asset_list
    ADD COLUMN IF NOT EXISTS schedule_start_min      INTEGER,        -- minute-of-day (IST), 600 = 10:00
    ADD COLUMN IF NOT EXISTS schedule_end_min        INTEGER,        -- must be > start
    ADD COLUMN IF NOT EXISTS schedule_active         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS schedule_last_generated DATE,           -- backfill high-water mark
    ADD COLUMN IF NOT EXISTS schedule_updated_by     VARCHAR(128),
    ADD COLUMN IF NOT EXISTS schedule_updated_at     TIMESTAMP;
```

`mt_machine_daily_kwh` needs **no change** (it already has `source` and `client_run_id`).
No change to the breakdown table (columns already existed).

---

## 4. Config / environment (Render)

Photo uploads reuse the existing S3 settings (`app/config.py` → `app/storage.py`). Confirm
these env vars are present on the Render service:
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (default `ap-south-1`)
- `AWS_S3_BUCKET_NAME`  ← **must be set**, else photo uploads raise `RuntimeError`

`DATABASE_URL` (RDS) unchanged. `python-multipart` is already a dependency (machine-transfers
uses it).

---

## 5. Timezone note

Schedule windows are **factory-local (Asia/Kolkata)**. `daily_kwh` depends only on the
window *duration*, so it's tz-independent; the generator stores `started_at`/`ended_at` as
UTC-naive (consistent with run rows) and only records a day once its window end has passed in IST.

---

## 6. Post-deploy smoke tests (curl)

```bash
BASE=https://maintenance-backend-pj31.onrender.com
TOKEN="Bearer <login-token>"

# B: list electric assets + schedules (any role)
curl -s "$BASE/asset-schedules?plant_id=both" -H "Authorization: $TOKEN" | head

# B: supervisor sets a 10:00-20:00 window (use a supervisor token)
curl -s -X PUT "$BASE/asset-schedules/<ASSET_ID>" -H "Authorization: $SUP_TOKEN" \
     -H "Content-Type: application/json" -d '{"start_min":600,"end_min":1200,"active":true}'

# A: work-done as multipart with a photo (should return ticket_status=PENDING_QC)
curl -s -X POST "$BASE/breakdowns/<REC_ID>/work-done" -H "Authorization: $TOKEN" \
     -F "user_id=7" -F "user_name=Ravi" -F "work_done=new gear installed" \
     -F "done_at=$(date +%s000)" -F "after_photo=@/path/to/photo.jpg"
```
Then confirm in pgAdmin: `mt_breakdown_records.work_done_des`/`photo_url` populated (photo_url is
an `https://…s3…/breakdowns/<id>/after.jpg` URL); `mt_machine_daily_kwh` has `source='SCHEDULE'` rows.

---

## 7. Test status

- `tests/test_asset_schedules.py` — **13/13 pass**.
- `tests/test_breakdowns.py` — pass (multipart + S3 assertions).
- **Pre-existing, unrelated failures:** `tests/test_reports_power.py` (5) fail because the test
  calls `/reports/power` while the route is `/head/reports/power`. This predates these changes
  and is not caused by them — fix the stale test path if you want the suite fully green.
