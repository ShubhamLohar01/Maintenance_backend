"""Schedule Electric Assets — daily consumption recording for non-runnable assets.

'Electric Asset' rows (lights, fans, etc.) can't be started/stopped by an operator,
so they log zero energy. A SUPERVISOR gives each one a recurring daily window
(e.g. 10:00-20:00); this module then generates one mt_machine_daily_kwh row per
elapsed day (source='SCHEDULE', daily_kwh = rated_kw x window-hours x power_factor)
via lazy backfill. HEAD is read-only. Schedules live on mt_asset_list (no new table).
"""
from datetime import datetime, timedelta, time as time_cls, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MachineDailyKwh, MtUser
from ..schemas import AssetScheduleDto, AssetScheduleUpsertRequest
from ..auth import get_current_user
from ..utils import iso_z, parse_kw, norm_plant, building_for
from ..config import settings

router = APIRouter(prefix="/asset-schedules", tags=["asset-schedules"])

ELECTRIC_CATEGORY = "Electric Asset"
IST = ZoneInfo("Asia/Kolkata")
_SCHEDULE = "SCHEDULE"
_COMPLETE = "COMPLETE"
_DAY_MINUTES = 24 * 60


def _hours(start_min: Optional[int], end_min: Optional[int]) -> float:
    if start_min is None or end_min is None:
        return 0.0
    return max(0.0, (end_min - start_min) / 60.0)


def _est_kwh(rated_kw: Optional[float], start_min: Optional[int], end_min: Optional[int]) -> Optional[float]:
    if not rated_kw:
        return None
    hrs = _hours(start_min, end_min)
    if hrs <= 0:
        return None
    return round(rated_kw * hrs * settings.power_factor, 3)


def _minute_to_time(m: int) -> time_cls:
    return time_cls(hour=(m // 60) % 24, minute=m % 60)


def _fmt_label(m: Optional[int]) -> Optional[str]:
    """Minute-of-day -> readable 12h clock, e.g. 600 -> '10:00 AM', 1140 -> '7:00 PM',
    0 -> '12:00 AM', 720 -> '12:00 PM'. None stays None (no window set)."""
    if m is None:
        return None
    h24, minute = (m // 60) % 24, m % 60
    period = "AM" if h24 < 12 else "PM"
    return f"{h24 % 12 or 12}:{minute:02d} {period}"


def _to_dto(a: MtAsset) -> AssetScheduleDto:
    rated = parse_kw(a.power_load) or None
    return AssetScheduleDto(
        asset_id=a.asset_id or str(a.id),
        asset_name=a.asset_name,
        building=a.building,
        sub_location=a.sub_location,
        power_load=a.power_load,
        rated_kw=rated,
        condition=a.condition,
        start_min=a.schedule_start_min,
        end_min=a.schedule_end_min,
        start_label=_fmt_label(a.schedule_start_min),
        end_label=_fmt_label(a.schedule_end_min),
        active=bool(a.schedule_active),
        hours=round(_hours(a.schedule_start_min, a.schedule_end_min), 2),
        est_daily_kwh=_est_kwh(rated, a.schedule_start_min, a.schedule_end_min),
        updated_by=a.schedule_updated_by,
        updated_at=iso_z(a.schedule_updated_at),
    )


def _try_insert_schedule_row(
    db: Session, asset: MtAsset, cursor, kwh: float,
    client_run_id: str, started: datetime, ended: datetime,
) -> bool:
    """Insert one SCHEDULE row inside a SAVEPOINT. `client_run_id` is UNIQUE at the DB
    level (see migrations/2026-07-15_daily_kwh_client_run_id_unique.sql), so if another
    concurrent sweep — the 21:00 cron (app/scheduler.py) and a lazy on-read sweep can now
    both fire independently — already inserted this exact (asset, day) a moment ago, this
    raises IntegrityError. We catch it here so only THIS ONE ROW's SAVEPOINT rolls back;
    the rest of the sweep (other assets/days already pending in the outer transaction)
    is untouched. Returns True if this call inserted the row, False if it lost the race."""
    try:
        with db.begin_nested():
            db.add(MachineDailyKwh(
                machine_id=asset.asset_id,
                reading_date=cursor,
                building=asset.building or "W-202",
                floor=asset.sub_location,
                client_run_id=client_run_id,
                operator_id=None,
                operator_name="Scheduled",
                started_at=started,
                ended_at=ended,
                status=_COMPLETE,
                daily_kwh=kwh,
                source=_SCHEDULE,
            ))
            db.flush()  # force the INSERT now, inside the SAVEPOINT, so a collision raises here
        return True
    except IntegrityError:
        return False  # another sweep already recorded this (asset, day) — not an error


def generate_due_rows(db: Session, now: Optional[datetime] = None) -> int:
    """Backfill missing daily consumption rows for every active electric-asset
    schedule, up to the latest window that has FULLY elapsed in IST. Idempotent
    (keyed on client_run_id 'sched-{asset}-{date}', UNIQUE-constraint-backed — a
    losing concurrent insert is caught and skipped, not crashed); safe to call on
    every read AND from a concurrent scheduled trigger (app/scheduler.py).
    Returns the number of rows actually inserted by THIS call."""
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    today = now.astimezone(IST).date()

    schedules = (
        db.query(MtAsset)
        .filter(
            MtAsset.category == ELECTRIC_CATEGORY,
            MtAsset.schedule_active.is_(True),
            MtAsset.schedule_start_min.isnot(None),
            MtAsset.schedule_end_min.isnot(None),
        )
        .all()
    )

    inserted = 0
    for a in schedules:
        rated_kw = parse_kw(a.power_load)
        start_min, end_min = a.schedule_start_min, a.schedule_end_min
        # No power draw or an invalid window -> nothing meaningful to record.
        if not rated_kw or end_min <= start_min:
            continue
        kwh = round(rated_kw * _hours(start_min, end_min) * settings.power_factor, 3)

        # Resume the day after the last generated date; for a fresh schedule start
        # from the day it was set (so we never backdate before the supervisor set it).
        if a.schedule_last_generated is not None:
            cursor = a.schedule_last_generated + timedelta(days=1)
        else:
            set_date = (a.schedule_updated_at or now.astimezone(timezone.utc).replace(tzinfo=None)).date()
            cursor = set_date

        last_done = a.schedule_last_generated
        while cursor <= today:
            # Only record a day once its window end has passed (IST).
            window_end_ist = datetime.combine(cursor, _minute_to_time(end_min), tzinfo=IST)
            if window_end_ist > now.astimezone(IST):
                break

            client_run_id = f"sched-{a.asset_id}-{cursor.isoformat()}"
            exists = (
                db.query(MachineDailyKwh)
                .filter(MachineDailyKwh.client_run_id == client_run_id)
                .first()
            )
            if exists is None:
                # Store started/ended as UTC-naive (consistent with run rows) so the
                # energy history renders the same way; only the duration drives kWh.
                start_ist = datetime.combine(cursor, _minute_to_time(start_min), tzinfo=IST)
                started = start_ist.astimezone(timezone.utc).replace(tzinfo=None)
                ended = window_end_ist.astimezone(timezone.utc).replace(tzinfo=None)
                if _try_insert_schedule_row(db, a, cursor, kwh, client_run_id, started, ended):
                    inserted += 1
            # Either way this day is now recorded (by us, or by whichever sweep won
            # the race) — advance past it so we never re-attempt it.
            last_done = cursor
            cursor += timedelta(days=1)

        if last_done is not None and last_done != a.schedule_last_generated:
            a.schedule_last_generated = last_done

    db.commit()
    return inserted


def _get_electric_asset(db: Session, machine_id: str) -> MtAsset:
    a = db.query(MtAsset).filter(MtAsset.asset_id == machine_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail=f"Asset {machine_id} not found")
    if (a.category or "").strip() != ELECTRIC_CATEGORY:
        raise HTTPException(
            status_code=400,
            detail="Only 'Electric Asset' items can be scheduled",
        )
    return a


def _require_supervisor(user: MtUser) -> None:
    if user.norm_role != "SUPERVISOR":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a supervisor can change asset schedules",
        )


@router.get("", response_model=List[AssetScheduleDto])
def list_asset_schedules(
    plant_id: str = Query("both", description="W202 | A185 | both (any spelling)"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All 'Electric Asset' rows + their schedule, newest missing days backfilled
    first. Any authenticated role (HEAD sees the same list, read-only)."""
    generate_due_rows(db)

    q = db.query(MtAsset).filter(MtAsset.category == ELECTRIC_CATEGORY)
    if norm_plant(plant_id) not in ("BOTH", ""):
        b = building_for(plant_id)
        if b:
            q = q.filter(MtAsset.building == b)
    rows = q.order_by(MtAsset.asset_id.asc()).all()
    return [_to_dto(a) for a in rows]


@router.put("/{machine_id}", response_model=AssetScheduleDto)
def upsert_asset_schedule(
    machine_id: str,
    payload: AssetScheduleUpsertRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Create or replace an electric asset's daily recording window (SUPERVISOR only).
    Backfills any days that already fully elapsed under the new window before returning."""
    _require_supervisor(user)
    a = _get_electric_asset(db, machine_id)

    if not (0 <= payload.start_min < payload.end_min <= _DAY_MINUTES):
        raise HTTPException(
            status_code=400,
            detail="Require 0 <= start_min < end_min <= 1440 (same-day window)",
        )

    a.schedule_start_min = payload.start_min
    a.schedule_end_min = payload.end_min
    a.schedule_active = payload.active
    a.schedule_updated_by = user.username
    a.schedule_updated_at = datetime.utcnow()
    db.commit()

    generate_due_rows(db)
    db.refresh(a)
    return _to_dto(a)


@router.delete("/{machine_id}", response_model=AssetScheduleDto)
def clear_asset_schedule(
    machine_id: str,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Remove an asset's schedule (SUPERVISOR only). Already-recorded days are kept;
    only future generation stops."""
    _require_supervisor(user)
    a = _get_electric_asset(db, machine_id)
    a.schedule_start_min = None
    a.schedule_end_min = None
    a.schedule_active = False
    a.schedule_updated_by = user.username
    a.schedule_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(a)
    return _to_dto(a)


@router.post("/generate")
def generate_now(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Force a backfill sweep (the list endpoint already does this). {generated: n}."""
    return {"generated": generate_due_rows(db)}
