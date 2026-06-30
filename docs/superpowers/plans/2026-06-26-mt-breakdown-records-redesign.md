# mt_breakdown_records Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the overloaded `mt_breakdown_records` table into a clean live-breakdown-workflow table and a separate `mt_doc_breakdown` table for the F.06 paper form, and update every caller.

**Architecture:** `mt_breakdown_records` becomes single-purpose (operator raises → technician acknowledges → technician submits work → QC approves/rejects). People are stored as names (resolved from `mt_users` at write time). A new `mt_doc_breakdown` table holds the CFPLA.C4.F.06 checklist rows. The `source` discriminator is removed. Status vocabulary changes: terminal lifecycle state `QC_APPROVED`→`CLOSED`, `qc_status` `DISAPPROVED`→`REJECTED`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (typed `Mapped[...]`), Pydantic v2, pytest, SQLite (tests) / RDS Postgres (prod).

**Spec:** `docs/superpowers/specs/2026-06-26-mt-breakdown-records-redesign-design.md`

**Run tests with:** `python -m pytest` (from `d:\Maintenance module\backend`). This repo is NOT a git repo, so the "Commit" steps are noted but optional — if `git` is unavailable, skip them.

---

## File Structure

- `app/models.py` — replace `BreakdownRecord`; add `BreakdownDoc` (`mt_doc_breakdown`).
- `app/schemas.py` — add `BreakdownWorkDoneRequest`; update `QcStatus` literal; comment updates.
- `app/api/breakdowns.py` — rewrite flag/ack/qc endpoints for new columns + name resolution; add `POST /breakdowns/{id}/work-done`; drop `source` guard.
- `app/api/breakdown_records.py` — write to `BreakdownDoc` instead of `BreakdownRecord`.
- `app/api/head.py` — column renames; drop `source` filter; `QC_APPROVED`→`CLOSED`, `DISAPPROVED`→`REJECTED`; names read directly.
- `app/api/live.py` — `asset_id`→`machine_id`, drop `source` filter, `QC_APPROVED`→`CLOSED`.
- `scripts/recreate_breakdown_tables.py` — NEW drop-&-recreate DDL script; delete old `scripts/migrate_breakdown_columns.py`.
- `tests/conftest.py` — register `BreakdownDoc` in `_TABLES`.
- `tests/test_breakdowns.py` — rewrite for the operator workflow + new endpoint.
- `tests/test_breakdown_docs.py` — NEW; F.06 sheet tests moved here, asserting on `BreakdownDoc`.
- `tests/test_head_escalations.py` — update `_flag` helper + status values.
- `docs/API_CONTRACT_FOR_ANDROID.md` — new status vocabulary + new endpoint.

---

## Task 1: Replace the models

**Files:**
- Modify: `app/models.py:235-284` (the `BreakdownRecord` class)
- Modify: `tests/conftest.py:18-33` (imports + `_TABLES`)

- [ ] **Step 1: Replace the `BreakdownRecord` class**

In `app/models.py`, replace the ENTIRE existing `BreakdownRecord` class (lines 235-284, from `class BreakdownRecord(RdsBase):` through the last `qc_notes` column) with the two classes below:

```python
class BreakdownRecord(RdsBase):
    """One live breakdown event: operator raises -> technician acknowledges &
    repairs -> QC approves/rejects. People are stored as names (resolved from
    mt_users at write time). The machine is usable again only when status=CLOSED."""
    __tablename__ = "mt_breakdown_records"

    id:                     Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:             Mapped[str | None]      = mapped_column(String(64), index=True, nullable=True)   # = mt_asset_list.asset_id
    machine_name:           Mapped[str | None]      = mapped_column(String(255), nullable=True)
    operator_raise_person:  Mapped[str | None]      = mapped_column(String(128), nullable=True)
    start_time:             Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description:            Mapped[str | None]      = mapped_column(Text, nullable=True)
    severity:               Mapped[str | None]      = mapped_column(String(16), nullable=True)               # CRITICAL|MAJOR|MINOR
    before_photo_url:       Mapped[str | None]      = mapped_column(Text, nullable=True)
    # OPEN | ACKNOWLEDGED | PENDING_QC | CLOSED | REOPENED (machine usable only when CLOSED)
    status:                 Mapped[str | None]      = mapped_column(String(16), index=True, nullable=True)
    technician:             Mapped[str | None]      = mapped_column(String(128), nullable=True)
    ackn_at:                Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    work_done_des:          Mapped[str | None]      = mapped_column(Text, nullable=True)
    photo_url:              Mapped[str | None]      = mapped_column(Text, nullable=True)
    qc_checked_by:          Mapped[str | None]      = mapped_column(String(128), nullable=True)
    qc_status:              Mapped[str | None]      = mapped_column(String(16), nullable=True)               # PENDING|APPROVED|REJECTED
    qc_reject_reason:       Mapped[str | None]      = mapped_column(Text, nullable=True)
    end_time:               Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # set when QC approves
    created_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
    updated_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


class BreakdownDoc(RdsBase):
    """One row of a submitted CFPLA.C4.F.06 breakdown-maintenance sheet. Moved out
    of mt_breakdown_records (which is now the live-workflow table only)."""
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

(`datetime`, `date`, `func`, `Integer`, `String`, `Text`, `Date`, `DateTime`, `Mapped`, `mapped_column` are already imported at the top of `models.py` — no new imports needed.)

- [ ] **Step 2: Register `BreakdownDoc` in the test harness**

In `tests/conftest.py`, add `BreakdownDoc` to the model import block (currently lines 18-24) and to `_TABLES` (lines 27-33):

```python
from app.models import (
    BreakdownRecord,
    BreakdownDoc,
    MtAsset,
    MtUser,
    MachineDailyKwh,
    MtFloorUtilityReading,
)

# RdsBase tables the suite needs (all SQLite-compatible — no JSONB columns).
_TABLES = [
    BreakdownRecord,
    BreakdownDoc,
    MtAsset,
    MtUser,
    MachineDailyKwh,
    MtFloorUtilityReading,
]
```

- [ ] **Step 3: Verify the app still imports**

Run: `python -c "import app.main"`
Expected: no output, exit code 0 (no `ImportError` / `ArgumentError`). Existing callers still reference old attributes; they're fixed in later tasks, but a bare import must succeed.

- [ ] **Step 4: Commit (optional — skip if not a git repo)**

```bash
git add app/models.py tests/conftest.py
git commit -m "refactor(models): split mt_breakdown_records into live-workflow + mt_doc_breakdown"
```

---

## Task 2: Rewrite the operator-breakdown workflow API

**Files:**
- Modify: `app/schemas.py` (add `BreakdownWorkDoneRequest`; widen `BreakdownFlagRequest`; update `QcStatus`)
- Modify: `app/api/breakdowns.py` (rewrite the whole file)
- Test: `tests/test_breakdowns.py` (rewrite — Step 1)

- [ ] **Step 1: Rewrite `tests/test_breakdowns.py` for the new workflow**

Replace the ENTIRE contents of `tests/test_breakdowns.py` with:

```python
"""Operator breakdown workflow on mt_breakdown_records (now a single-purpose table):
flag -> acknowledge -> work-done -> QC approve/reject, plus GET /breakdowns/open.
People are stored as names (resolved from mt_users at write time)."""

from app.models import BreakdownRecord, MtAsset, MtUser
from app.utils import to_epoch_ms

NOW = 1750768500000  # epoch ms


def _seed(db):
    if db.query(MtAsset).filter(MtAsset.asset_id == "W202-0005").first() is None:
        db.add_all([
            MtAsset(asset_id="W202-0005", asset_name="Band Sealer", building="W-202", sub_location="2nd Floor"),
            MtAsset(asset_id="A185-0001", asset_name="Tubelight", building="A-185", sub_location="LB"),
        ])
        db.commit()
    if db.query(MtUser).filter(MtUser.id == 42).first() is None:
        db.add(MtUser(id=42, name="Anil", username="anil", location="W-202", role="OPERATOR"))
        db.commit()


def _flag(c, asset="W202-0005"):
    r = c.post("/breakdowns/flag", json={
        "machine_id": asset, "operator_id": "42", "severity": "MAJOR",
        "description": "jaw not heating", "raised_at": NOW})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_flag_creates_open_record(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    rec = db_session.get(BreakdownRecord, int(fid))
    assert rec.status == "OPEN"
    assert rec.machine_id == "W202-0005"
    assert rec.machine_name == "Band Sealer"
    assert rec.severity == "MAJOR"
    assert rec.description == "jaw not heating"
    assert rec.operator_raise_person == "Anil"          # resolved from mt_users id 42
    assert to_epoch_ms(rec.start_time) == NOW            # round-trips through a tz-naive column


def test_flag_falls_back_to_caller_name_when_unknown_operator(auth_client, db_session):
    _seed(db_session)
    r = auth_client.post("/breakdowns/flag", json={
        "machine_id": "W202-0005", "operator_id": "999", "severity": "MINOR",
        "description": "x", "raised_at": NOW})
    assert r.status_code == 200, r.text
    rec = db_session.get(BreakdownRecord, int(r.json()["id"]))
    assert rec.operator_raise_person == "Tester"        # StubUser.name fallback


def test_flag_unknown_asset_404(auth_client, db_session):
    _seed(db_session)
    r = auth_client.post("/breakdowns/flag", json={
        "machine_id": "ZZZ-9999", "operator_id": "42", "severity": "MINOR",
        "description": "x", "raised_at": NOW})
    assert r.status_code == 404


def test_full_lifecycle(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)

    ack = auth_client.post(f"/breakdowns/{fid}/qc/acknowledge", json={
        "user_id": "7", "user_name": "Ravi", "acknowledged_at": NOW}).json()
    assert ack["ticket_status"] == "ACKNOWLEDGED"
    rec = db_session.get(BreakdownRecord, int(fid))
    db_session.refresh(rec)
    assert rec.technician == "Ravi"
    assert to_epoch_ms(rec.ackn_at) == NOW

    wd = auth_client.post(f"/breakdowns/{fid}/work-done", json={
        "user_id": "7", "user_name": "Ravi", "work_done": "replaced coil",
        "after_photo_path": "s3://x/after.jpg", "done_at": NOW}).json()
    assert wd["ticket_status"] == "PENDING_QC"
    assert wd["qc_status"] == "PENDING"
    db_session.refresh(rec)
    assert rec.work_done_des == "replaced coil"
    assert rec.photo_url == "s3://x/after.jpg"

    dis = auth_client.post(f"/breakdowns/{fid}/qc/disapprove", json={
        "user_id": "9", "user_name": "Qcuser", "decided_at": NOW,
        "reason": "not fixed"}).json()
    assert dis["ticket_status"] == "REOPENED"
    assert dis["qc_status"] == "REJECTED"
    db_session.refresh(rec)
    assert rec.qc_reject_reason == "not fixed"
    assert rec.qc_checked_by == "Qcuser"

    app_ = auth_client.post(f"/breakdowns/{fid}/qc/approve", json={
        "user_id": "9", "user_name": "Qcuser", "decided_at": NOW,
        "notes": "ok"}).json()
    assert app_["ticket_status"] == "CLOSED"
    assert app_["qc_status"] == "APPROVED"
    assert app_["machine_status"] == "AVAILABLE"
    db_session.refresh(rec)
    assert rec.qc_checked_by == "Qcuser"
    assert to_epoch_ms(rec.end_time) == NOW


def test_open_endpoint_excludes_closed(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    assert any(x["id"] == fid for x in auth_client.get("/breakdowns/open").json())
    auth_client.post(f"/breakdowns/{fid}/qc/approve", json={
        "user_id": "9", "user_name": "Qcuser", "decided_at": NOW})
    assert fid not in [x["id"] for x in auth_client.get("/breakdowns/open").json()]


def test_open_endpoint_fields(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    row = next(x for x in auth_client.get("/breakdowns/open").json() if x["id"] == fid)
    assert row["asset_id"] == "W202-0005"
    assert row["asset_name"] == "Band Sealer"
    assert row["reporter_name"] == "Anil"
    assert row["reported_at"] == NOW
    assert row["building"] == "W-202"


def test_open_endpoint_plant_scope(auth_client, db_session):
    _seed(db_session)
    w = _flag(auth_client, "W202-0005")
    a = _flag(auth_client, "A185-0001")
    w_ids = [x["id"] for x in auth_client.get("/breakdowns/open?plant_id=W202").json()]
    assert w in w_ids and a not in w_ids
    both = [x["id"] for x in auth_client.get("/breakdowns/open?plant_id=both").json()]
    assert w in both and a in both


def test_requires_auth_401(client):
    assert client.post("/breakdowns/flag", json={
        "machine_id": "W202-0005", "operator_id": "42", "severity": "MINOR",
        "description": "x", "raised_at": NOW}).status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_breakdowns.py -q`
Expected: FAIL — endpoints/columns not updated yet (e.g. `AttributeError`/`KeyError` on `work-done`, `machine_id`, `CLOSED`).

- [ ] **Step 3: Update `app/schemas.py`**

(a) Change the `QcStatus` literal (currently around line 396) from:

```python
QcStatus = Literal["APPROVED", "DISAPPROVED"]
```
to:
```python
QcStatus = Literal["APPROVED", "REJECTED"]
```

(b) Add an optional before-photo field to `BreakdownFlagRequest` (currently around lines 496-501) so the operator's raise-time photo can be stored:

```python
class BreakdownFlagRequest(_Trimmed):
    machine_id: str                       # = mt_asset_list.asset_id
    operator_id: Optional[str] = None     # hint; backend resolves to a name
    severity: str = "MAJOR"
    description: str = ""
    before_photo_path: Optional[str] = None
    raised_at: int                        # epoch ms
```

(c) Update the `QcUpdateResponse` comment for `ticket_status` (around line 528) to the new vocabulary, and add the new work-done request model right after `QcDecideRequest` (around line 524):

```python
class BreakdownWorkDoneRequest(_Trimmed):
    """Technician submits the completed repair -> status PENDING_QC, qc_status PENDING."""
    user_id: str = ""
    user_name: str = ""
    work_done: str = ""
    after_photo_path: Optional[str] = None
    done_at: int                          # epoch ms
```

And change the `QcUpdateResponse.ticket_status` inline comment to:
```python
    ticket_status: str                    # OPEN | ACKNOWLEDGED | PENDING_QC | CLOSED | REOPENED
```

- [ ] **Step 4: Rewrite `app/api/breakdowns.py`**

Replace the ENTIRE contents of `app/api/breakdowns.py` with:

```python
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, BreakdownRecord, MtUser
from ..schemas import (
    BreakdownFlagRequest, BreakdownFlagResponse,
    QcAckRequest, QcDecideRequest, QcUpdateResponse, OpenBreakdownDto,
    BreakdownWorkDoneRequest,
)
from ..auth import get_current_user
from ..utils import to_epoch_ms, from_epoch_ms, norm_plant, building_for, ALL_BUILDINGS

router = APIRouter(tags=["breakdowns"])


# A machine is usable again only once its breakdown is CLOSED (QC approved).
def _machine_status(status: str) -> str:
    return "AVAILABLE" if status == "CLOSED" else "UNDER_BREAKDOWN"


def _ms_to_naive(ms: int):
    """epoch ms -> naive UTC datetime (the DateTime columns are tz-naive; mixing in
    tz-aware values breaks later comparisons against datetime.utcnow())."""
    return from_epoch_ms(ms).replace(tzinfo=None)


def _resolve_name(db: Session, uid: Optional[str]) -> Optional[str]:
    """mt_users.id -> name, or None if unknown/blank."""
    if uid and str(uid).isdigit():
        u = db.get(MtUser, int(uid))
        if u is not None:
            return u.name
    return None


def _get_rec(db: Session, rec_id: str) -> BreakdownRecord:
    """Fetch a breakdown row by its id (the table is single-purpose now)."""
    try:
        rid = int(rec_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="not found")
    rec = db.get(BreakdownRecord, rid)
    if rec is None:
        raise HTTPException(status_code=404, detail="not found")
    return rec


@router.post("/breakdowns/flag", response_model=BreakdownFlagResponse)
def raise_flag(
    req: BreakdownFlagRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Operator flags a machine as broken -> one OPEN row in mt_breakdown_records,
    keyed by machine_id. The machine is 'under breakdown' (Production Start blocked)
    until QC approves it (status=CLOSED)."""
    asset = db.query(MtAsset).filter(MtAsset.asset_id == req.machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")

    operator_name = _resolve_name(db, req.operator_id) or user.name
    rec = BreakdownRecord(
        machine_id=req.machine_id,
        machine_name=(asset.asset_name or "")[:255] or None,
        operator_raise_person=operator_name,
        severity=req.severity,
        description=req.description or "",
        before_photo_url=req.before_photo_path or None,
        status="OPEN",
        start_time=_ms_to_naive(req.raised_at),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return BreakdownFlagResponse(id=str(rec.id), sync_status="SYNCED")


@router.post("/breakdowns/{rec_id}/qc/acknowledge", response_model=QcUpdateResponse)
def acknowledge(
    rec_id: str,
    req: QcAckRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Technician acknowledges the breakdown -> ACKNOWLEDGED."""
    rec = _get_rec(db, rec_id)
    rec.status = "ACKNOWLEDGED"
    rec.technician = req.user_name or _resolve_name(db, req.user_id) or user.name
    rec.ackn_at = _ms_to_naive(req.acknowledged_at)
    db.commit()
    return QcUpdateResponse(
        id=str(rec.id), ticket_status=rec.status,
        machine_status=_machine_status(rec.status), qc_status=rec.qc_status,
    )


@router.post("/breakdowns/{rec_id}/work-done", response_model=QcUpdateResponse)
def work_done(
    rec_id: str,
    req: BreakdownWorkDoneRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Technician records the completed repair -> PENDING_QC (awaiting QC)."""
    rec = _get_rec(db, rec_id)
    rec.status = "PENDING_QC"
    rec.qc_status = "PENDING"
    rec.work_done_des = req.work_done or None
    if req.after_photo_path:
        rec.photo_url = req.after_photo_path
    if not rec.technician:
        rec.technician = req.user_name or _resolve_name(db, req.user_id) or user.name
    db.commit()
    return QcUpdateResponse(
        id=str(rec.id), ticket_status=rec.status,
        machine_status=_machine_status(rec.status), qc_status=rec.qc_status,
    )


@router.post("/breakdowns/{rec_id}/qc/approve", response_model=QcUpdateResponse)
def qc_approve(
    rec_id: str,
    req: QcDecideRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """QC approves the repair -> CLOSED (machine usable again)."""
    rec = _get_rec(db, rec_id)
    now = datetime.utcnow()
    rec.status = "CLOSED"
    rec.qc_status = "APPROVED"
    rec.qc_checked_by = req.user_name or _resolve_name(db, req.user_id) or user.name
    rec.end_time = _ms_to_naive(req.decided_at) if req.decided_at else now
    if req.after_photo_path and not rec.photo_url:
        rec.photo_url = req.after_photo_path
    db.commit()
    return QcUpdateResponse(
        id=str(rec.id), ticket_status=rec.status,
        machine_status=_machine_status(rec.status), qc_status=rec.qc_status,
    )


@router.post("/breakdowns/{rec_id}/qc/disapprove", response_model=QcUpdateResponse)
def qc_disapprove(
    rec_id: str,
    req: QcDecideRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """QC rejects the repair -> REOPENED (still under breakdown; needs re-work)."""
    rec = _get_rec(db, rec_id)
    rec.status = "REOPENED"
    rec.qc_status = "REJECTED"
    rec.qc_checked_by = req.user_name or _resolve_name(db, req.user_id) or user.name
    rec.qc_reject_reason = req.reason or req.notes or None
    db.commit()
    return QcUpdateResponse(
        id=str(rec.id), ticket_status=rec.status,
        machine_status=_machine_status(rec.status), qc_status=rec.qc_status,
    )


@router.get("/breakdowns/open", response_model=List[OpenBreakdownDto])
def list_open_breakdowns(
    plant_id: str = Query("both", description="W202 | A185 | both (any spelling)"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Cross-device read: every breakdown not yet CLOSED, scoped to plant. Lets a
    technician/Head on another device see open breakdowns."""
    if norm_plant(plant_id) in ("BOTH", ""):
        buildings = list(ALL_BUILDINGS)
    else:
        b = building_for(plant_id)
        buildings = [b] if b else []
    if not buildings:
        return []

    recs = (
        db.query(BreakdownRecord)
        .filter(BreakdownRecord.status != "CLOSED")
        .order_by(BreakdownRecord.start_time.desc(), BreakdownRecord.id.desc())
        .all()
    )
    if not recs:
        return []

    asset_ids = {r.machine_id for r in recs if r.machine_id}
    assets = {
        a.asset_id: a
        for a in db.query(MtAsset).filter(MtAsset.asset_id.in_(list(asset_ids))).all()
    } if asset_ids else {}

    out: List[OpenBreakdownDto] = []
    for r in recs:
        asset = assets.get(r.machine_id)
        if asset is None or asset.building not in buildings:
            continue
        out.append(OpenBreakdownDto(
            id=str(r.id),
            asset_id=r.machine_id or "",
            asset_name=asset.asset_name,
            reported_by=r.operator_raise_person,
            reporter_name=r.operator_raise_person,
            severity=r.severity,
            description=r.description or "",
            status=r.status or "OPEN",
            reported_at=to_epoch_ms(r.start_time),
            building=asset.building,
        ))
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_breakdowns.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 6: Commit (optional)**

```bash
git add app/schemas.py app/api/breakdowns.py tests/test_breakdowns.py
git commit -m "feat(breakdowns): rebuild operator workflow on the slimmed table + work-done step"
```

---

## Task 3: Point the F.06 endpoint at `mt_doc_breakdown`

**Files:**
- Modify: `app/api/breakdown_records.py`
- Test: `tests/test_breakdown_docs.py` (new)

- [ ] **Step 1: Write the new F.06 test file**

Create `tests/test_breakdown_docs.py`:

```python
"""POST /preventive-maintenance/breakdowns — CFPLA.C4.F.06 sheet -> mt_doc_breakdown
(one row per entry). Moved off mt_breakdown_records when that table was slimmed to
the live workflow."""

from app.models import BreakdownDoc

ENDPOINT = "/preventive-maintenance/breakdowns"


def test_submit_creates_one_row_per_entry(auth_client, db_session):
    body = {
        "doc_no": "CFPLA.C4.F.06",
        "verified_by": "Ravi",
        "entries": [
            {"record_date": "2026-06-22", "location": "Lower Basement",
             "machine_name": "Auto L-sealer", "problem_in_brief": "Heater coil not heating"},
            {"record_date": "2026-06-23", "machine_name": "Capper", "problem_in_brief": "Jam"},
        ],
    }
    resp = auth_client.post(ENDPOINT, json=body)
    assert resp.status_code == 201, resp.text
    ids = resp.json()["ids"]
    assert len(ids) == 2

    rows = db_session.query(BreakdownDoc).order_by(BreakdownDoc.sr_no).all()
    assert [r.sr_no for r in rows] == [1, 2]
    assert {r.id for r in rows} == set(ids)
    assert all(r.verified_by == "Ravi" for r in rows)
    assert all(r.created_by == "tester" for r in rows)
    assert rows[0].machine_name == "Auto L-sealer"
    assert rows[0].location == "Lower Basement"


def test_empty_entries_400(auth_client):
    resp = auth_client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": []})
    assert resp.status_code == 400


def test_null_record_date_ok(auth_client, db_session):
    resp = auth_client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": [{"machine_name": "X"}]})
    assert resp.status_code == 201, resp.text
    resp2 = auth_client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": [{"record_date": "", "machine_name": "Z"}]})
    assert resp2.status_code == 201, resp2.text
    rows = db_session.query(BreakdownDoc).all()
    assert len(rows) == 2
    assert all(r.record_date is None for r in rows)


def test_requires_auth_401(client):
    resp = client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": [{"machine_name": "X"}]})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_breakdown_docs.py -q`
Expected: FAIL — endpoint still writes `BreakdownRecord` with `source`/`sr_no` columns that no longer exist there (`TypeError`/`AttributeError`).

- [ ] **Step 3: Update `app/api/breakdown_records.py`**

Replace the ENTIRE contents with:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import BreakdownDoc, MtUser
from ..schemas import BreakdownSheetIn, BreakdownCreatedResponse
from ..auth import get_current_user

router = APIRouter(prefix="/preventive-maintenance", tags=["preventive-maintenance"])


@router.post(
    "/breakdowns",
    status_code=status.HTTP_201_CREATED,
    response_model=BreakdownCreatedResponse,
)
def create_breakdowns(
    sheet: BreakdownSheetIn,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Explode a CFPLA.C4.F.06 sheet into one `mt_doc_breakdown` row per entry.
    Each row carries the sheet-level `doc_no`/`verified_by`, its 1-based `sr_no`, and
    `created_by` = the logged-in user. Returns 201 {ids:[...]}."""
    if not sheet.entries:
        raise HTTPException(status_code=400, detail="entries must be non-empty")

    doc_no = sheet.doc_no or "CFPLA.C4.F.06"
    records = [
        BreakdownDoc(
            doc_no=doc_no,
            sr_no=idx + 1,
            verified_by=sheet.verified_by,
            created_by=user.username,
            **entry.model_dump(),
        )
        for idx, entry in enumerate(sheet.entries)
    ]
    db.add_all(records)
    db.flush()  # populate auto-generated ids before commit
    ids = [r.id for r in records]
    db.commit()
    return BreakdownCreatedResponse(ids=ids)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_breakdown_docs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (optional)**

```bash
git add app/api/breakdown_records.py tests/test_breakdown_docs.py
git commit -m "feat(f06): write CFPLA.C4.F.06 sheets to mt_doc_breakdown"
```

---

## Task 4: Update the Head read views

**Files:**
- Modify: `app/api/head.py`
- Test: `tests/test_head_escalations.py`

- [ ] **Step 1: Update the `_flag` helper + status values in `tests/test_head_escalations.py`**

Replace the `_flag` helper (lines 20-28) with the new-schema version:

```python
def _flag(db, asset_id, reported_at, status="OPEN", severity="MAJOR"):
    rec = BreakdownRecord(
        machine_id=asset_id, operator_raise_person="Anil",
        severity=severity, description="x", status=status, start_time=reported_at,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return str(rec.id)
```

Then in `test_escalations_excludes_qc_approved` (around line 68), change the cleared-flag status from `"QC_APPROVED"` to `"CLOSED"`:

```python
    _flag(db_session, "A185-1", now - timedelta(days=5), status="CLOSED")   # cleared
```

- [ ] **Step 2: Run the head-escalation tests to verify they fail**

Run: `python -m pytest tests/test_head_escalations.py -q`
Expected: FAIL — `head.py` still filters on `source`/reads `reported_at`/treats `QC_APPROVED` as terminal.

- [ ] **Step 3: Update `app/api/head.py`**

(a) Replace the lifecycle comment + `ACTIVE_STATUSES` (lines 20-22) with:

```python
# Breakdown lifecycle (mt_breakdown_records):
#   OPEN -> ACKNOWLEDGED -> PENDING_QC -> CLOSED | REOPENED (machine usable only at CLOSED)
ACTIVE_STATUSES = ("OPEN", "ACKNOWLEDGED", "REOPENED", "PENDING_QC")
```

(b) Delete the now-unused `_user_names` helper (lines 32-36).

(c) Replace `_flags_in_scope` (lines 39-48) with the source-free, `machine_id` version:

```python
def _flags_in_scope(db: Session, buildings, statuses=None):
    """Breakdown records whose machine sits in `buildings` (records carry machine_id,
    not a plant column, so scope is resolved through mt_asset_list)."""
    q = db.query(BreakdownRecord)
    if statuses is not None:
        q = q.filter(BreakdownRecord.status.in_(statuses))
    recs = q.all()
    assets = _assets(db, {r.machine_id for r in recs})
    keep = [r for r in recs if assets.get(r.machine_id) and assets[r.machine_id].building in buildings]
    return keep, assets
```

(d) In `head_escalations`, replace the body of the `for r in recs:` loop (lines 76-92) with `start_time`-based logic:

```python
    for r in recs:
        if r.start_time is None:
            continue
        days = (now - r.start_time).days
        tiered = _tier_for(days)
        if tiered is None:
            continue
        tier, role = tiered
        if tier < min_tier:
            continue
        a = assets.get(r.machine_id)
        out.append(EscalationItemDto(
            type="BREAKDOWN", flag_id=str(r.id), machine_id=r.machine_id or "",
            machine_name=a.asset_name if a else "", plant_id=norm_plant(a.building if a else ""),
            severity=r.severity or "", status=r.status or "", raised_at=iso_z(r.start_time),
            days_overdue=days, tier=tier, tier_role=role, proof_photo_url=r.before_photo_url,
        ))
```

(e) Replace `head_breakdowns` from the `cutoff =` line through its `return` (lines 108-128) with:

```python
    cutoff = datetime.utcnow() - timedelta(days=7)
    sel = [
        r for r in recs
        if r.status in ACTIVE_STATUSES
        or (r.status == "CLOSED" and r.end_time and r.end_time >= cutoff)
    ]
    sel.sort(key=lambda r: r.start_time or datetime.min, reverse=True)
    return [
        HeadBreakdownDto(
            id=str(r.id), machine_id=r.machine_id or "",
            machine_name=assets[r.machine_id].asset_name if assets.get(r.machine_id) else "",
            plant_id=norm_plant(assets[r.machine_id].building if assets.get(r.machine_id) else ""),
            severity=r.severity or "", status=r.status or "OPEN", description=r.description or "",
            raised_at=iso_z(r.start_time),
            acknowledged_by_name=r.technician,
            resolved_by_name=r.technician,
            qc_status=r.qc_status,
        )
        for r in sel
    ]
```

(f) Replace `head_qc` from the `recs, assets =` line through its `return` (lines 141-164) with:

```python
    recs, assets = _flags_in_scope(db, buildings)

    awaiting: List[HeadQcAwaitingDto] = []
    decided: List[HeadQcDecidedDto] = []
    for r in recs:
        a = assets.get(r.machine_id)
        nm = a.asset_name if a else ""
        pid = norm_plant(a.building if a else "")
        if r.qc_status in ("APPROVED", "REJECTED"):
            decided.append(HeadQcDecidedDto(
                flag_id=str(r.id), machine_id=r.machine_id or "", machine_name=nm, plant_id=pid,
                qc_status=r.qc_status, qc_decided_by_name=r.qc_checked_by,
                qc_decided_at=iso_z(r.end_time), qc_notes=r.qc_reject_reason,
                resolved_by_name=r.technician,
            ))
        elif r.status in ("ACKNOWLEDGED", "PENDING_QC"):
            awaiting.append(HeadQcAwaitingDto(
                flag_id=str(r.id), machine_id=r.machine_id or "", machine_name=nm, plant_id=pid,
                severity=r.severity or "", description=r.description or "",
                resolved_by_name=r.technician,
                resolved_at=None,
            ))
    return HeadQcActivityDto(awaiting=awaiting, decided=decided)
```

- [ ] **Step 4: Run the head-escalation tests to verify they pass**

Run: `python -m pytest tests/test_head_escalations.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (optional)**

```bash
git add app/api/head.py tests/test_head_escalations.py
git commit -m "refactor(head): read the slimmed breakdown table (names, start_time, CLOSED)"
```

---

## Task 5: Update the live-machine view

**Files:**
- Modify: `app/api/live.py:35-45`

- [ ] **Step 1: Update the PENDING_QC machine set in `app/api/live.py`**

Replace the `pending_qc` query (lines 35-45) with:

```python
    # Machines with a breakdown not yet CLOSED -> PENDING_QC
    # (Production Start stays blocked until QC clears the breakdown).
    pending_qc = {
        r.machine_id
        for r in db.query(BreakdownRecord.machine_id)
        .filter(BreakdownRecord.status != "CLOSED")
        .all()
    }
```

- [ ] **Step 2: Verify the app imports and the breakdown/head suites still pass**

Run: `python -c "import app.main"`
Expected: exit code 0.

Run: `python -m pytest tests/test_breakdowns.py tests/test_head_escalations.py -q`
Expected: PASS (live.py shares the model; this confirms no regression).

- [ ] **Step 3: Commit (optional)**

```bash
git add app/api/live.py
git commit -m "refactor(live): breakdown PENDING_QC set uses machine_id + CLOSED"
```

---

## Task 6: Replace the migration script with a drop-&-recreate script

**Files:**
- Create: `scripts/recreate_breakdown_tables.py`
- Delete: `scripts/migrate_breakdown_columns.py`

- [ ] **Step 1: Create `scripts/recreate_breakdown_tables.py`**

```python
"""DESTRUCTIVE — drop the old mt_breakdown_records and recreate it as the slimmed
live-workflow table, plus the new mt_doc_breakdown (F.06 paper form). Existing rows
are test data and are discarded (per the redesign spec). Run once (RDS reachable):

    python -m scripts.recreate_breakdown_tables
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from app.database import rds_engine  # noqa: E402

DDL = [
    "DROP TABLE IF EXISTS mt_breakdown_records",
    """
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
    )
    """,
    "CREATE INDEX idx_mt_breakdown_status     ON mt_breakdown_records (status)",
    "CREATE INDEX idx_mt_breakdown_machine_id ON mt_breakdown_records (machine_id)",
    """
    CREATE TABLE IF NOT EXISTS mt_doc_breakdown (
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
    )
    """,
]


def main():
    with rds_engine.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
            print("ok:", " ".join(stmt.split())[:70])
    print("done — mt_breakdown_records recreated (slim) + mt_doc_breakdown created.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Delete the obsolete migration script**

Delete `scripts/migrate_breakdown_columns.py` (it added the now-removed operator-flag columns to the old shared table).

Run: `python -c "import ast; ast.parse(open('scripts/recreate_breakdown_tables.py').read())"`
Expected: exit code 0 (the new script parses; do NOT run it here — it touches live RDS).

- [ ] **Step 3: Commit (optional)**

```bash
git add scripts/recreate_breakdown_tables.py
git rm scripts/migrate_breakdown_columns.py
git commit -m "chore(scripts): drop-&-recreate breakdown tables; remove old column migration"
```

---

## Task 7: Full suite + API contract doc

**Files:**
- Modify: `docs/API_CONTRACT_FOR_ANDROID.md`

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest -q`
Expected: PASS — all tests, including the unrelated suites. If any non-breakdown test fails, it indicates a missed reference to a removed column/value; fix the offending file using the same column/value mapping from this plan (`reported_at`→`start_time`, `asset_id`→`machine_id`, `QC_APPROVED`→`CLOSED`, `DISAPPROVED`→`REJECTED`, names instead of id lookups).

- [ ] **Step 2: Update `docs/API_CONTRACT_FOR_ANDROID.md`**

Read the file, then update the breakdown section(s) for the new behavior:
- Document `POST /breakdowns/{id}/work-done` with body `{user_id, user_name, work_done, after_photo_path?, done_at}` → returns `{id, ticket_status: "PENDING_QC", machine_status, qc_status: "PENDING", sync_status}`.
- Change documented `ticket_status` terminal value `QC_APPROVED` → `CLOSED`.
- Change documented `qc_status` value `DISAPPROVED` → `REJECTED`.
- Note that `POST /breakdowns/flag` now accepts an optional `before_photo_path`.
- Note the response field names are unchanged (`reported_at`, `reporter_name`, `asset_id`); only the status string values changed, and apps must update any `when`/`switch` on those values.

- [ ] **Step 3: Commit (optional)**

```bash
git add docs/API_CONTRACT_FOR_ANDROID.md
git commit -m "docs(contract): breakdown work-done endpoint + CLOSED/REJECTED status vocab"
```

---

## Self-Review notes (already applied)

- **Spec coverage:** Both tables (Tasks 1, 6), all callers — breakdowns/F.06/head/live (Tasks 2-5), tests (every task), contract (Task 7). The spec's "no work-done timestamp" simplification is reflected in `head_qc`'s `resolved_at=None`.
- **Type/name consistency:** New column names (`machine_id`, `start_time`, `technician`, `ackn_at`, `work_done_des`, `photo_url`, `qc_checked_by`, `qc_status`, `qc_reject_reason`, `end_time`) are used identically across models, endpoints, head.py, live.py, and tests. Status vocabulary (`OPEN/ACKNOWLEDGED/PENDING_QC/CLOSED/REOPENED`, `qc_status PENDING/APPROVED/REJECTED`) is consistent everywhere.
- **No placeholders:** every code step contains complete code.
- **Known semantic simplifications (intentional):** `resolved_by_name` maps to `technician` (same person in the slim model); `qc_decided_at` is read from `end_time` (null for rejected rows); the QC `awaiting` view's `resolved_at` is null (no work-done timestamp column).
