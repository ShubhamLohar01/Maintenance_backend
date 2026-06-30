from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import (
    BreakdownRecord, MtAsset, MachineTransfer, PreventiveMaintenanceDoc,
)
from ..schemas import (
    EscalationItemDto, HeadBreakdownDto, HeadQcActivityDto, HeadQcAwaitingDto,
    HeadQcDecidedDto, HeadTransferDto, PmChecklistListItemDto,
)
from ..auth import get_current_user
from ..utils import iso_z, norm_plant, scoped_buildings

router = APIRouter(tags=["head"])

# Breakdown lifecycle (mt_breakdown_records):
#   OPEN -> ACKNOWLEDGED -> PENDING_QC -> CLOSED | REOPENED (machine usable only at CLOSED)
ACTIVE_STATUSES = ("OPEN", "ACKNOWLEDGED", "REOPENED", "PENDING_QC")


def _assets(db: Session, asset_ids) -> dict[str, MtAsset]:
    ids = [a for a in asset_ids if a]
    if not ids:
        return {}
    return {a.asset_id: a for a in db.query(MtAsset).filter(MtAsset.asset_id.in_(ids)).all()}


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


# Overdue escalation tiers: (min_days, tier, role). Highest-first.
ESCALATION_TIERS = [(3, 3, "HEAD"), (2, 2, "SUPERVISOR"), (1, 1, "TECHNICIAN")]


def _tier_for(days_overdue: int):
    for min_days, tier, role in ESCALATION_TIERS:
        if days_overdue >= min_days:
            return tier, role
    return None


@router.get("/head/escalations", response_model=List[EscalationItemDto])
def head_escalations(
    min_tier: int = Query(3, ge=1, le=3, description="lowest tier to include (default 3 = HEAD)"),
    db: Session = Depends(get_rds),
    user=Depends(get_current_user),
):
    """Overdue, still-unresolved operator breakdowns routed by tier (HEAD sees both
    plants). Widen with ?min_tier=1."""
    buildings = scoped_buildings(user)
    if not buildings:
        return []
    recs, assets = _flags_in_scope(db, buildings, ("OPEN", "ACKNOWLEDGED", "REOPENED"))
    now = datetime.utcnow()
    out: List[EscalationItemDto] = []
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
    out.sort(key=lambda i: i.days_overdue, reverse=True)
    return out


@router.get("/head/breakdowns", response_model=List[HeadBreakdownDto])
def head_breakdowns(
    db: Session = Depends(get_rds),
    user=Depends(get_current_user),
):
    """#2 — breakdowns across the Head's warehouses: all active plus anything
    QC_APPROVED in the last 7 days. Newest first."""
    buildings = scoped_buildings(user)
    if not buildings:
        return []
    recs, assets = _flags_in_scope(db, buildings)
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


@router.get("/head/qc", response_model=HeadQcActivityDto)
def head_qc(
    db: Session = Depends(get_rds),
    user=Depends(get_current_user),
):
    """#3 — QC activity: `awaiting` = acknowledged/pending flags with no QC decision
    yet; `decided` = flags already APPROVED/DISAPPROVED."""
    buildings = scoped_buildings(user)
    if not buildings:
        return HeadQcActivityDto(awaiting=[], decided=[])
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


@router.get("/head/checklists", response_model=List[PmChecklistListItemDto])
def head_checklists(
    db: Session = Depends(get_rds),
    user=Depends(get_current_user),
):
    """#4 — SUBMITTED preventive checklists across the Head's warehouses, newest
    first. Same shape as the preventive list endpoint (multi-plant, SUBMITTED only)."""
    buildings = scoped_buildings(user)
    if not buildings:
        return []
    scoped_norm = {norm_plant(b) for b in buildings}

    docs = (
        db.query(PreventiveMaintenanceDoc)
        .order_by(PreventiveMaintenanceDoc.created_at.desc(), PreventiveMaintenanceDoc.id.desc())
        .all()
    )
    out: List[PmChecklistListItemDto] = []
    for d in docs:
        h = d.rows if isinstance(d.rows, dict) else {}
        if str(h.get("status", "SUBMITTED")) != "SUBMITTED":
            continue
        plant = norm_plant(h.get("plant_id"))
        if plant and plant not in scoped_norm:
            continue
        out.append(PmChecklistListItemDto(
            id=d.id,
            form_type=str(h.get("form_type", "")),
            doc_no=str(h.get("doc_no", "")),
            status="SUBMITTED",
            checklist_date=str(h.get("checklist_date", d.month or "")),
            done_by=str(h.get("done_by", d.created_by or "")),
            created_at=iso_z(d.created_at) or "",
        ))
    return out


@router.get("/head/transfers", response_model=List[HeadTransferDto])
def head_transfers(
    db: Session = Depends(get_rds),
    user=Depends(get_current_user),
):
    """#6 — machine transfers touching the Head's warehouses (either end), newest first."""
    buildings = scoped_buildings(user)
    if not buildings:
        return []
    scoped_norm = {norm_plant(b) for b in buildings}

    rows = (
        db.query(MachineTransfer)
        .order_by(MachineTransfer.created_at.desc(), MachineTransfer.id.desc())
        .all()
    )
    out: List[HeadTransferDto] = []
    for r in rows:
        if norm_plant(r.from_warehouse) not in scoped_norm and norm_plant(r.to_warehouse) not in scoped_norm:
            continue
        out.append(HeadTransferDto(
            id=r.id,
            date=r.transfer_date.isoformat() if r.transfer_date else "",
            from_warehouse=r.from_warehouse,
            to_warehouse=r.to_warehouse,
            machine_name=r.machine_name,
            condition=r.condition,
            created_by=r.created_by,
            created_at=iso_z(r.created_at),
            proof_photo_url=r.proof_photo_url,
        ))
    return out
