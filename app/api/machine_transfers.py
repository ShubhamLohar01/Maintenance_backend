from datetime import date as date_cls, datetime
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status, Form, File, UploadFile,
)
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MachineTransfer, MtUser
from ..schemas import MachineTransferCreatedResponse, MachineTransferListItemDto
from ..auth import get_current_user
from ..storage import upload_bytes, image_ext_for

router = APIRouter(prefix="/machine-transfers", tags=["machine-transfers"])

MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


def _iso_z(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MachineTransferCreatedResponse)
async def create_machine_transfer(
    from_warehouse: Optional[str] = Form(None),
    to_warehouse: Optional[str] = Form(None),
    machine_name: Optional[str] = Form(None),
    date: Optional[str] = Form(None),          # ISO yyyy-MM-dd; defaults to today
    machine_code: Optional[str] = Form(None),
    condition: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
    authorised_person: Optional[str] = Form(None),
    remarks: Optional[str] = Form(None),
    proof_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Record one machine transfer (multipart/form-data) with an optional proof
    photo. Required: from_warehouse, to_warehouse, machine_name (and they must
    differ). created_by is taken from the JWT. 201 -> {id, proof_photo_url}."""
    fw = (from_warehouse or "").strip()
    tw = (to_warehouse or "").strip()
    mn = (machine_name or "").strip()
    if not fw or not tw or not mn:
        raise HTTPException(
            status_code=400,
            detail="from_warehouse, to_warehouse and machine_name are required",
        )
    if fw.casefold() == tw.casefold():
        raise HTTPException(
            status_code=400,
            detail="from_warehouse and to_warehouse must differ",
        )

    # date — optional; default to today (UTC) if absent/blank
    transfer_date = datetime.utcnow().date()
    if date and date.strip():
        try:
            transfer_date = date_cls.fromisoformat(date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be ISO yyyy-MM-dd")

    # photo — optional; validate type + size if present
    photo_bytes: Optional[bytes] = None
    photo_ext: Optional[str] = None
    photo_ct: str = ""
    if proof_photo is not None and (proof_photo.filename or "").strip():
        photo_ct = (proof_photo.content_type or "").strip().lower()
        photo_ext = image_ext_for(photo_ct)
        if photo_ext is None:
            raise HTTPException(status_code=400, detail="proof_photo must be image/jpeg or image/png")
        photo_bytes = await proof_photo.read()
        if len(photo_bytes) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=400, detail="proof_photo must be <= 10 MB")
        if not photo_bytes:
            photo_bytes = None  # empty part -> treat as no photo

    doc = MachineTransfer(
        transfer_date=transfer_date,
        from_warehouse=fw,
        to_warehouse=tw,
        machine_name=mn,
        machine_code=_clean(machine_code),
        condition=_clean(condition),
        reason=_clean(reason),
        authorised_person=_clean(authorised_person),
        remarks=_clean(remarks),
        created_by=user.username,
    )
    db.add(doc)
    db.flush()  # assign doc.id inside the transaction (for the S3 key)

    proof_photo_url: Optional[str] = None
    if photo_bytes:
        # Upload before commit: if S3 fails the request errors out and the row is
        # rolled back (no orphan transfer without its proof).
        proof_photo_url = upload_bytes(
            f"machine-transfers/{doc.id}.{photo_ext}", photo_bytes, photo_ct
        )
        doc.proof_photo_url = proof_photo_url

    db.commit()
    return MachineTransferCreatedResponse(id=doc.id, proof_photo_url=proof_photo_url)


@router.get("", response_model=List[MachineTransferListItemDto])
def list_machine_transfers(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All machine transfers, newest first (empty array if none)."""
    rows = (
        db.query(MachineTransfer)
        .order_by(MachineTransfer.created_at.desc(), MachineTransfer.id.desc())
        .all()
    )
    return [
        MachineTransferListItemDto(
            id=r.id,
            date=r.transfer_date.isoformat() if r.transfer_date else "",
            from_warehouse=r.from_warehouse,
            to_warehouse=r.to_warehouse,
            machine_name=r.machine_name,
            condition=r.condition,
            created_at=_iso_z(r.created_at),
            proof_photo_url=r.proof_photo_url,
        )
        for r in rows
    ]
