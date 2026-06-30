from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Floor, Machine, FloorUtilityReading, User
from ..schemas import FloorUtilityReadingDto, FloorSummaryDto
from ..auth import get_current_user

router = APIRouter(prefix="/floors", tags=["floors"])


@router.get("/", response_model=List[FloorSummaryDto])
def list_floors(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Floor-wise summary: machine count, total rated kW, latest meter reading,
    last-30-days consumed kWh. Backs an admin dashboard (out of scope for the
    operator mobile app contract, but useful for the maintenance head)."""
    floors = db.query(Floor).filter(Floor.plant_id == user.plant_id).all()
    today = datetime.utcnow().date()
    cutoff = today - timedelta(days=30)

    out: List[FloorSummaryDto] = []
    for f in floors:
        agg = (
            db.query(
                func.count(Machine.id),
                func.coalesce(func.sum(Machine.rated_kw), 0.0),
            )
            .filter(Machine.floor_id == f.id)
            .one()
        )
        machine_count, total_kw = agg

        latest = (
            db.query(FloorUtilityReading)
            .filter(FloorUtilityReading.floor_id == f.id)
            .order_by(FloorUtilityReading.reading_date.desc())
            .first()
        )
        last_30 = (
            db.query(func.coalesce(func.sum(FloorUtilityReading.daily_kwh), 0.0))
            .filter(
                FloorUtilityReading.floor_id == f.id,
                FloorUtilityReading.reading_date >= cutoff,
            )
            .scalar()
        )

        out.append(FloorSummaryDto(
            floor_id=f.id,
            floor_name=f.name,
            machine_count=machine_count,
            total_rated_kw=round(float(total_kw), 3),
            latest_meter_reading=latest.meter_reading if latest else None,
            last_30d_kwh=round(float(last_30), 2) if last_30 else None,
        ))
    return out


@router.get("/{floor_id}/utility", response_model=List[FloorUtilityReadingDto])
def floor_utility(
    floor_id: str,
    from_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    floor = db.get(Floor, floor_id)
    if floor is None:
        raise HTTPException(status_code=404, detail="Floor not found")

    q = db.query(FloorUtilityReading).filter(FloorUtilityReading.floor_id == floor_id)
    if from_date:
        q = q.filter(FloorUtilityReading.reading_date >= datetime.fromisoformat(from_date).date())
    if to_date:
        q = q.filter(FloorUtilityReading.reading_date <= datetime.fromisoformat(to_date).date())
    rows = q.order_by(FloorUtilityReading.reading_date.asc()).all()
    return [
        FloorUtilityReadingDto(
            floor_id=r.floor_id,
            floor_name=floor.name,
            reading_date=r.reading_date.isoformat(),
            meter_reading=r.meter_reading,
            daily_kwh=r.daily_kwh,
        )
        for r in rows
    ]
