from datetime import date, datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import PreventiveMaintenanceDoc, MtUser
from ..schemas import (
    PmChecklistRequest, PmChecklistCreatedResponse,
    PmChecklistListItemDto, PmChecklistDetailItemDto, PmChecklistDetailDto,
)
from ..auth import get_current_user

router = APIRouter(prefix="/preventive-maintenance", tags=["preventive-maintenance"])


def _iso_z(dt: datetime | None) -> str:
    """Naive-UTC datetime -> ISO 8601 with a trailing Z, e.g. 2026-06-20T11:30:00Z."""
    if dt is None:
        return ""
    return dt.replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _header_and_items(doc: PreventiveMaintenanceDoc):
    """The `rows` JSONB comes in two shapes:
      - app-created: a dict {form_type, doc_no, ..., items: [...]}
      - legacy:      a bare list of item dicts (header lives in scalar columns)
    Return (header_dict, items_list) for either shape so reads never crash."""
    raw = doc.rows
    if isinstance(raw, dict):
        return raw, (raw.get("items") or [])
    if isinstance(raw, list):
        return {}, raw
    return {}, []


def _validate_and_payload(req: PmChecklistRequest, user: MtUser) -> dict:
    """Validate per record-status and build the JSONB payload.

    DRAFT     -> lenient: UNSET items and blank header fields are allowed.
    SUBMITTED -> items must be OK/NOT_OK (no UNSET) and checklist_date a real date.
    `created_by` is always the logged-in user (authoritative, not client-supplied)."""
    if not req.items:
        raise HTTPException(status_code=400, detail="items must be non-empty")
    if req.status == "SUBMITTED":
        if any(it.status == "UNSET" for it in req.items):
            raise HTTPException(
                status_code=400,
                detail="a SUBMITTED checklist cannot contain UNSET items",
            )
        try:
            date.fromisoformat(req.checklist_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="checklist_date must be ISO date YYYY-MM-DD",
            )
    return {
        "form_type": req.form_type,
        "doc_no": req.doc_no,
        "status": req.status,
        "checklist_date": req.checklist_date,
        "done_by": req.done_by,
        "checked_by": req.checked_by,
        "verified_by": req.verified_by,
        "remarks": req.remarks or "",
        "created_by": user.username,
        "plant_id": user.plant_id,
        "items": [item.model_dump() for item in req.items],
    }


@router.post(
    "/checklists",
    status_code=status.HTTP_201_CREATED,
    response_model=PmChecklistCreatedResponse,
)
def create_checklist(
    req: PmChecklistRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Create a PM checklist (DRAFT or SUBMITTED) as one JSONB document row.
    Returns 201 with the new id. Validation errors come back as JSON 4xx."""
    payload = _validate_and_payload(req, user)
    doc = PreventiveMaintenanceDoc(
        month=(req.checklist_date or "")[:7],   # YYYY-MM, fits the existing month column
        checked_by=req.checked_by,
        verified_by=req.verified_by,
        created_by=user.username,
        rows=payload,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return PmChecklistCreatedResponse(id=doc.id)


@router.put("/checklists/{checklist_id}", response_model=PmChecklistCreatedResponse)
def update_checklist(
    checklist_id: int,
    req: PmChecklistRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Replace a checklist's header + items — used for subsequent draft saves and
    for finalizing (send status=SUBMITTED). Returns 200 {id}; 404 JSON if unknown."""
    doc = db.get(PreventiveMaintenanceDoc, checklist_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    payload = _validate_and_payload(req, user)
    doc.rows = payload
    doc.month = (req.checklist_date or "")[:7]
    doc.checked_by = req.checked_by
    doc.verified_by = req.verified_by
    doc.created_by = user.username
    db.add(doc)
    db.commit()
    return PmChecklistCreatedResponse(id=doc.id)


@router.get("/checklists", response_model=List[PmChecklistListItemDto])
def list_checklists(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All stored PM checklists, newest first (empty array if none). Header
    fields are read from the stored `rows` JSONB document."""
    docs = (
        db.query(PreventiveMaintenanceDoc)
        .order_by(
            PreventiveMaintenanceDoc.created_at.desc(),
            PreventiveMaintenanceDoc.id.desc(),
        )
        .all()
    )
    out: List[PmChecklistListItemDto] = []
    for d in docs:
        h, _ = _header_and_items(d)
        out.append(PmChecklistListItemDto(
            id=d.id,
            form_type=str(h.get("form_type", "")),
            doc_no=str(h.get("doc_no", "")),
            status=str(h.get("status", "SUBMITTED")),
            checklist_date=str(h.get("checklist_date", d.month or "")),
            done_by=str(h.get("done_by", d.created_by or "")),
            created_at=_iso_z(d.created_at),
        ))
    return out


@router.get("/checklists/{checklist_id}", response_model=PmChecklistDetailDto)
def get_checklist(
    checklist_id: int,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """One PM checklist with its full items[]. 404 JSON for an unknown id."""
    doc = db.get(PreventiveMaintenanceDoc, checklist_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")

    h, raw_items = _header_and_items(doc)
    items: List[PmChecklistDetailItemDto] = []
    for it in raw_items:
        it = it if isinstance(it, dict) else {}
        items.append(PmChecklistDetailItemDto(
            section=str(it.get("section", "")),
            equipment=str(it.get("equipment", "")),
            sr_no=it.get("sr_no") if isinstance(it.get("sr_no"), int) else None,
            equipment_date=str(it.get("equipment_date", "")),
            checkpoint=str(it.get("checkpoint", "")),
            status=str(it.get("status", "")),
            remarks=str(it.get("remarks", "")),
        ))
    return PmChecklistDetailDto(
        id=doc.id,
        form_type=str(h.get("form_type", "")),
        doc_no=str(h.get("doc_no", "")),
        status=str(h.get("status", "SUBMITTED")),
        checklist_date=str(h.get("checklist_date", doc.month or "")),
        done_by=str(h.get("done_by", doc.created_by or "")),
        checked_by=str(h.get("checked_by") or doc.checked_by or ""),
        verified_by=str(h.get("verified_by") or doc.verified_by or ""),
        remarks=str(h.get("remarks", "")),
        created_at=_iso_z(doc.created_at),
        items=items,
    )
