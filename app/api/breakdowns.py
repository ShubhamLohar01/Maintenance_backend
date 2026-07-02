from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, BreakdownRecord, MtUser
from ..schemas import (
    BreakdownFlagResponse,
    QcAckRequest, QcDecideRequest, QcUpdateResponse, OpenBreakdownDto,
)
from ..auth import get_current_user
from ..storage import upload_bytes, image_ext_for
from ..utils import to_epoch_ms, from_epoch_ms, norm_plant, building_for, ALL_BUILDINGS, is_shut_down

router = APIRouter(tags=["breakdowns"])

MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


async def _upload_photo(photo: Optional[UploadFile], key: str) -> Optional[str]:
    """Validate + upload an optional image part to S3, returning its public URL
    (None when no photo was attached). Mirrors the machine-transfer photo flow:
    type/size are checked here so the client gets a clear 400, and the upload runs
    before the DB commit so a failed upload rolls back the row (no orphan record
    pointing at a missing object). `key` is the S3 object key WITHOUT extension."""
    if photo is None or not (photo.filename or "").strip():
        return None
    content_type = (photo.content_type or "").strip().lower()
    ext = image_ext_for(content_type)
    if ext is None:
        raise HTTPException(status_code=400, detail="photo must be image/jpeg or image/png")
    data = await photo.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="photo must be <= 10 MB")
    if not data:
        return None  # empty part -> treat as no photo
    return upload_bytes(f"{key}.{ext}", data, content_type)


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
async def raise_flag(
    machine_id: str = Form(...),
    operator_id: Optional[str] = Form(None),
    severity: str = Form("MAJOR"),
    description: str = Form(""),
    raised_at: int = Form(...),                       # epoch ms
    before_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Operator flags a machine as broken -> one OPEN row in mt_breakdown_records,
    keyed by machine_id. The machine is 'under breakdown' (Production Start blocked)
    until QC approves it (status=CLOSED).

    multipart/form-data: an optional `before_photo` image part is uploaded to S3 and
    its URL stored in `before_photo_url` (mirrors the work-done / machine-transfer
    photo flow). The upload runs before commit, so a failed upload rolls back the row."""
    asset = db.query(MtAsset).filter(MtAsset.asset_id == machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")
    if is_shut_down(asset.condition):
        raise HTTPException(status_code=409, detail="Machine is shut down")

    operator_name = _resolve_name(db, operator_id) or user.name
    rec = BreakdownRecord(
        machine_id=machine_id,
        machine_name=(asset.asset_name or "")[:255] or None,
        operator_raise_person=operator_name,
        severity=severity,
        description=(description or "").strip(),
        status="OPEN",
        start_time=_ms_to_naive(raised_at),
    )
    db.add(rec)
    db.flush()  # assign rec.id inside the transaction (used in the S3 object key)

    photo_url = await _upload_photo(before_photo, f"breakdowns/{rec.id}/before")
    if photo_url:
        rec.before_photo_url = photo_url

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
    """Dual-purpose. Technician acknowledges the breakdown -> ACKNOWLEDGED (ackn_at).
    QC 'pickup' of an awaiting-QC ticket sends `qc_checked_by`: that path only stamps
    qc_acknowledged_at + qc_checked_by and DOES NOT change status or ackn_at — the
    ticket stays PENDING_QC through QC review (the old flip back to ACKNOWLEDGED,
    which also clobbered the technician's ackn_at, was a bug)."""
    rec = _get_rec(db, rec_id)
    if req.qc_checked_by:
        rec.qc_checked_by = req.qc_checked_by
        rec.qc_acknowledged_at = _ms_to_naive(req.acknowledged_at)
    else:
        rec.status = "ACKNOWLEDGED"
        rec.technician = req.user_name or _resolve_name(db, req.user_id) or user.name
        rec.ackn_at = _ms_to_naive(req.acknowledged_at)
    db.commit()
    return QcUpdateResponse(
        id=str(rec.id), ticket_status=rec.status,
        machine_status=_machine_status(rec.status), qc_status=rec.qc_status,
    )


@router.post("/breakdowns/{rec_id}/work-done", response_model=QcUpdateResponse)
async def work_done(
    rec_id: str,
    user_id: str = Form(""),
    user_name: str = Form(""),
    work_done: str = Form(""),
    done_at: int = Form(...),                         # epoch ms
    after_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Technician records the completed repair -> PENDING_QC (awaiting QC).

    multipart/form-data: the `after_photo` image part is uploaded to S3 and its URL
    stored in `photo_url` (NOT a device-local file path). The upload runs before
    commit, so a failed upload rolls back the row (work_done_des won't persist
    without its photo)."""
    rec = _get_rec(db, rec_id)
    rec.status = "PENDING_QC"
    rec.qc_status = "PENDING"
    rec.resolved_at = _ms_to_naive(done_at)           # repair finished (was discarded)
    rec.work_done_des = (work_done or "").strip() or None
    if not rec.technician:
        rec.technician = user_name or _resolve_name(db, user_id) or user.name

    photo_url = await _upload_photo(after_photo, f"breakdowns/{rec.id}/after")
    if photo_url:
        rec.photo_url = photo_url

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
    rec.qc_decided_at = _ms_to_naive(req.decided_at) if req.decided_at else now
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
    """QC rejects the repair -> back to OPEN so the SAME technician picks it up again
    (reappears in GET /breakdowns/open). `technician` is kept (whose ticket this was);
    machine stays under breakdown until a later approve sets CLOSED."""
    rec = _get_rec(db, rec_id)
    rec.status = "OPEN"
    rec.qc_status = "DISAPPROVED"
    rec.qc_checked_by = req.user_name or _resolve_name(db, req.user_id) or user.name
    rec.qc_reject_reason = req.reason or req.notes or None
    rec.qc_decided_at = _ms_to_naive(req.decided_at) if req.decided_at else datetime.utcnow()
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
            acknowledged_at=to_epoch_ms(r.ackn_at),
            resolved_at=to_epoch_ms(r.resolved_at),
            qc_acknowledged_at=to_epoch_ms(r.qc_acknowledged_at),
            qc_decided_at=to_epoch_ms(r.qc_decided_at),
            building=asset.building,
            qc_reject_reason=r.qc_reject_reason,
        ))
    return out
