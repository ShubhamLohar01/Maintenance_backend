import re
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MtUser
from ..schemas import MtMachineDto, MtMachineUpdate
from ..auth import get_current_user

router = APIRouter(prefix="/mt-machines", tags=["mt-machines"])

# Roles allowed to edit the asset register. The app only shows the edit button to
# SUPERVISOR for now; HEAD/ADMIN are permitted too.
_EDIT_ROLES = {"SUPERVISOR", "HEAD", "ADMIN"}


def _parse_kw(power_load: Optional[str]) -> Optional[float]:
    """Best-effort kW from the raw 'Power/load' text, e.g. '120Watt', '4 KW'."""
    if not power_load:
        return None
    m = re.search(r"([\d.]+)\s*(kw|kilowatt|w|watt)", power_load, re.IGNORECASE)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    return val if m.group(2).lower().startswith("k") else val / 1000.0


def _to_dto(r: MtAsset) -> MtMachineDto:
    """Asset-register row -> API shape. `rated_kw` is derived from power_load (no
    stored column); the GET list and the PUT update return the same shape."""
    return MtMachineDto(
        asset_id=r.asset_id or str(r.id),
        asset_name=r.asset_name,
        building=r.building,
        sub_location=r.sub_location,
        category=r.category,
        model_no=r.model_no,
        serial_no=r.serial_no,
        power_load=r.power_load,
        rated_kw=_parse_kw(r.power_load),
        quantity=r.quantity,
        condition=r.condition,
        assigned_to=r.assigned_to,
        remarks=r.remarks,
    )


@router.get("", response_model=List[MtMachineDto])
def list_mt_machines(
    building: Optional[str] = Query(None, description="Filter on building, 'W-202' or 'A-185'"),
    category: Optional[str] = Query(None, description="Filter on category, e.g. 'Packaging', 'Production Equipment'"),
    sub_location: Optional[str] = Query(None, description="Filter on sub_location"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Return the real asset register from mt_asset_list (all fields)."""
    q = db.query(MtAsset)
    if building:
        q = q.filter(MtAsset.building == building)
    if category:
        q = q.filter(MtAsset.category == category)
    if sub_location:
        q = q.filter(MtAsset.sub_location == sub_location)
    rows = q.order_by(MtAsset.asset_id.asc()).all()
    return [_to_dto(r) for r in rows]


@router.put("/{asset_id}", response_model=MtMachineDto)
def update_mt_machine(
    asset_id: str,
    payload: MtMachineUpdate,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Update an existing mt_asset_list row by its (immutable) asset_id.

    SUPERVISOR / HEAD / ADMIN only. Full update — the app sends every editable
    field on each save, so columns are overwritten straight. rated_kw is recomputed
    from power_load (it has no stored column) and reflected in the response."""
    if user.norm_role not in _EDIT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to edit assets",
        )

    building = (payload.building or "").strip()
    asset_name = (payload.asset_name or "").strip()
    if not building or not asset_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="building and asset_name are required",
        )

    row = db.query(MtAsset).filter(MtAsset.asset_id == asset_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found",
        )

    row.building = building
    row.asset_name = asset_name
    row.category = payload.category
    row.sub_location = payload.sub_location
    row.quantity = payload.quantity
    row.model_no = payload.model_no
    row.serial_no = payload.serial_no
    row.power_load = payload.power_load
    row.condition = payload.condition
    row.remarks = payload.remarks
    db.commit()
    db.refresh(row)
    return _to_dto(row)
