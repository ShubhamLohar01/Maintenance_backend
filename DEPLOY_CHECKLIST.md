# Backend Deploy Checklist — all changes (as of 2026-07-04)

Everything the backend needs to go live for: **breakdown photos/persistence fix**,
**Schedule Electric Assets**, and **Machine Transfer (rename + acknowledge + duplicate guard)**.
Run the SQL on RDS, deploy the code, confirm env, verify. **App + backend must ship together.**

---

## 1. SQL — run on RDS Postgres (`DATABASE_URL`), in this order

### A. Machine transfer table — rename + all new columns (idempotent)
```sql
-- Rename the old table if it exists (keeps data). No-op if it doesn't.
ALTER TABLE IF EXISTS doc_machine_transfer RENAME TO mt_machine_transfer;

-- Create fresh if it doesn't exist at all.
CREATE TABLE IF NOT EXISTS mt_machine_transfer (
    id                SERIAL PRIMARY KEY,
    transfer_date     DATE,
    from_warehouse    VARCHAR(32)  NOT NULL,
    to_warehouse      VARCHAR(32)  NOT NULL,
    machine_name      VARCHAR(255) NOT NULL,
    machine_code      VARCHAR(128),
    condition         VARCHAR(64),
    reason            TEXT,
    authorised_person VARCHAR(255),
    remarks           TEXT,
    proof_photo_url   TEXT,
    created_by        VARCHAR(128),
    created_at        TIMESTAMP NOT NULL DEFAULT now()
);

-- New columns for acknowledge + duplicate guard (safe whether renamed or freshly created).
ALTER TABLE mt_machine_transfer
    ADD COLUMN IF NOT EXISTS status          VARCHAR(16) NOT NULL DEFAULT 'PENDING',  -- PENDING | APPROVED
    ADD COLUMN IF NOT EXISTS acknowledged_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS machine_id      VARCHAR(64);                             -- = mt_asset_list.asset_id when picked

CREATE INDEX IF NOT EXISTS idx_mt_machine_transfer_from       ON mt_machine_transfer (from_warehouse);
CREATE INDEX IF NOT EXISTS idx_mt_machine_transfer_to         ON mt_machine_transfer (to_warehouse);
CREATE INDEX IF NOT EXISTS idx_mt_machine_transfer_machine_id ON mt_machine_transfer (machine_id);
```
> Rare edge case: if BOTH `doc_machine_transfer` and `mt_machine_transfer` already exist,
> the RENAME errors (target exists) — pick one table, drop/merge the other, then run the ALTER.

### B. Schedule Electric Assets — columns on `mt_asset_list`
```sql
ALTER TABLE mt_asset_list
    ADD COLUMN IF NOT EXISTS schedule_start_min      INTEGER,        -- minute-of-day IST, 600 = 10:00
    ADD COLUMN IF NOT EXISTS schedule_end_min        INTEGER,        -- must be > start
    ADD COLUMN IF NOT EXISTS schedule_active         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS schedule_last_generated DATE,
    ADD COLUMN IF NOT EXISTS schedule_updated_by     VARCHAR(128),
    ADD COLUMN IF NOT EXISTS schedule_updated_at     TIMESTAMP;
```

### C. Breakdowns — **no SQL** (`work_done_des`, `photo_url`, `before_photo_url` already exist
in `mt_breakdown_records`). Energy/schedule rows reuse existing `mt_machine_daily_kwh` columns.

---

## 2. Deploy the backend code

Deploy the current source (all changed together):
- `app/models.py` — `mt_machine_transfer` rename + `status`/`acknowledged_by`/`acknowledged_at`/`machine_id`; `mt_asset_list` schedule columns.
- `app/schemas.py` — transfer + asset-schedule DTOs.
- `app/main.py` — registers the `asset_schedules` router.
- `app/api/breakdowns.py` — `/breakdowns/flag` + `/breakdowns/{id}/work-done` are now **multipart** + S3 upload.
- `app/api/machine_transfers.py` — building-move on create, acknowledge endpoint, duplicate-pending 409 guard.
- `app/api/asset_schedules.py` — **new** router.

---

## 3. Environment (Render)

Confirm these are set (photos fail without the bucket):
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (default `ap-south-1`), **`AWS_S3_BUCKET_NAME`**
- `DATABASE_URL` (RDS) — unchanged.

`python-multipart` is already a dependency.

---

## 4. API contract changes (for app/other clients)

- `POST /breakdowns/flag` and `POST /breakdowns/{id}/work-done` — **JSON → multipart/form-data** (optional `before_photo`/`after_photo` file → S3 → `before_photo_url`/`photo_url`).
- **NEW** `GET/PUT/DELETE /asset-schedules` + `POST /asset-schedules/generate` — electric-asset daily recording (SUPERVISOR writes, HEAD read-only).
- `POST /machine-transfers` — multipart; accepts `asset_id`; returns **409** if the machine already has a PENDING transfer.
- **NEW** `POST /machine-transfers/{id}/acknowledge` — receiving warehouse confirms receipt (PENDING → APPROVED). SUPERVISOR any; TECHNICIAN only their destination plant; else 403.
- `GET /machine-transfers` rows now include `status`, `acknowledged_by`, `acknowledged_at`, `can_acknowledge`, `machine_id`, `proof_photo_url`.

---

## 5. Verify (curl)

```bash
BASE=https://maintenance-backend-pj31.onrender.com
TOK="Bearer <token>"

curl -s "$BASE/health"                                             # {"status":"ok"}
curl -s "$BASE/asset-schedules?plant_id=both" -H "Authorization: $TOK" | head
curl -s "$BASE/machine-transfers" -H "Authorization: $TOK" | head  # rows have status/can_acknowledge

# duplicate guard: create the same machine twice -> 2nd is 409
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/machine-transfers" -H "Authorization: $TOK" \
     -F from_warehouse=W202 -F to_warehouse=A185 -F machine_name="Dup Test"
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE/machine-transfers" -H "Authorization: $TOK" \
     -F from_warehouse=W202 -F to_warehouse=A185 -F machine_name="Dup Test"   # -> 409
```
Then in pgAdmin: `mt_breakdown_records.photo_url` is an `https://…s3…` URL after a work-done with photo;
`mt_machine_daily_kwh` has `source='SCHEDULE'` rows; `mt_machine_transfer.status` flips to APPROVED on acknowledge.

Run the suite before deploy: `python -m pytest -q` (asset-schedules 13, transfer/ack/guard 22 green;
the 5 `test_reports_power.py` failures are pre-existing/unrelated — stale `/reports/power` vs `/head/reports/power` path).

---

## 6. Optional — stop the cold-start slowness (infra, not code)

Render free tier sleeps (~30-50s to wake). Either upgrade to a **Starter** instance (no sleep),
or add an external uptime pinger (UptimeRobot / cron-job.org) hitting `/health` every 5 min.
