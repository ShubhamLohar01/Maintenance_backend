from datetime import date as date_cls, datetime
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status, Form, File, UploadFile,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MachineTransfer, MtUser, MtAsset
from ..schemas import (
    MachineTransferCreatedResponse, MachineTransferListItemDto, MachineTransferEditRequest,
)
from ..auth import get_current_user
from ..storage import upload_bytes, image_ext_for
from ..utils import norm_plant, building_for

router = APIRouter(prefix="/machine-transfers", tags=["machine-transfers"])

MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


def _iso_z(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


def _pending_transfer_exists(
    db: Session, asset_id: Optional[str], machine_name: str, exclude_id: Optional[int] = None
) -> bool:
    """True when this machine is already mid-transfer — a PENDING row not yet
    acknowledged. Keyed on asset_id when a register row was picked (precise); else on
    the case-insensitive name so a hand-typed duplicate is still caught. `exclude_id`
    skips a row (used on edit so a transfer doesn't clash with itself)."""
    q = db.query(MachineTransfer).filter(MachineTransfer.status == "PENDING")
    if exclude_id is not None:
        q = q.filter(MachineTransfer.id != exclude_id)
    if asset_id:
        return q.filter(MachineTransfer.machine_id == asset_id).first() is not None
    return q.filter(func.lower(MachineTransfer.machine_name) == (machine_name or "").lower()).first() is not None


def _set_asset_building(db: Session, asset_id: Optional[str], warehouse: str) -> None:
    """Point a specific register row's `building` at `warehouse` (compact/hyphenated
    both accepted). No-op when there's no asset_id (hand-typed transfer) or the
    warehouse is unrecognised. Used to revert/re-apply the move on edit + delete."""
    if not asset_id:
        return
    dest = building_for(warehouse)
    if not dest:
        return
    a = db.query(MtAsset).filter(MtAsset.asset_id == asset_id).first()
    if a is not None:
        a.building = dest


def _can_edit(user: MtUser, row: MachineTransfer) -> bool:
    """Only the creator may edit/delete, and only while the transfer is still PENDING
    (once the destination has acknowledged it's locked, so the register stays truthful)."""
    return row.created_by == user.username and (row.status or "PENDING") != "APPROVED"


def _move_asset_building(
    db: Session, *, asset_id: Optional[str], machine_name: str,
    from_wh: str, to_wh: str,
) -> Optional[str]:
    """Follow the physical move in the asset register: set the transferred asset's
    `building` to the destination warehouse in mt_asset_list.

    Matches by `asset_id` when the app sent one (precise). Otherwise falls back to a
    UNIQUE `asset_name` match within the SOURCE warehouse and does nothing when that
    is ambiguous (0 or >1 rows) — so a repeated name can never move the wrong asset.
    Returns the asset_id actually moved, or None if nothing matched. Runs inside the
    caller's transaction, so it commits/rolls back atomically with the transfer."""
    dest = building_for(to_wh)
    if not dest:
        return None
    target = None
    if asset_id:
        target = db.query(MtAsset).filter(MtAsset.asset_id == asset_id).first()
    if target is None and machine_name:
        src = building_for(from_wh)
        q = db.query(MtAsset).filter(func.lower(MtAsset.asset_name) == machine_name.lower())
        if src:
            q = q.filter(MtAsset.building == src)
        rows = q.all()
        if len(rows) == 1:
            target = rows[0]
    if target is None:
        return None
    target.building = dest
    return target.asset_id


def _can_acknowledge(user: MtUser, to_warehouse: str, status: str) -> bool:
    """Who may acknowledge receipt of a transfer:
    - SUPERVISOR: any transfer.
    - TECHNICIAN: only transfers whose DESTINATION warehouse is their own plant
      (they confirm the machine actually arrived at their warehouse).
    Already-APPROVED rows are never re-acknowledgeable. HEAD is view-only here."""
    if (status or "PENDING") == "APPROVED":
        return False
    role = user.norm_role
    if role == "SUPERVISOR":
        return True
    if role == "TECHNICIAN":
        own = building_for(getattr(user, "plant_id", None))
        return own is not None and norm_plant(own) == norm_plant(to_warehouse or "")
    return False


def _to_list_dto(r: MachineTransfer, user: MtUser) -> MachineTransferListItemDto:
    status = r.status or "PENDING"
    return MachineTransferListItemDto(
        id=r.id,
        date=r.transfer_date.isoformat() if r.transfer_date else "",
        from_warehouse=r.from_warehouse,
        to_warehouse=r.to_warehouse,
        machine_name=r.machine_name,
        condition=r.condition,
        machine_code=r.machine_code,
        reason=r.reason,
        authorised_person=r.authorised_person,
        remarks=r.remarks,
        created_at=_iso_z(r.created_at),
        proof_photo_url=r.proof_photo_url,
        machine_id=r.machine_id,
        status=status,
        acknowledged_by=r.acknowledged_by,
        acknowledged_at=_iso_z(r.acknowledged_at) if r.acknowledged_at else None,
        can_acknowledge=_can_acknowledge(user, r.to_warehouse, status),
        can_edit=_can_edit(user, r),
    )


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
    asset_id: Optional[str] = Form(None),     # register key: moves this asset's building
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

    # A machine already awaiting acknowledgement can't be transferred again until
    # the receiving warehouse confirms receipt (status -> APPROVED).
    aid = _clean(asset_id)
    if _pending_transfer_exists(db, aid, mn):
        raise HTTPException(
            status_code=409,
            detail="This machine already has a pending transfer awaiting acknowledgement.",
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
        machine_id=aid,
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

    # Follow the physical move in the asset register (atomic with the transfer).
    moved_id = _move_asset_building(db, asset_id=aid, machine_name=mn, from_wh=fw, to_wh=tw)
    # Remember exactly which register row we moved (even a name-matched one) so a later
    # edit/delete can revert it precisely.
    if doc.machine_id is None and moved_id:
        doc.machine_id = moved_id

    db.commit()
    return MachineTransferCreatedResponse(id=doc.id, proof_photo_url=proof_photo_url)


@router.get("", response_model=List[MachineTransferListItemDto])
def list_machine_transfers(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All machine transfers, newest first (empty array if none). `can_acknowledge`
    is computed per row for the calling user (see _can_acknowledge)."""
    rows = (
        db.query(MachineTransfer)
        .order_by(MachineTransfer.created_at.desc(), MachineTransfer.id.desc())
        .all()
    )
    return [_to_list_dto(r, user) for r in rows]


@router.post("/{transfer_id}/acknowledge", response_model=MachineTransferListItemDto)
def acknowledge_machine_transfer(
    transfer_id: int,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Receiving warehouse confirms the machine arrived -> status PENDING -> APPROVED.
    Allowed for a SUPERVISOR (any) or a TECHNICIAN whose plant == the transfer's
    destination. Idempotent: re-acknowledging an APPROVED row returns it unchanged."""
    row = db.get(MachineTransfer, transfer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transfer not found")

    current = row.status or "PENDING"
    if current != "APPROVED":
        if not _can_acknowledge(user, row.to_warehouse, current):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the destination warehouse (its technician) or a supervisor "
                       "can acknowledge this transfer",
            )
        row.status = "APPROVED"
        row.acknowledged_by = user.name
        row.acknowledged_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
    return _to_list_dto(row, user)


@router.put("/{transfer_id}", response_model=MachineTransferListItemDto)
def edit_machine_transfer(
    transfer_id: int,
    payload: MachineTransferEditRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Edit a still-PENDING transfer (creator only). If from/to/machine change, the
    asset-register move is reverted and re-applied. The proof photo is not editable here."""
    row = db.get(MachineTransfer, transfer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if row.created_by != user.username:
        raise HTTPException(status_code=403, detail="Only the person who created this transfer can edit it")
    if (row.status or "PENDING") == "APPROVED":
        raise HTTPException(status_code=409, detail="An acknowledged transfer can't be edited")

    fw = (payload.from_warehouse if payload.from_warehouse is not None else row.from_warehouse or "").strip()
    tw = (payload.to_warehouse if payload.to_warehouse is not None else row.to_warehouse or "").strip()
    mn = (payload.machine_name if payload.machine_name is not None else row.machine_name or "").strip()
    if not fw or not tw or not mn:
        raise HTTPException(status_code=400, detail="from_warehouse, to_warehouse and machine_name are required")
    if fw.casefold() == tw.casefold():
        raise HTTPException(status_code=400, detail="from_warehouse and to_warehouse must differ")

    new_aid = _clean(payload.asset_id) if payload.asset_id is not None else row.machine_id
    if _pending_transfer_exists(db, new_aid, mn, exclude_id=row.id):
        raise HTTPException(status_code=409, detail="This machine already has another pending transfer.")

    transfer_date = row.transfer_date
    if payload.date is not None:
        d = (payload.date or "").strip()
        if not d:
            transfer_date = None
        else:
            try:
                transfer_date = date_cls.fromisoformat(d)
            except ValueError:
                raise HTTPException(status_code=400, detail="date must be ISO yyyy-MM-dd")

    # revert the OLD register move (asset back to its old source), then apply the new one
    _set_asset_building(db, row.machine_id, row.from_warehouse)
    moved_id = _move_asset_building(db, asset_id=new_aid, machine_name=mn, from_wh=fw, to_wh=tw)

    row.from_warehouse = fw
    row.to_warehouse = tw
    row.machine_name = mn
    row.machine_id = new_aid or moved_id
    row.transfer_date = transfer_date
    if payload.machine_code is not None:
        row.machine_code = _clean(payload.machine_code)
    if payload.condition is not None:
        row.condition = _clean(payload.condition)
    if payload.reason is not None:
        row.reason = _clean(payload.reason)
    if payload.authorised_person is not None:
        row.authorised_person = _clean(payload.authorised_person)
    if payload.remarks is not None:
        row.remarks = _clean(payload.remarks)

    db.commit()
    db.refresh(row)
    return _to_list_dto(row, user)


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine_transfer(
    transfer_id: int,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Delete a still-PENDING transfer (creator only) and revert the asset back to its
    source warehouse in the register."""
    row = db.get(MachineTransfer, transfer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if row.created_by != user.username:
        raise HTTPException(status_code=403, detail="Only the person who created this transfer can delete it")
    if (row.status or "PENDING") == "APPROVED":
        raise HTTPException(status_code=409, detail="An acknowledged transfer can't be deleted")

    _set_asset_building(db, row.machine_id, row.from_warehouse)  # undo the move
    db.delete(row)
    db.commit()
    return None
