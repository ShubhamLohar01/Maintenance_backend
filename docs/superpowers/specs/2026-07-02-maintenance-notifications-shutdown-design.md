# Design — Maintenance app: breakdown lifecycle timestamps, machine shut-down, notification scaffolding

- **Date:** 2026-07-02
- **Source:** Backend work brief from the Android (FactoryOps) team (notifications + machine shut-down).
- **Status:** Approved for implementation, scoped as below.

## Context

The Android app added two features that touch the backend contract:

1. **Role-based reminders/notifications** computed on-device by polling existing
   endpoints and escalating based on how long an item has sat in a given state.
   This relies on **state-transition timestamps** being present in API responses.
2. **Machine "shut down"** (soft decommission): supervisors/admin/head write the
   literal string `"Shut Down"` to `mt_asset_list.condition` via the existing
   `PUT /mt-machines/{asset_id}`; the app then locks all actions on that machine.

Timestamps in payloads are **epoch milliseconds (integer)** — this convention is
kept everywhere. Auth is JWT bearer (unchanged).

## Scope

| Item | Decision |
|---|---|
| **P0 — breakdown lifecycle timestamps** | **Build now.** Section 1. |
| **P1 — machine shut-down enforcement** | **Build now.** Section 2. |
| **PM work orders backend-owned** | **Deferred to Phase 3.** Section 3 records the constraints; no code now. |
| **P2 — FCM push** | **Build safe scaffolding only** (token registry + fan-out module behind `FCM_ENABLED=false`). Escalation cron + sent-ledger deferred. Section 4. |

**Commit plan:** P0 and P1 ship first as **separate, independent commits** (so the
P0 fix that unblocks the shipped app feature is not held up by anything else). The
P2 scaffolding is a **separate commit** from P0/P1. Section 3 is documentation only.

---

## Section 1 — P0: Breakdown lifecycle timestamps

### Problem

`GET /breakdowns/open` returns only `reported_at`. The app's time-based reminder
escalation can't fire correctly without acknowledgement / resolution / QC
timestamps. Of the four timestamps the app needs, only `acknowledged_at` has a
backing column today (`mt_breakdown_records.ackn_at`); the other transition times
are **received by the write endpoints and then discarded**.

### Data model change

Add three nullable columns to `mt_breakdown_records` (`acknowledged_at` already
exists as `ackn_at`):

```sql
ALTER TABLE mt_breakdown_records
  ADD COLUMN IF NOT EXISTS resolved_at        timestamp NULL,
  ADD COLUMN IF NOT EXISTS qc_acknowledged_at timestamp NULL,
  ADD COLUMN IF NOT EXISTS qc_decided_at      timestamp NULL;
```

There is **no Alembic** in this project — schema is created by
`Base.metadata.create_all`, which only creates missing *tables*, never adds
columns to an existing one. The DDL above must be run manually in pgAdmin on RDS.
The columns are nullable, so it is non-breaking. Tests build tables fresh from the
models and therefore need no migration.

`BreakdownRecord` (SQLAlchemy model) gains the three matching mapped columns.

### Population on transition

| Lifecycle event | Endpoint | Column written |
|---|---|---|
| technician acknowledges | `POST /breakdowns/{id}/qc/acknowledge` (no `qc_checked_by`) | `ackn_at` (existing; surfaced as `acknowledged_at`) |
| QC picks up the ticket | `POST /breakdowns/{id}/qc/acknowledge` **with** `qc_checked_by` | `qc_acknowledged_at` + `qc_checked_by` — **does not touch** `ackn_at` or `status` |
| repair completed | `POST /breakdowns/{id}/work-done` | `resolved_at = done_at` (currently discarded) |
| QC approve | `POST /breakdowns/{id}/qc/approve` | `qc_decided_at = decided_at` (existing `end_time` still set) |
| QC disapprove | `POST /breakdowns/{id}/qc/disapprove` | `qc_decided_at = decided_at` |

### Behavior change (flag to app team)

Today the QC-pickup call (`qc_checked_by` present) flips the ticket back to
`ACKNOWLEDGED` and overwrites `ackn_at`. This was a bug: the app expects
`PENDING_QC` to persist through QC review. The QC-pickup branch will now **leave
`status` and `ackn_at` untouched** and only stamp `qc_acknowledged_at` +
`qc_checked_by`. Consequently the response `ticket_status` for that call stays at
its prior value (e.g. `PENDING_QC`) instead of becoming `ACKNOWLEDGED`. The
technician-ack branch (no `qc_checked_by`) is unchanged.

### API change

`OpenBreakdownDto` gains four fields, all **epoch-ms integers, nullable** until the
transition happens, serialized exactly like `reported_at` (via `to_epoch_ms`) — NOT
ISO strings (the app parses them as `Long`):

```
acknowledged_at:    Optional[int]   # <- ackn_at
resolved_at:        Optional[int]   # <- resolved_at
qc_acknowledged_at: Optional[int]   # <- qc_acknowledged_at
qc_decided_at:      Optional[int]   # <- qc_decided_at
```

`GET /breakdowns/open` already filters `status != "CLOSED"`, so OPEN /
ACKNOWLEDGED / PENDING_QC / REOPENED are all already returned — **confirmed, no
change needed**. (`qc/disapprove` currently sets status to `"OPEN"`, not
`"REOPENED"`; the reminders key off `qc_decided_at` + `qc_status = DISAPPROVED`, so
this string is not load-bearing. Noted, left as-is.)

### Tests (pytest, `tests/test_breakdowns.py`)

- Walk a ticket flag → acknowledge → work-done → qc-approve and assert all four
  fields serialize as ints matching the same clock as `reported_at`.
- QC-pickup (`qc_checked_by` present) stamps `qc_acknowledged_at`, keeps status
  `PENDING_QC`, and does **not** overwrite `ackn_at`.
- Disapprove stamps `qc_decided_at`.
- Fields are `null` before their transition.

---

## Section 2 — P1: Machine shut-down enforcement

### Round-trip (already works — lock in with a test)

`PUT /mt-machines/{asset_id}` writes `condition` verbatim and `GET /mt-machines`
returns it unchanged; no other server flow writes `mt_asset_list.condition`. So the
`"Shut Down"` sentinel already survives, and restore (`condition: null`) clears it.
Add a regression test asserting the `"Shut Down"` ↔ `null` round-trip.

### Server-side guards (defense-in-depth)

Add `is_shut_down(condition) -> bool` in `app/utils.py` (strip + case-insensitive
`== "shut down"`, so `"Shut Down"`/`" shut down "` match). Reject these when the
target asset is shut down, with HTTP **409** and detail `"Machine is shut down"`:

- `POST /energy/runs/start` (production start)
- `POST /breakdowns/flag` (raise breakdown)

Note: the app's raise/start paths are offline-first and may retry on a 409; the
guard is still wanted as server-side defense-in-depth.

### Tests

- `test_mt_machines_update.py`: `"Shut Down"` ↔ `null` round-trip.
- `test_energy.py`: run-start on a shut-down asset → 409.
- `test_breakdowns.py`: flag on a shut-down asset → 409.

---

## Section 3 — PM work orders (DEFERRED to Phase 3, no code now)

There is no PM work-order entity server-side today; the app's PM workflow is fully
client-side. **Do not build now** — the naive form/title/due_at shape would diverge
from the app's model. Recorded here so Phase 3 builds the right thing:

- (a) Must mirror the app's `PmWorkOrder`: **plan/template-driven** with
  `template_id` / `template_name`, `machine_type`, `trade_type`,
  `estimated_duration_minutes`, `scheduled_date`, `escalation_tier`, plus **child
  task-log items and spares** — NOT a `form_type` / `title` / `due_at` shape.
- (b) Work orders are **auto-generated from a `PmPlan` schedule**, not created
  manually. Supervisors create *plans*, not work orders.
- (c) A first-cut design was missing: task logs, spares, the template fields,
  `trade_type`, and `escalation_tier`.

The four escalation timestamps the app will eventually need on the PM WO payload
(`submitted_at`, `supervisor_approved_at`, `supervisor_rejected_at`,
`qc_decided_at`) plus the status enum (`DRAFT, NOTIFIED, ACKNOWLEDGED, IN_PROGRESS,
SUBMITTED, SUPERVISOR_APPROVED, PENDING_QC, QC_APPROVED, CLOSED, OVERDUE,
CANCELLED`) and a per-plant "non-closed WOs" list endpoint are the Phase-3
deliverable, to be co-designed against the app's actual model.

---

## Section 4 — P2: FCM push (safe scaffolding only)

Built behind a config flag so **nothing sends** until we deliberately move off
polling (avoids double-notify while the app still polls). This is a **separate
commit** from P0/P1.

### Build now

- **`POST /devices/token`** — register a device token.
  - Body: `{ "user_id": "...", "token": "<fcm-token>", "platform": "android" }`,
    JWT-authenticated.
  - New table `mt_device_tokens` (`id, user_id, token UNIQUE, platform, created_at,
    updated_at`). **Upsert on `token`**; multiple devices per user supported.
- **Fan-out module** `app/notifications/`:
  - Envelope builder producing the exact data-message shape the app maps to its
    in-app renderer: `type, category, entityId, targetRole, targetUserId, title,
    body, tier, deepLinkExtraKey`.
    - `type ∈ {B1_NEW_BREAKDOWN, B2_ACK_STALE, B3_AWAITING_QC, B4_REOPENED,
      P2_AWAITING_SUPERVISOR, P3_SUPERVISOR_REJECTED, P4_AWAITING_QC,
      P5_QC_REJECTED}`
    - `category ∈ {BREAKDOWN, PM}`
    - `deepLinkExtraKey = "ticket_id"` (breakdown) / `"pm_wo_id"` (PM)
    - `tier` = escalation level (`"0"` = first nudge).
  - Audience resolver: target role → `MtUser`s in that plant → their device tokens.
  - **Sender abstraction:** a real `firebase-admin` sender used only when creds are
    configured, else a no-op logging sender. Selected by config.
- **Config flag `FCM_ENABLED` (default `false`).** When false, fan-out is a no-op
  (logs only). No token is sent to Firebase.

### Held until we commit to moving off polling (NOT in this commit)

- The deadline-based **escalation cron** (`POST /notifications/run-escalations`
  driven by Render Cron every ~2 min) and the **`mt_notifications_sent` ledger**
  (entity + type + tier, send-exactly-once). These are Phase-2C-exit work.

### Infra notes (for the user)

- The app is already FCM-wired to a Firebase project; the same project's
  **service-account JSON** will be provided. Backend never reads `.env` directly in
  this repo workflow — the required env vars are listed in the delivery notes
  (`FCM_ENABLED`, and the service-account credential var) for the user to set on
  Render.
- Render Cron is available for the escalation endpoint when Phase-2C exit happens.

---

## Test / acceptance summary

- **P0:** four fields serialize as epoch-ms ints for a ticket walked through
  acknowledge → resolve → qc-decide; null before each transition; QC-pickup keeps
  `PENDING_QC` and preserves `ackn_at`.
- **P1:** `PUT`→`GET` round-trips `condition = "Shut Down"` and `null`; run-start
  and raise-flag on a shut-down asset are rejected (409). pytest covers both.
- **P2 scaffolding:** `POST /devices/token` upserts a token; repeat token updates in
  place; fan-out is a no-op while `FCM_ENABLED=false`. pytest covers token upsert
  and the flag-off no-op path.

## Out of scope

- Alembic / automated migrations (manual pgAdmin DDL per existing repo convention).
- PM work-order entity and endpoints (Phase 3).
- Escalation scheduler + sent ledger + live FCM sending (Phase-2C exit).
