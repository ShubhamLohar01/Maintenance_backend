# Machine Transfer — table + FE↔BE wiring (handoff)

**Status: already implemented end-to-end in code.** The table is being renamed from
`doc_machine_transfer` → `mt_machine_transfer`. The ORM model (`app/models.py`) now points at
`mt_machine_transfer`, so the DB must use that name too, **deployed together** (if the code
ships before the table is renamed — or vice-versa — `POST/GET /machine-transfers` will 500).

- Frontend: `TransferFormScreen` → `TransferFormViewModel.submit()` →
  `MachineTransferRepositoryImpl.createTransfer()` → `MachineTransferApi` (multipart) →
  `POST /machine-transfers`.
- Backend: `app/api/machine_transfers.py` (POST + GET, S3 proof upload) +
  `MachineTransfer` model (`mt_machine_transfer`), router already registered in `app/main.py`.

The table name **must be exactly `mt_machine_transfer`** and column names/types must match
the ORM model, or the endpoint 500s.

---

## 1. SQL — run on RDS Postgres

**Case A — the `doc_machine_transfer` table already exists (rename, keeps all data):**

```sql
ALTER TABLE doc_machine_transfer RENAME TO mt_machine_transfer;

-- optional: tidy the auto-created index names to match (harmless if skipped / if names differ)
ALTER INDEX IF EXISTS ix_doc_machine_transfer_from_warehouse RENAME TO ix_mt_machine_transfer_from_warehouse;
ALTER INDEX IF EXISTS ix_doc_machine_transfer_to_warehouse   RENAME TO ix_mt_machine_transfer_to_warehouse;
```

**Case B — fresh install, no existing table (create):**

```sql
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

CREATE INDEX IF NOT EXISTS idx_mt_machine_transfer_from    ON mt_machine_transfer (from_warehouse);
CREATE INDEX IF NOT EXISTS idx_mt_machine_transfer_to      ON mt_machine_transfer (to_warehouse);
CREATE INDEX IF NOT EXISTS idx_mt_machine_transfer_created ON mt_machine_transfer (created_at DESC);
```

> Use **Case A** if a prior backend startup already auto-created `doc_machine_transfer`
> (`Base.metadata.create_all()` does this when RDS is reachable). Otherwise use **Case B**.

---

## 2. Field mapping (form → column → API)

| Transfer form field | DB column | Type | Required | Notes |
|---|---|---|---|---|
| date | `transfer_date` | DATE | no | ISO `yyyy-MM-dd`; defaults to today (server) |
| From warehouse | `from_warehouse` | VARCHAR(32) | yes | e.g. `A185` |
| To warehouse | `to_warehouse` | VARCHAR(32) | yes | must differ from `from` |
| Machine name | `machine_name` | VARCHAR(255) | yes | |
| Machine code (model/Sr.No.) | `machine_code` | VARCHAR(128) | no | |
| Condition | `condition` | VARCHAR(64) | no | |
| Reason | `reason` | TEXT | no | |
| Authorised person | `authorised_person` | VARCHAR(255) | no | |
| Remarks | `remarks` | TEXT | no | |
| Proof photo (file) | `proof_photo_url` | TEXT | no | uploaded to S3, URL stored |
| (JWT) | `created_by` | VARCHAR(128) | — | logged-in username |
| (server) | `created_at` | TIMESTAMP | — | `now()` |

---

## 3. API contract (already served)

`POST /machine-transfers` — **multipart/form-data**, JWT required:
- form: `from_warehouse`(req), `to_warehouse`(req), `machine_name`(req),
  `date`, `machine_code`, `condition`, `reason`, `authorised_person`, `remarks`
- file: `proof_photo` (optional; jpeg/png ≤10 MB → S3 key `machine-transfers/{id}.{ext}`)
- 400 if a required field is missing or `from == to`. 201 → `{ id, proof_photo_url }`.

`GET /machine-transfers` — JWT required → newest first:
`[{ id, date, from_warehouse, to_warehouse, machine_name, condition, created_at, proof_photo_url }]`

---

## 4. Backend team steps

1. Run the SQL in section 1 on the RDS Postgres DB (`DATABASE_URL`).
2. Confirm S3 env vars on Render (same ones the breakdown/asset work needs):
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (default `ap-south-1`),
   **`AWS_S3_BUCKET_NAME`** (required for the proof photo; text fields work without it).
3. Deploy the current backend (router already registered — nothing to add).
4. Smoke test:
   ```bash
   BASE=https://maintenance-backend-pj31.onrender.com
   curl -s -X POST "$BASE/machine-transfers" -H "Authorization: Bearer <token>" \
        -F "from_warehouse=A185" -F "to_warehouse=W202" -F "machine_name=Pan Coater" \
        -F "reason=line rebalance" -F "proof_photo=@/path/photo.jpg"
   curl -s "$BASE/machine-transfers" -H "Authorization: Bearer <token>" | head
   ```
   Then confirm a row in `mt_machine_transfer` with `proof_photo_url` = an `https://…s3…/machine-transfers/<id>.jpg` URL.

---

## 5. Receiving-warehouse acknowledgement (added 2026-07-02)

New: a transfer is **PENDING** until the receiving warehouse confirms the machine
arrived (**APPROVED**). The app's new "Transfer Records" page lists transfers and shows
an **Acknowledge** button on rows the caller may confirm.

### 5a. SQL — add the columns to `mt_machine_transfer`

```sql
ALTER TABLE mt_machine_transfer
    ADD COLUMN IF NOT EXISTS status          VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS acknowledged_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMP;
```

### 5b. New endpoint (already implemented in `app/api/machine_transfers.py`)

`POST /machine-transfers/{id}/acknowledge` — JWT required. Sets `status='APPROVED'`,
`acknowledged_by = <caller name>`, `acknowledged_at = now`. Returns the updated row.
- **Permission:** SUPERVISOR → any transfer; TECHNICIAN → only when their plant
  (`mt_users.location`) equals the transfer's **`to_warehouse`** (destination). HEAD/others → **403**.
- **404** if the id doesn't exist. **Idempotent** — re-acknowledging an APPROVED row returns it unchanged.

`GET /machine-transfers` now also returns, per row: `status`, `acknowledged_by`,
`acknowledged_at`, `proof_photo_url`, and **`can_acknowledge`** (a per-caller boolean the
app uses to show/hide the Acknowledge button — the POST re-checks it server-side).

### 5c. Steps
1. Run the SQL in 5a on RDS.
2. Deploy the backend (endpoint + model columns already in code — deploy together with the SQL).
3. Verify:
   ```bash
   # as a W-202 technician (or any supervisor), acknowledge an A185→W202 transfer:
   curl -s -X POST "$BASE/machine-transfers/<id>/acknowledge" -H "Authorization: Bearer <token>"
   # -> {"id":.., "status":"APPROVED", "acknowledged_by":"Manish", ...}
   ```
   A technician of the WRONG plant should get **403**.
