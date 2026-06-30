from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import BreakdownDoc, MtUser
from ..schemas import BreakdownSheetIn, BreakdownCreatedResponse, BreakdownRecordDto
from ..auth import get_current_user
from ..utils import iso_z

router = APIRouter(prefix="/preventive-maintenance", tags=["preventive-maintenance"])


def _s(v) -> str:
    return v if v is not None else ""


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


@router.get("/breakdowns", response_model=List[BreakdownRecordDto])
def list_breakdowns(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Read-back of stored F.06 rows (one per entry), newest first. [] when empty.
    Mirrors GET /preventive-maintenance/checklists."""
    rows = (
        db.query(BreakdownDoc)
        .order_by(BreakdownDoc.created_at.desc(), BreakdownDoc.id.desc())
        .all()
    )
    return [
        BreakdownRecordDto(
            id=r.id,
            doc_no=_s(r.doc_no),
            record_date=r.record_date.isoformat() if r.record_date else "",
            location=_s(r.location),
            machine_name=_s(r.machine_name),
            equipment_model_no=_s(r.equipment_model_no),
            problem_in_brief=_s(r.problem_in_brief),
            type_of_maintenance=_s(r.type_of_maintenance),
            part_of_machine=_s(r.part_of_machine),
            temporary_reason=_s(r.temporary_reason),
            duration_start=_s(r.duration_start),
            duration_end=_s(r.duration_end),
            machine_operator_sign=_s(r.machine_operator_sign),
            maintenance_person_sign=_s(r.maintenance_person_sign),
            qc_clearance_sign=_s(r.qc_clearance_sign),
            verified_by=_s(r.verified_by),
            created_at=iso_z(r.created_at) or "",
        )
        for r in rows
    ]
