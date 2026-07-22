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
    MtUtilityRate,
)
from ..schemas import (
    UtilityDieselRequest, UtilityDieselDto,
    UtilityGasRequest, UtilityGasDto,
    UtilityElectricityRequest, UtilityElectricityDto,
    UtilityWaterRequest, UtilityWaterDto,
    UtilityRatesDto, UtilityRatesUpdateRequest,
    UtilityPrefillDto,
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


_RATE_EDITOR_ROLES = {"SUPERVISOR", "HEAD", "ADMIN"}


def _require_rate_editor(user: MtUser) -> None:
    """403 unless the caller may set utility rates (SUPERVISOR/HEAD/ADMIN)."""
    if getattr(user, "norm_role", "") not in _RATE_EDITOR_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only SUPERVISOR/HEAD/ADMIN can set utility rates",
        )


def _f(v):
    """Decimal -> float; pass through None/float (SQLite already gives float)."""
    return float(v) if isinstance(v, Decimal) else v


def _current_rate(db: Session, plant: str, field: str):
    """The plant's current rate for `field` (e.g. 'diesel_rate'), or None if the
    plant has no mt_utility_rates row yet."""
    row = db.query(MtUtilityRate).filter(MtUtilityRate.plant == plant).first()
    return getattr(row, field, None) if row else None


def _rates_to_dto(row: MtUtilityRate) -> UtilityRatesDto:
    return UtilityRatesDto(
        plant=row.plant,
        diesel_rate=_f(row.diesel_rate), gas_rate=_f(row.gas_rate),
        water_rate=_f(row.water_rate), electricity_rate=_f(row.electricity_rate),
        set_by=row.set_by, set_at=iso_z(row.set_at),
    )


# --- Server-side recompute (authoritative rate + derived costs) -------------
# `values` is the request payload minus plant/reading_date/created_by. Each
# helper overwrites the rate field with the config value and recomputes the
# derived columns from the client's meter readings + factors. Any missing input
# leaves its derived column None (partial saves stay allowed); cost_per_unit is
# None when production_units is 0/blank.

def _sub(a, b):
    return (a - b) if a is not None and b is not None else None


def _mul(a, b):
    return (a * b) if a is not None and b is not None else None


def _per_unit(cost, production_units):
    return (cost / production_units) if cost is not None and production_units not in (None, 0) else None


def _recompute_diesel(values: dict, rate) -> None:
    values["diesel_rate"] = rate
    values["total_consumption"] = _sub(values.get("final_kwh_reading"), values.get("initial_kwh_reading"))
    values["total_run_hour"] = _sub(values.get("stop_dg_run_hour"), values.get("start_dg_run_hour"))
    values["total_diesel_l"] = _mul(values.get("diesel_l_per_hour"), values["total_run_hour"])
    values["total_fuel_cost"] = _mul(values["total_diesel_l"], rate)


def _recompute_gas(values: dict, rate) -> None:
    values["gas_rate"] = rate
    consumed = _mul(_sub(values.get("gas_meter_closing"), values.get("gas_meter_opening")),
                    values.get("gas_conversion_factor"))
    values["gas_consumed_m3"] = consumed
    values["daily_gas_cost"] = _mul(consumed, rate)
    values["cost_per_unit"] = _per_unit(values["daily_gas_cost"], values.get("production_units"))


def _recompute_electricity(values: dict, rate) -> None:
    values["electricity_rate"] = rate
    consumed_kwh = _mul(_sub(values.get("energy_meter_closing_kwh"), values.get("energy_meter_opening_kwh")),
                        values.get("ct_multiplier"))
    values["electricity_consumed_kwh"] = consumed_kwh
    values["electricity_consumed_kvah"] = _sub(values.get("energy_meter_closing_kvah"),
                                               values.get("energy_meter_opening_kvah"))
    values["daily_electricity_cost"] = _mul(consumed_kwh, rate)
    values["cost_per_unit"] = _per_unit(values["daily_electricity_cost"], values.get("production_units"))


def _recompute_water(values: dict, rate) -> None:
    values["water_rate"] = rate
    consumed = _sub(values.get("water_meter_closing"), values.get("water_meter_opening"))
    values["water_consumed"] = consumed
    values["daily_water_cost"] = _mul(consumed, rate)
    values["cost_per_unit"] = _per_unit(values["daily_water_cost"], values.get("production_units"))


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
    recompute=None, rate_field: Optional[str] = None,
) -> BaseModel:
    """Insert, or overwrite the existing (plant, reading_date) row. The rate is
    NOT trusted from the client: `recompute` stamps the current supervisor rate
    (from mt_utility_rates) onto the row and recomputes the derived costs."""
    plant = _canon_plant(req.plant)
    rdate = _parse_reading_date(req.reading_date)
    _check_closing_not_less_than_opening(pairs)
    values = req.model_dump(exclude={"plant", "reading_date", "created_by"})
    if recompute is not None and rate_field is not None:
        recompute(values, _f(_current_rate(db, plant, rate_field)))

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
    return _upsert(db, MtUtilityDiesel, UtilityDieselDto, req, user, pairs,
                   _recompute_diesel, "diesel_rate")


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
    return _upsert(db, MtUtilityGas, UtilityGasDto, req, user, pairs,
                   _recompute_gas, "gas_rate")


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
    return _upsert(db, MtUtilityElectricity, UtilityElectricityDto, req, user, pairs,
                   _recompute_electricity, "electricity_rate")


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
    return _upsert(db, MtUtilityWater, UtilityWaterDto, req, user, pairs,
                   _recompute_water, "water_rate")


@router.get("/water", response_model=List[UtilityWaterDto])
def list_water(
    plant: Optional[str] = Query(None), date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    return _list(db, MtUtilityWater, UtilityWaterDto, plant, date_from, date_to)


# --- Rates (supervisor-managed current prices) ------------------------------

@router.get("/rates", response_model=List[UtilityRatesDto])
def get_rates(
    plant: Optional[str] = Query(None),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Current prices, one row per plant. `plant` optional (omit for both).
    Any authenticated caller — the technician app reads these to display the
    read-only price."""
    q = db.query(MtUtilityRate)
    if plant:
        q = q.filter(MtUtilityRate.plant == _canon_plant(plant))
    return [_rates_to_dto(r) for r in q.order_by(MtUtilityRate.plant).all()]


@router.put("/rates", response_model=UtilityRatesDto)
def set_rates(
    req: UtilityRatesUpdateRequest,
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Set one or more rates for a plant (SUPERVISOR/HEAD/ADMIN). Partial: only
    the rates present in the body change; the rest are kept."""
    _require_rate_editor(user)
    plant = _canon_plant(req.plant)
    changes = req.model_dump(exclude={"plant"}, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="no rate fields provided")
    row = db.query(MtUtilityRate).filter(MtUtilityRate.plant == plant).first()
    if row is None:
        row = MtUtilityRate(plant=plant, set_by=user.username, **changes)
        db.add(row)
    else:
        for k, v in changes.items():
            setattr(row, k, v)
        row.set_by = user.username
        row.set_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _rates_to_dto(row)


# --- Prefill (opening <- previous closing) ----------------------------------
# For each utility: (Model, rate field, {opening_field: previous_closing_field}).
_PREFILL_MAP = {
    "diesel":      (MtUtilityDiesel, "diesel_rate",
                    {"initial_kwh_reading": "final_kwh_reading",
                     "start_dg_run_hour": "stop_dg_run_hour"}),
    "gas":         (MtUtilityGas, "gas_rate",
                    {"gas_meter_opening": "gas_meter_closing"}),
    "electricity": (MtUtilityElectricity, "electricity_rate",
                    {"energy_meter_opening_kwh": "energy_meter_closing_kwh",
                     "energy_meter_opening_kvah": "energy_meter_closing_kvah"}),
    "water":       (MtUtilityWater, "water_rate",
                    {"water_meter_opening": "water_meter_closing"}),
}


@router.get("/{utility}/prefill", response_model=UtilityPrefillDto)
def prefill(
    utility: str,
    plant: str = Query(...),
    date_q: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Opening values for a new reading form, copied from the most recent EARLIER
    row's closing (survives skipped days), plus the current rate. `date` defaults
    to today."""
    cfg = _PREFILL_MAP.get(utility)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"unknown utility {utility!r}")
    Model, rate_field, mapping = cfg
    cplant = _canon_plant(plant)
    rdate = _parse_reading_date(date_q) if date_q else date.today()
    prev = (
        db.query(Model)
        .filter(Model.plant == cplant, Model.reading_date < rdate)
        .order_by(Model.reading_date.desc(), Model.id.desc())
        .first()
    )
    openings = {
        open_field: (_f(getattr(prev, close_field, None)) if prev else None)
        for open_field, close_field in mapping.items()
    }
    return UtilityPrefillDto(
        plant=cplant, utility=utility, reading_date=rdate.isoformat(),
        source_date=prev.reading_date.isoformat() if prev else None,
        rate=_f(_current_rate(db, cplant, rate_field)),
        openings=openings,
    )
