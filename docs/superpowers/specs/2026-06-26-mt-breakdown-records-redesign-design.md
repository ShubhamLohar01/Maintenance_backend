# mt_breakdown_records redesign — design

**Date:** 2026-06-26
**Status:** Approved (pending written-spec review)

## Problem

`mt_breakdown_records` currently does two unrelated jobs, told apart by a `source`
column:

- `OPERATOR_FLAG` rows — the live breakdown workflow (operator raises → technician
  acknowledges → does work → QC approves/rejects). Written by `POST /breakdowns/flag`
  and the `/breakdowns/{id}/qc/*` endpoints.
- `F06_RECORD` rows — the CFPLA.C4.F.06 paper-form checklist (sr_no, doc_no,
  signatures, verified_by). Written by `POST /preventive-maintenance/breakdowns`.

Mixing the two makes the table wide and confusing, and most columns are NULL for any
given row. We split it into two single-purpose tables and trim the live-workflow table
down to the columns the breakdown flow actually needs.

## Decisions (locked)

1. **Split the table.** `mt_breakdown_records` becomes the live-workflow table only;
   the F.06 paper form moves to its own table named **`mt_doc_breakdown`**.
2. **Two status fields.** A lifecycle `status` plus a separate `qc_status`. The
   lifecycle status drives "is the machine usable" and the open-breakdowns list.
3. **People stored as names** (free text). The Android app sends user *ids*; the
   backend resolves id → name against `mt_users` at write time before saving.
4. **Drop and recreate.** Existing rows are test data — `DROP` the old table and
   `CREATE` both new tables clean. No migration of existing rows.
5. **`end_time` = closure time** — filled when QC approves. On reject it stays NULL
   until the rework is finally approved.
6. **Keep `qc_reject_reason`** so a rejected breakdown tells the technician what to fix.
7. **Keep the operator's before-photo** (`before_photo_url`) at raise time.
8. **Add a technician-submit step** — today work-done/photo are bundled into the
   QC-approve call; they belong to the technician, so the flow gets an explicit
   "technician submits work done" transition (status → PENDING_QC).

Both tables live in RDS (`RdsBase`), pgAdmin-visible.

## Table 1 — `mt_breakdown_records` (live workflow)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | integer PK, autoincrement | no | |
| `machine_id` | varchar(64), indexed | yes | = `mt_asset_list.asset_id` (soft ref, same pattern as `mt_machine_daily_kwh.machine_id`) |
| `machine_name` | varchar(255) | yes | denormalized snapshot from the asset |
| `operator_raise_person` | varchar(128) | yes | name of operator who raised it |
| `start_time` | timestamp | yes | when raised |
| `description` | text | yes | the problem |
| `severity` | varchar(16) | yes | CRITICAL / MAJOR / MINOR |
| `before_photo_url` | text | yes | operator's photo at raise time |
| `status` | varchar(16), indexed | yes | OPEN / ACKNOWLEDGED / PENDING_QC / CLOSED / REOPENED |
| `technician` | varchar(128) | yes | name of technician who acknowledged |
| `ackn_at` | timestamp | yes | acknowledge time |
| `work_done_des` | text | yes | parts used / work done (by technician) |
| `photo_url` | text | yes | technician's after-repair photo |
| `qc_checked_by` | varchar(128) | yes | name of QC person |
| `qc_status` | varchar(16) | yes | PENDING / APPROVED / REJECTED |
| `qc_reject_reason` | text | yes | why QC rejected (set on REOPENED) |
| `end_time` | timestamp | yes | closure time (set when QC approves) |
| `created_at` | timestamp | no | audit, server default now() |
| `updated_at` | timestamp | no | audit, server default now() |

Index: `status` (open-breakdowns list), `machine_id` (per-asset lookup).

### SQLAlchemy model

```python
class BreakdownRecord(RdsBase):
    """One live breakdown event: operator raises -> technician acknowledges &
    repairs -> QC approves/rejects. Machine is usable again only when status=CLOSED."""
    __tablename__ = "mt_breakdown_records"

    id:                     Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:             Mapped[str | None]      = mapped_column(String(64), index=True, nullable=True)   # = mt_asset_list.asset_id
    machine_name:           Mapped[str | None]      = mapped_column(String(255), nullable=True)
    operator_raise_person:  Mapped[str | None]      = mapped_column(String(128), nullable=True)
    start_time:             Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description:            Mapped[str | None]      = mapped_column(Text, nullable=True)
    severity:               Mapped[str | None]      = mapped_column(String(16), nullable=True)
    before_photo_url:       Mapped[str | None]      = mapped_column(Text, nullable=True)
    status:                 Mapped[str | None]      = mapped_column(String(16), index=True, nullable=True)
    technician:             Mapped[str | None]      = mapped_column(String(128), nullable=True)
    ackn_at:                Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    work_done_des:          Mapped[str | None]      = mapped_column(Text, nullable=True)
    photo_url:              Mapped[str | None]      = mapped_column(Text, nullable=True)
    qc_checked_by:          Mapped[str | None]      = mapped_column(String(128), nullable=True)
    qc_status:              Mapped[str | None]      = mapped_column(String(16), nullable=True)
    qc_reject_reason:       Mapped[str | None]      = mapped_column(Text, nullable=True)
    end_time:               Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
    updated_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
```

### Raw DDL

```sql
DROP TABLE IF EXISTS mt_breakdown_records;

CREATE TABLE mt_breakdown_records (
    id                     SERIAL PRIMARY KEY,
    machine_id             VARCHAR(64),
    machine_name           VARCHAR(255),
    operator_raise_person  VARCHAR(128),
    start_time             TIMESTAMP,
    description            TEXT,
    severity               VARCHAR(16),
    before_photo_url       TEXT,
    status                 VARCHAR(16),
    technician             VARCHAR(128),
    ackn_at                TIMESTAMP,
    work_done_des          TEXT,
    photo_url              TEXT,
    qc_checked_by          VARCHAR(128),
    qc_status              VARCHAR(16),
    qc_reject_reason       TEXT,
    end_time               TIMESTAMP,
    created_at             TIMESTAMP NOT NULL DEFAULT now(),
    updated_at             TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_mt_breakdown_status     ON mt_breakdown_records (status);
CREATE INDEX idx_mt_breakdown_machine_id ON mt_breakdown_records (machine_id);
```

## Table 2 — `mt_doc_breakdown` (F.06 paper form)

Straight move of the F.06 columns out of the old table.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `doc_no` | varchar(32) | default 'CFPLA.C4.F.06' |
| `sr_no` | integer | 1-based row order within a submitted sheet |
| `record_date` | date | |
| `location` | varchar(128) | |
| `machine_name` | varchar(128) | |
| `equipment_model_no` | varchar(128) | |
| `problem_in_brief` | text | |
| `type_of_maintenance` | varchar(32) | |
| `part_of_machine` | varchar(128) | |
| `temporary_reason` | text | |
| `duration_start` | varchar(32) | |
| `duration_end` | varchar(32) | |
| `machine_operator_sign` | varchar(128) | |
| `maintenance_person_sign` | varchar(128) | |
| `qc_clearance_sign` | varchar(128) | |
| `verified_by` | varchar(128) | sheet-level |
| `created_by` | varchar(128) | logged-in user |
| `created_at` | timestamp | default now() |

### SQLAlchemy model

```python
class BreakdownDoc(RdsBase):
    """One row of a submitted CFPLA.C4.F.06 breakdown-maintenance sheet."""
    __tablename__ = "mt_doc_breakdown"

    id:                      Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_no:                  Mapped[str]          = mapped_column(String(32), nullable=False, default="CFPLA.C4.F.06")
    sr_no:                   Mapped[int | None]   = mapped_column(Integer, nullable=True)
    record_date:             Mapped[date | None]  = mapped_column(Date, nullable=True)
    location:                Mapped[str | None]   = mapped_column(String(128), nullable=True)
    machine_name:            Mapped[str | None]   = mapped_column(String(128), nullable=True)
    equipment_model_no:      Mapped[str | None]   = mapped_column(String(128), nullable=True)
    problem_in_brief:        Mapped[str | None]   = mapped_column(Text, nullable=True)
    type_of_maintenance:     Mapped[str | None]   = mapped_column(String(32), nullable=True)
    part_of_machine:         Mapped[str | None]   = mapped_column(String(128), nullable=True)
    temporary_reason:        Mapped[str | None]   = mapped_column(Text, nullable=True)
    duration_start:          Mapped[str | None]   = mapped_column(String(32), nullable=True)
    duration_end:            Mapped[str | None]   = mapped_column(String(32), nullable=True)
    machine_operator_sign:   Mapped[str | None]   = mapped_column(String(128), nullable=True)
    maintenance_person_sign: Mapped[str | None]   = mapped_column(String(128), nullable=True)
    qc_clearance_sign:       Mapped[str | None]   = mapped_column(String(128), nullable=True)
    verified_by:             Mapped[str | None]   = mapped_column(String(128), nullable=True)
    created_by:              Mapped[str | None]   = mapped_column(String(128), nullable=True)
    created_at:              Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)
```

### Raw DDL

```sql
CREATE TABLE mt_doc_breakdown (
    id                       SERIAL PRIMARY KEY,
    doc_no                   VARCHAR(32) NOT NULL DEFAULT 'CFPLA.C4.F.06',
    sr_no                    INTEGER,
    record_date              DATE,
    location                 VARCHAR(128),
    machine_name             VARCHAR(128),
    equipment_model_no       VARCHAR(128),
    problem_in_brief         TEXT,
    type_of_maintenance      VARCHAR(32),
    part_of_machine          VARCHAR(128),
    temporary_reason         TEXT,
    duration_start           VARCHAR(32),
    duration_end             VARCHAR(32),
    machine_operator_sign    VARCHAR(128),
    maintenance_person_sign  VARCHAR(128),
    qc_clearance_sign        VARCHAR(128),
    verified_by              VARCHAR(128),
    created_by               VARCHAR(128),
    created_at               TIMESTAMP NOT NULL DEFAULT now()
);
```

## Lifecycle & machine usability

```
operator raises    -> status=OPEN,         start_time, operator_raise_person, [before_photo_url]
technician acks    -> status=ACKNOWLEDGED,  technician, ackn_at
technician submits -> status=PENDING_QC,    qc_status=PENDING, work_done_des, photo_url
QC approves        -> status=CLOSED,        qc_status=APPROVED, qc_checked_by, end_time   (machine USABLE)
QC rejects         -> status=REOPENED,      qc_status=REJECTED, qc_reject_reason          (still under breakdown)
```

A machine is usable again **only when its latest breakdown row has `status=CLOSED`**.
`qc_status` is NULL until the technician submits work to QC.

## API impact

- `POST /breakdowns/flag` — write the new columns: `operator_raise_person` (resolve
  `operator_id`/current user → name), `start_time` (= raised_at), `machine_name`
  (from asset), optional `before_photo_url`. `status=OPEN`.
- `POST /breakdowns/{id}/qc/acknowledge` — set `technician` (resolve user id → name),
  `ackn_at`, `status=ACKNOWLEDGED`.
- **NEW** `POST /breakdowns/{id}/work-done` (technician) — set `work_done_des`,
  `photo_url`, `status=PENDING_QC`, `qc_status=PENDING`. (Splits work-done out of the
  QC-approve call, which currently carries it.)
- `POST /breakdowns/{id}/qc/approve` — set `qc_checked_by` (name), `qc_status=APPROVED`,
  `status=CLOSED`, `end_time`.
- `POST /breakdowns/{id}/qc/disapprove` — set `qc_checked_by`, `qc_status=REJECTED`,
  `status=REOPENED`, `qc_reject_reason`.
- `GET /breakdowns/open` — filter `status != 'CLOSED'`; `building` still derived by
  joining `machine_id` → `mt_asset_list`. Reporter name comes straight from
  `operator_raise_person` now (no more `mt_users` lookup for the name).
- `POST /preventive-maintenance/breakdowns` — repoint at `BreakdownDoc` /
  `mt_doc_breakdown`. No behavior change.
- `app/api/head.py` (escalations / breakdowns / qc views) — these read the old
  columns and must be updated: `reported_at`→`start_time`; `acknowledged_by`/
  `resolved_by`/`qc_decided_by` (ids resolved via `mt_users`) → the stored name
  columns `technician`/`qc_checked_by` (no lookup); `qc_decided_at`→`end_time`;
  `qc_notes`→`qc_reject_reason`; drop the `source` filter; status `QC_APPROVED`→
  `CLOSED`; `qc_status` `DISAPPROVED`→`REJECTED`. `before_photo_url` stays. There is
  no separate "work-done" timestamp, so the QC `awaiting` view's `resolved_at`
  becomes null and `resolved_by_name` maps to `technician`.
- `app/api/live.py` — the "PENDING_QC" machine set uses `BreakdownRecord.asset_id`
  → `machine_id`, drops the `source` filter, and `status != 'QC_APPROVED'` →
  `status != 'CLOSED'`.

The `source` discriminator and `_get_flag`'s `source == 'OPERATOR_FLAG'` guard are
removed (table is single-purpose now).

### API contract / JSON shape

Response **field names** stay the same (e.g. `OpenBreakdownDto.reported_at`,
`reporter_name`) so the apps' JSON parsing doesn't break — only how they're filled
changes (`reported_at` ← `start_time`, `reporter_name` ← `operator_raise_person`).
The **status string values** do change, per the chosen vocabulary: lifecycle terminal
state `QC_APPROVED`→`CLOSED`, and `qc_status` `DISAPPROVED`→`REJECTED`. The Android
(FactoryOps) and RN (Flutterproj) apps must update any code that switches on those
strings. This is tracked in Out of scope below.

## Columns dropped from the old table (intentional)

`source`, `reported_by`/`acknowledged_by`/`resolved_by`/`qc_decided_by` (replaced by
name columns), `resolved_at`/`qc_decided_at` (folded into `end_time`),
`qc_checklist_json`, `qc_notes` (replaced by `qc_reject_reason`), `created_by`,
`location`, and all F.06 columns (moved to `mt_doc_breakdown`).

## Out of scope / follow-ups

- Android (FactoryOps) + RN (Flutterproj) app changes: the new technician work-done
  step, and updating any code that switches on the changed status strings
  (`CLOSED`, `REJECTED`).
- Updating `docs/API_CONTRACT_FOR_ANDROID.md` to the new status vocabulary + the new
  `POST /breakdowns/{id}/work-done` endpoint.

## Migration steps (high level)

1. Replace `BreakdownRecord` in `app/models.py`; add `BreakdownDoc`.
2. Drop & recreate the tables in RDS (replace `scripts/migrate_breakdown_columns.py`
   with a drop/create script, or run the DDL above).
3. Update `app/api/breakdowns.py`, `app/api/breakdown_records.py`, `app/schemas.py`.
4. Update tests; run the suite.
