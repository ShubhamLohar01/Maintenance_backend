"""Utility Consumption endpoints — daily Diesel / Gas / Electricity / Water logs.

One row per (plant, reading_date) in the four mt_utility_* tables. The Android app
fills the input fields, computes the derived values client-side (mirroring the
"Utility Consumption 2026-2027" sheet formulas), and POSTs BOTH inputs and computed
values here. The backend is a PASS-THROUGH store: it normalizes the plant, upserts on
(plant, reading_date) — so re-submitting the same day EDITS that row — and saves what
it receives. (The formulas are documented on each model; flip to server-authoritative
recompute later by filling the derived fields here instead of trusting the client.)

Auth: any authenticated caller (Bearer JWT). `plant` accepts any spelling and is
normalized to 'A-185' / 'W-202'; `reading_date` is an ISO date.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple, Type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_rds
from ..models import (
    MtUser, MtUtilityDiesel, MtUtilityGas, MtUtilityElectricity, MtUtilityWater,
)
from ..schemas import (
    UtilityDieselRequest, UtilityDieselDto,
    UtilityGasRequest, UtilityGasDto,
    UtilityElectricityRequest, UtilityElectricityDto,
    UtilityWaterRequest, UtilityWaterDto,
)
from ..auth import get_current_user
from ..utils import building_for, iso_z

router = APIRouter(prefix="/utilities", tags=["utilities"])


def _canon_plant(plant: str) -> str:
    """Any spelling ('A185', 'w-202', ' A-185 ') -> canonical 'A-185' / 'W-202'; 400 else."""
    canon = building_for(plant)
    if canon is None:
        raise HTTPException(status_code=400, detail=f"unknown plant {plant!r} (expected A-185 or W-202)")
    return canon


def _parse_reading_date(raw: Optional[str]) -> date:
    """'YYYY-MM-DD' -> date; 400 (not the default 422) when missing or unparseable —
    reading_date arrives as a plain str in the request schema for exactly this reason."""
    if not raw or not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="reading_date is required (expected YYYY-MM-DD)")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"reading_date {raw!r} is not a valid date (expected YYYY-MM-DD)")


def _check_closing_not_less_than_opening(pairs: Sequence[Tuple[str, Optional[float], Optional[float]]]) -> None:
    """400 if any (label, opening, closing) pair has closing < opening. Pairs with a
    missing side are skipped — partial saves are allowed (see schemas.py)."""
    for label, opening, closing in pairs:
        if opening is not None and closing is not None and closing < opening:
            raise HTTPException(
                status_code=400,
                detail=f"{label}: closing ({closing}) is less than opening ({opening})",
            )


def _row_to_dto(DtoCls: Type[BaseModel], row) -> BaseModel:
    """ORM row -> DTO. Numerics come back as Decimal -> float; reading_date -> ISO str;
    audit timestamps -> ISO Z."""
    data = {}
    for name in DtoCls.model_fields:
        if name in ("created_at", "updated_at"):
            data[name] = iso_z(getattr(row, name, None))
        elif name == "reading_date":
            val = getattr(row, name, None)
            data[name] = val.isoformat() if val is not None else None
        else:
            val = getattr(row, name, None)
            data[name] = float(val) if isinstance(val, Decimal) else val
    return DtoCls(**data)


def _upsert(
    db: Session, Model, DtoCls: Type[BaseModel], req: BaseModel, user: MtUser,
    pairs: Sequence[Tuple[str, Optional[float], Optional[float]]] = (),
) -> BaseModel:
    """Insert, or overwrite the existing (plant, reading_date) row (full replace — the app
    sends every field each save). Returns the stored row as a DTO."""
    plant = _canon_plant(req.plant)
    rdate = _parse_reading_date(req.reading_date)
    _check_closing_not_less_than_opening(pairs)
    values = req.model_dump(exclude={"plant", "reading_date", "created_by"})

    row = (
        db.query(Model)
        .filter(Model.plant == plant, Model.reading_date == rdate)
        .first()
    )
    if row is None:
        row = Model(plant=plant, reading_date=rdate, created_by=user.username, **values)
        db.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
        row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _row_to_dto(DtoCls, row)


def _list(
    db: Session, Model, DtoCls: Type[BaseModel],
    plant: Optional[str], date_from: Optional[date], date_to: Optional[date],
) -> List[BaseModel]:
    q = db.query(Model)
    if plant:
        q = q.filter(Model.plant == _canon_plant(plant))
    if date_from:
        q = q.filter(Model.reading_date >= date_from)
    if date_to:
        q = q.filter(Model.reading_date <= date_to)
    rows = q.order_by(Model.reading_date.desc(), Model.id.desc()).all()
    return [_row_to_dto(DtoCls, r) for r in rows]


# --- Diesel -----------------------------------------------------------------

@router.post("/diesel", response_model=UtilityDieselDto)
def upsert_diesel(req: UtilityDieselRequest, db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user)):
    """Save one day's DG diesel log for a plant (upsert on plant+date)."""
    pairs = [
        ("initial/final kwh reading", req.initial_kwh_reading, req.final_kwh_reading),
        ("start/stop DG run hour", req.start_dg_run_hour, req.stop_dg_run_hour),
    ]
    return _upsert(db, MtUtilityDiesel, UtilityDieselDto, req, user, pairs)


@router.get("/diesel", response_model=List[UtilityDieselDto])
def list_diesel(
    plant: Optional[str] = Query(None), date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    return _list(db, MtUtilityDiesel, UtilityDieselDto, plant, date_from, date_to)


# --- Gas --------------------------------------------------------------------

@router.post("/gas", response_model=UtilityGasDto)
def upsert_gas(req: UtilityGasRequest, db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user)):
    """Save one day's gas log for a plant (upsert on plant+date)."""
    pairs = [("gas meter opening/closing", req.gas_meter_opening, req.gas_meter_closing)]
    return _upsert(db, MtUtilityGas, UtilityGasDto, req, user, pairs)


@router.get("/gas", response_model=List[UtilityGasDto])
def list_gas(
    plant: Optional[str] = Query(None), date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    return _list(db, MtUtilityGas, UtilityGasDto, plant, date_from, date_to)


# --- Electricity ------------------------------------------------------------

@router.post("/electricity", response_model=UtilityElectricityDto)
def upsert_electricity(req: UtilityElectricityRequest, db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user)):
    """Save one day's electricity log for a plant (upsert on plant+date)."""
    pairs = [
        ("energy meter opening/closing kWh", req.energy_meter_opening_kwh, req.energy_meter_closing_kwh),
        ("energy meter opening/closing kVAh", req.energy_meter_opening_kvah, req.energy_meter_closing_kvah),
    ]
    return _upsert(db, MtUtilityElectricity, UtilityElectricityDto, req, user, pairs)


@router.get("/electricity", response_model=List[UtilityElectricityDto])
def list_electricity(
    plant: Optional[str] = Query(None), date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    return _list(db, MtUtilityElectricity, UtilityElectricityDto, plant, date_from, date_to)


# --- Water ------------------------------------------------------------------

@router.post("/water", response_model=UtilityWaterDto)
def upsert_water(req: UtilityWaterRequest, db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user)):
    """Save one day's water log for a plant (upsert on plant+date)."""
    pairs = [("water meter opening/closing", req.water_meter_opening, req.water_meter_closing)]
    return _upsert(db, MtUtilityWater, UtilityWaterDto, req, user, pairs)


@router.get("/water", response_model=List[UtilityWaterDto])
def list_water(
    plant: Optional[str] = Query(None), date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    return _list(db, MtUtilityWater, UtilityWaterDto, plant, date_from, date_to)
