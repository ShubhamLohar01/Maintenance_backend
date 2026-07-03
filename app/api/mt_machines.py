import re
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MtUser
from ..schemas import MtMachineDto, MtMachineUpdate, MtMachineCreate
from ..auth import get_current_user
from ..utils import norm_plant

router = APIRouter(prefix="/mt-machines", tags=["mt-machines"])

# Roles allowed to edit the asset register. The app only shows the edit button to
# SUPERVISOR for now; HEAD/ADMIN are permitted too.
_EDIT_ROLES = {"SUPERVISOR", "HEAD", "ADMIN"}
# Roles allowed to add a new asset (the app now shows "Add machine" to these).
# OPERATOR is excluded.
_CREATE_ROLES = {"SUPERVISOR", "HEAD", "TECHNICIAN", "ADMIN"}


def _next_asset_id(db: Session, building: str) -> str:
    """Next building-prefixed asset id, e.g. 'W202-0008' — one past the highest
    existing NNNN for that building's prefix (norm_plant('W-202') -> 'W202'). Ids
    that don't match the prefix-NNNN shape are ignored; starts at 0001."""
    prefix = norm_plant(building) or "AST"
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    max_n = 0
    for (aid,) in db.query(MtAsset.asset_id).filter(MtAsset.asset_id.like(f"{prefix}-%")).all():
        m = pat.match(aid or "")
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}-{max_n + 1:04d}"


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


@router.post("", response_model=MtMachineDto, status_code=status.HTTP_201_CREATED)
def create_mt_machine(
    payload: MtMachineCreate,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Add a new asset to mt_asset_list. SUPERVISOR / HEAD / TECHNICIAN / ADMIN only
    (not OPERATOR). The app sends the full row with an empty asset_id; the backend
    assigns a building-prefixed id, stores every field, and returns the MtMachineDto
    (with the assigned asset_id and rated_kw computed from power_load)."""
    if user.norm_role not in _CREATE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to add assets",
        )

    building = (payload.building or "").strip()
    asset_name = (payload.asset_name or "").strip()
    category = (payload.category or "").strip()
    sub_location = (payload.sub_location or "").strip()
    missing = [n for n, v in (
        ("building", building), ("asset_name", asset_name),
        ("category", category), ("sub_location", sub_location),
    ) if not v]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required field(s): {', '.join(missing)}",
        )

    # asset_id is assigned server-side (any value in the body is ignored). Retry a
    # couple of times so a rare concurrent insert racing the same id just re-picks.
    for _ in range(3):
        row = MtAsset(
            asset_id=_next_asset_id(db, building),
            building=building,
            asset_name=asset_name,
            category=category,
            sub_location=sub_location,
            power_load=payload.power_load,
            quantity=payload.quantity,
            model_no=payload.model_no,
            serial_no=payload.serial_no,
            condition=payload.condition,
            assigned_to=payload.assigned_to,
            remarks=payload.remarks,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(row)
        return _to_dto(row)

    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                        detail="Could not allocate an asset id; please retry")


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
