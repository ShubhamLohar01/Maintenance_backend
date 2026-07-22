from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MachineDailyKwh, MtAsset, MtFloorUtilityReading, MtUser
from ..schemas import (
    HeadPowerReportDto, WarehousePowerDto,
    MachineReadingRowDto, MachinesReadingResponse,
    FloorReadingReportRowDto, FloorReadingsReportResponse,
)
from ..auth import get_current_user
from ..utils import norm_plant, scoped_buildings, to_epoch_ms

router = APIRouter(tags=["head"])

IST = ZoneInfo("Asia/Kolkata")


def _parse_date(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be ISO date YYYY-MM-DD")


def _report_for_building(db: Session, building: str, d_from: date, d_to: date,
                         from_s: str, to_s: str) -> dict:
    """Aggregate one warehouse's daily-kWh rows over [d_from, d_to]."""
    rows = (
        db.query(MachineDailyKwh)
        .filter(
            MachineDailyKwh.building == building,
            MachineDailyKwh.reading_date >= d_from,
            MachineDailyKwh.reading_date <= d_to,
        )
        .all()
    )
    total = 0.0
    by_day: dict[str, float] = {}
    by_machine: dict[str, float] = {}
    for r in rows:
        kwh = float(r.daily_kwh or 0)
        total += kwh
        ds = r.reading_date.isoformat()
        by_day[ds] = by_day.get(ds, 0.0) + kwh
        by_machine[r.machine_id] = by_machine.get(r.machine_id, 0.0) + kwh

    names: dict[str, str] = {}
    if by_machine:
        for a in db.query(MtAsset).filter(MtAsset.asset_id.in_(list(by_machine))).all():
            names[a.asset_id] = a.asset_name

    return {
        "plant_id": norm_plant(building),
        "from": from_s,
        "to": to_s,
        "total_kwh": round(total, 4),
        "by_day": [{"date": d, "kwh": round(v, 4)} for d, v in sorted(by_day.items())],
        "by_machine": [
            {"machine_id": m, "name": names.get(m, ""), "kwh": round(v, 4)}
            for m, v in sorted(by_machine.items())
        ],
    }


@router.get("/head/reports/power", response_model=HeadPowerReportDto)
def power_report(
    from_: str = Query(..., alias="from", description="ISO YYYY-MM-DD (inclusive)"),
    to: str = Query(..., description="ISO YYYY-MM-DD (inclusive)"),
    db: Session = Depends(get_rds),
    user=Depends(get_current_user),
):
    """Per-warehouse energy totals for the Head Reports view, summed from the daily
    per-machine kWh. Warehouses are derived from the JWT (HEAD -> both A-185 + W-202;
    others -> own plant); the app sends no plant param."""
    d_from = _parse_date(from_, "from")
    d_to = _parse_date(to, "to")
    buildings = scoped_buildings(user)
    warehouses = [
        WarehousePowerDto(**_report_for_building(db, b, d_from, d_to, from_, to))
        for b in buildings
    ]
    return HeadPowerReportDto(from_=from_, to=to, warehouses=warehouses)


# ============================================================================
# Supervisor Reports — Machines Reading (mt_machine_daily_kwh) and
# Warehouse/Floor Readings (mt_floor_utility_readings). Read-only historical
# listings, one row per stored record (no aggregation). Any authenticated user
# may call these (role gating lives in the app's nav, not the API) — same
# convention as /asset-schedules, /spare-parts.
# ============================================================================

def _reading_range(from_: Optional[str], to_: Optional[str]) -> tuple[date, date]:
    """Both bounds are explicit query params -> simple inclusive range, defaulting
    to the last 30 days. 400 on an unparseable date or from > to."""
    today = datetime.now(IST).date()
    if to_:
        try:
            d_to = date.fromisoformat(to_)
        except ValueError:
            raise HTTPException(status_code=400, detail="to must be ISO date YYYY-MM-DD")
    else:
        d_to = today

    if from_:
        try:
            d_from = date.fromisoformat(from_)
        except ValueError:
            raise HTTPException(status_code=400, detail="from must be ISO date YYYY-MM-DD")
    else:
        d_from = d_to - timedelta(days=30)

    if d_from > d_to:
        raise HTTPException(status_code=400, detail="from must not be after to")
    return d_from, d_to


@router.get("/reports/machines", response_model=MachinesReadingResponse, tags=["reports"])
def machines_reading(
    plant: Optional[str] = Query(None, description="A-185 / W-202 / omitted = both (any spelling)"),
    from_: Optional[str] = Query(None, alias="from", description="ISO YYYY-MM-DD; default = 30 days ago"),
    to: Optional[str] = Query(None, description="ISO YYYY-MM-DD; default = today"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Every mt_machine_daily_kwh row (RUN + SCHEDULE sourced) in range, newest
    first. Plant-scoped like every other supervisor-facing endpoint: SUPERVISOR/
    HEAD see both plants (narrowed by `plant`); everyone else sees only their own."""
    d_from, d_to = _reading_range(from_, to)
    buildings = scoped_buildings(user, plant)
    if not buildings:
        return MachinesReadingResponse(rows=[])

    rows = (
        db.query(MachineDailyKwh)
        .filter(
            MachineDailyKwh.building.in_(buildings),
            MachineDailyKwh.reading_date >= d_from,
            MachineDailyKwh.reading_date <= d_to,
        )
        .order_by(MachineDailyKwh.reading_date.desc(), MachineDailyKwh.id.desc())
        .all()
    )

    # Legacy rows predate the asset_name snapshot column — backfill from mt_asset_list.
    missing_ids = {r.machine_id for r in rows if not r.asset_name and r.machine_id}
    names = {}
    if missing_ids:
        names = {
            a.asset_id: a.asset_name
            for a in db.query(MtAsset).filter(MtAsset.asset_id.in_(list(missing_ids))).all()
        }

    return MachinesReadingResponse(rows=[
        MachineReadingRowDto(
            reading_date=r.reading_date.isoformat(),
            machine_id=r.machine_id or "",
            asset_name=r.asset_name or names.get(r.machine_id, "") or "",
            building=r.building,
            floor=r.floor,
            operator_name=r.operator_name,
            started_at=to_epoch_ms(r.started_at),
            ended_at=to_epoch_ms(r.ended_at),
            status=r.status,
            source=r.source,
            daily_kwh=float(r.daily_kwh) if r.daily_kwh is not None else None,
        )
        for r in rows
    ])


@router.get("/reports/floor-readings", response_model=FloorReadingsReportResponse, tags=["reports"])
def floor_readings_report(
    plant: Optional[str] = Query(None, description="A-185 / W-202 / omitted = both (any spelling)"),
    from_: Optional[str] = Query(None, alias="from", description="ISO YYYY-MM-DD; default = 30 days ago"),
    to: Optional[str] = Query(None, description="ISO YYYY-MM-DD; default = today"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Every mt_floor_utility_readings row in range, newest first — actual
    (meter_reading) and system-computed (daily_kwh) side by side."""
    d_from, d_to = _reading_range(from_, to)
    buildings = scoped_buildings(user, plant)
    if not buildings:
        return FloorReadingsReportResponse(rows=[])

    rows = (
        db.query(MtFloorUtilityReading)
        .filter(
            MtFloorUtilityReading.building.in_(buildings),
            MtFloorUtilityReading.reading_date >= d_from,
            MtFloorUtilityReading.reading_date <= d_to,
        )
        .order_by(MtFloorUtilityReading.reading_date.desc(), MtFloorUtilityReading.id.desc())
        .all()
    )

    return FloorReadingsReportResponse(rows=[
        FloorReadingReportRowDto(
            reading_date=r.reading_date.isoformat(),
            building=r.building,
            floor=r.floor,
            meter_reading=float(r.meter_reading) if r.meter_reading is not None else None,
            daily_kwh=float(r.daily_kwh) if r.daily_kwh is not None else None,
        )
        for r in rows
    ])
