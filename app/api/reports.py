from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MachineDailyKwh, MtAsset
from ..schemas import HeadPowerReportDto, WarehousePowerDto
from ..auth import get_current_user
from ..utils import norm_plant, scoped_buildings

router = APIRouter(tags=["head"])


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
