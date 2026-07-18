from datetime import date, datetime, timedelta
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MachineDailyKwh, MtFloorUtilityReading, User
from ..schemas import (
    FloorSystemReadingDto, FloorReadingsResponse,
    FloorReadingsSubmitRequest, FloorReadingsSubmitResponse,
)
from ..auth import get_current_user
from ..utils import building_for, scoped_buildings

router = APIRouter(prefix="/floor-readings", tags=["floor-readings"])

IST = ZoneInfo("Asia/Kolkata")


def _default_reading_date() -> date:
    """No explicit date -> yesterday (IST). A technician's 'Daily Reading' round
    reports the PREVIOUS day's full consumption — today's isn't over yet, so
    defaulting to today (as this used to) always undercounted the current day's
    still-in-progress runs."""
    return (datetime.now(IST) - timedelta(days=1)).date()


def _resolve_building(user, requested: str | None, *, allow_default: bool) -> str:
    """The single building this caller enters meter readings for.

    Daily meter reading is a per-building physical task, so it always resolves to
    ONE building. OPERATOR/TECHNICIAN -> their own plant (`requested` ignored — they
    can never read another plant). HEAD/SUPERVISOR oversee both plants, so they pass
    `?building=A-185` (or W-202). For the GET (read-only) `allow_default=True` falls
    back to the first scoped building so the screen always loads; the POST keeps it
    strict so a write is never silently saved to the wrong building."""
    allowed = scoped_buildings(user, requested)  # head/sup narrowed by requested; others = own
    if len(allowed) == 1:
        return allowed[0]
    pid = getattr(user, "plant_id", None)
    if not allowed:
        raise HTTPException(
            status_code=400,
            detail=(f"Could not resolve a building for this user (plant_id={pid!r}). "
                    "Set the user's location to A-185 or W-202, or pass ?building=A-185."),
        )
    if allow_default:                       # GET: HEAD/SUPERVISOR with no building -> first plant
        return allowed[0]
    raise HTTPException(                     # POST: must name the building explicitly
        status_code=400,
        detail="Multiple buildings in scope — pass building=A-185 or building=W-202 in the body.",
    )


def _building_floors(db: Session, building: str) -> list[str]:
    """Distinct non-blank floors (= mt_asset_list.sub_location) for the building."""
    rows = (
        db.query(MtAsset.sub_location)
        .filter(MtAsset.building == building, MtAsset.sub_location.isnot(None))
        .distinct()
        .all()
    )
    return sorted({(r[0] or "").strip() for r in rows} - {""})


def _system_by_floor(db: Session, building: str, on: date) -> dict[str, float]:
    """Sum of run kWh (mt_machine_daily_kwh.daily_kwh) per floor for the date."""
    rows = (
        db.query(MachineDailyKwh.floor, func.sum(MachineDailyKwh.daily_kwh))
        .filter(MachineDailyKwh.building == building, MachineDailyKwh.reading_date == on)
        .group_by(MachineDailyKwh.floor)
        .all()
    )
    return {(f or "").strip(): float(s or 0.0) for f, s in rows}


@router.get("/system", response_model=FloorReadingsResponse)
def fetch_system_readings(
    date_: str | None = Query(None, alias="date", description="ISO YYYY-MM-DD; defaults to yesterday"),
    building_: str | None = Query(None, alias="building", description="A-185 / W-202; required for HEAD/SUPERVISOR"),
    db: Session = Depends(get_rds),
    user: User = Depends(get_current_user),
):
    """"Fetch system reading" button: every floor of the caller's building with the
    system-generated kWh total for `date` (default yesterday — today's day isn't
    over yet), plus any actual meter reading already saved for that floor/date so
    the form is re-editable."""
    building = _resolve_building(user, building_, allow_default=True)
    if date_:
        try:
            on = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be ISO YYYY-MM-DD")
    else:
        on = _default_reading_date()

    floors = _building_floors(db, building)
    system = _system_by_floor(db, building, on)
    saved = {
        r.floor: r
        for r in db.query(MtFloorUtilityReading)
        .filter(MtFloorUtilityReading.building == building, MtFloorUtilityReading.reading_date == on)
        .all()
    }

    return FloorReadingsResponse(
        building=building,
        reading_date=on.isoformat(),
        floors=[
            FloorSystemReadingDto(
                floor=f,
                system_reading=round(system.get(f, 0.0), 4),
                meter_reading=(float(saved[f].meter_reading) if f in saved and saved[f].meter_reading is not None else None),
            )
            for f in floors
        ],
    )


@router.post("", response_model=FloorReadingsSubmitResponse)
def submit_readings(
    req: FloorReadingsSubmitRequest,
    db: Session = Depends(get_rds),
    user: User = Depends(get_current_user),
):
    """Save the technician's actual meter readings for all floors in one shot.
    For each floor the server recomputes the system reading from the run table
    (authoritative) and upserts (building, floor, reading_date)."""
    building = _resolve_building(user, req.building, allow_default=False)
    if req.reading_date:
        try:
            on = date.fromisoformat(req.reading_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="reading_date must be ISO YYYY-MM-DD")
    else:
        on = _default_reading_date()

    system = _system_by_floor(db, building, on)
    existing = {
        r.floor: r
        for r in db.query(MtFloorUtilityReading)
        .filter(MtFloorUtilityReading.building == building, MtFloorUtilityReading.reading_date == on)
        .all()
    }

    saved = 0
    for row in req.rows:
        floor = row.floor.strip()
        if not floor:
            continue
        rec = existing.get(floor)
        if rec is None:
            rec = MtFloorUtilityReading(building=building, floor=floor, reading_date=on)
            db.add(rec)
            existing[floor] = rec
        rec.meter_reading = row.meter_reading
        rec.daily_kwh = round(system.get(floor, 0.0), 4)  # system reading, recomputed
        saved += 1

    db.commit()
    return FloorReadingsSubmitResponse(building=building, reading_date=on.isoformat(), saved=saved)
