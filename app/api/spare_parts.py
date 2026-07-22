"""Spare Parts (W-202) — browse stock (machine -> parts -> quantity on hand)
and log use/restock actions against it.

mt_202_spareparts is pre-existing, W-202 only. machine_name is free text, NOT a
foreign key into mt_asset_list — matched_assets is a best-effort case-insensitive
substring match, computed here; empty when nothing matches (most machine_name
values today have no match — see the design doc). Every use/restock is logged
to mt_202_spareparts_log (no dedicated history screen yet, but the data is
captured from day one for future traceability).
"""
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MtSparePart, MtSparePartLog, MtUser
from ..schemas import (
    MatchedAssetDto, SparePartDto, SparePartsMachineDto, SparePartsResponse,
    SparePartActionRequest,
)
from ..auth import get_current_user

router = APIRouter(prefix="/spare-parts", tags=["spare-parts"])


def _matched_assets(db: Session, machine_names: set) -> Dict[str, List[MatchedAssetDto]]:
    """Distinct machine_name -> best-effort matched (asset_id, asset_name) pairs
    in W-202. [] for a name (or the "" / unassigned bucket) with no match."""
    out: Dict[str, List[MatchedAssetDto]] = {}
    for name in machine_names:
        if not name:
            out[name] = []
            continue
        rows = (
            db.query(MtAsset)
            .filter(MtAsset.building == "W-202", MtAsset.asset_name.ilike(f"%{name}%"))
            .order_by(MtAsset.asset_name.asc())
            .all()
        )
        out[name] = [MatchedAssetDto(asset_id=a.asset_id or "", asset_name=a.asset_name) for a in rows]
    return out


def _part_dto(row: MtSparePart) -> SparePartDto:
    parts = row.parts_name or {}
    return SparePartDto(id=row.id, part_name=parts.get("name") or "", unit=parts.get("unit"), quantity=row.quantity)


def _get_part(db: Session, part_id: int) -> MtSparePart:
    row = db.get(MtSparePart, part_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"spare part {part_id} not found")
    return row


def _log_action(db: Session, row: MtSparePart, action: str, req: SparePartActionRequest, user: MtUser) -> None:
    parts = row.parts_name or {}
    db.add(MtSparePartLog(
        spare_part_id=row.id,
        machine_name=row.machine_name,
        part_name=parts.get("name"),
        action=action,
        quantity=req.quantity,
        note=req.note,
        performed_by=user.username,
        performed_by_name=user.name,
    ))


@router.get("", response_model=SparePartsResponse)
def list_spare_parts(db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user)):
    """Every machine's spare parts + quantity on hand, in one response (small
    enough — 113 rows total — that pagination isn't needed)."""
    rows = db.query(MtSparePart).order_by(MtSparePart.machine_name.asc(), MtSparePart.id.asc()).all()

    grouped: Dict[str, List[MtSparePart]] = {}
    for r in rows:
        grouped.setdefault(r.machine_name or "", []).append(r)

    matched = _matched_assets(db, set(grouped))
    machines = [
        SparePartsMachineDto(machine_name=name, matched_assets=matched.get(name, []), parts=[_part_dto(r) for r in parts])
        for name, parts in sorted(grouped.items())
    ]
    return SparePartsResponse(machines=machines)


@router.post("/{part_id}/use", response_model=SparePartDto)
def use_spare_part(
    part_id: int, req: SparePartActionRequest,
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Log usage and atomically decrement quantity. 400 if quantity isn't a
    positive number, or if it exceeds what's on hand (checked in the same
    conditional UPDATE — no separate check-then-write race window)."""
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be a positive number")
    row = _get_part(db, part_id)

    result = db.execute(
        update(MtSparePart)
        .where(MtSparePart.id == part_id, MtSparePart.quantity >= req.quantity)
        .values(quantity=MtSparePart.quantity - req.quantity)
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"not enough stock: {row.quantity} on hand")

    _log_action(db, row, "USE", req, user)
    db.commit()
    db.refresh(row)
    return _part_dto(row)


@router.post("/{part_id}/restock", response_model=SparePartDto)
def restock_spare_part(
    part_id: int, req: SparePartActionRequest,
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Log a restock and atomically increment quantity. 400 if quantity isn't
    a positive number."""
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be a positive number")
    row = _get_part(db, part_id)

    db.execute(
        update(MtSparePart)
        .where(MtSparePart.id == part_id)
        .values(quantity=MtSparePart.quantity + req.quantity)
    )
    _log_action(db, row, "RESTOCK", req, user)
    db.commit()
    db.refresh(row)
    return _part_dto(row)
