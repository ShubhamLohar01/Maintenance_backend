from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from ..database import get_rds
from ..models import MtAsset, MachineDailyKwh, MtMachineRunSegment, User, MtUser
from ..schemas import (
    RunStartRequest, RunStartResponse,
    RunStopRequest, RunStopResponse,
    DailyHistoryDto, DailyRunDto, ActiveRunDto,
)
from ..auth import get_current_user
from ..utils import to_epoch_ms, from_epoch_ms, parse_kw, is_shut_down
from ..config import settings

router = APIRouter(prefix="/energy", tags=["energy"])

# A segment (or its daily row) that has been started but not yet stopped.
_RUNNING = "RUNNING"
_COMPLETE = "COMPLETE"
_RUN = "RUN"


def _as_utc(dt: datetime) -> datetime:
    """Treat a stored naive timestamp as UTC (matches how the columns are written)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _segment_hours(started: Optional[datetime], ended: Optional[datetime]) -> float:
    if started is None or ended is None:
        return 0.0
    return max(0.0, (_as_utc(ended) - _as_utc(started)).total_seconds() / 3600.0)


def _recompute_daily_status(db: Session, daily: MachineDailyKwh) -> None:
    """A daily row is RUNNING while any of its segments is still open, else COMPLETE.
    Flush first so just-changed (but uncommitted) segment statuses are counted even when
    the session has autoflush off."""
    db.flush()
    open_left = (
        db.query(MtMachineRunSegment.id)
        .filter(
            MtMachineRunSegment.daily_id == daily.id,
            MtMachineRunSegment.status == _RUNNING,
        )
        .first()
    )
    daily.status = _RUNNING if open_left is not None else _COMPLETE


def _add_segment_kwh(daily: MachineDailyKwh, kwh: float, ended_at: datetime, now: datetime) -> None:
    """Fold a just-closed segment's kWh into its daily row and extend the day's end."""
    daily.daily_kwh = round(float(daily.daily_kwh or 0.0) + kwh, 3)
    if daily.ended_at is None or _as_utc(ended_at) > _as_utc(daily.ended_at):
        daily.ended_at = ended_at
    daily.updated_at = now


def _autoclose_stale_runs(db: Session, now: datetime | None = None) -> int:
    """Close open SEGMENTS whose operator never pressed STOP. A segment open longer than
    settings.max_run_hours is an orphan; we cap its duration at max_run_hours (so the
    115h-style runs stop inflating kWh), compute kWh from the asset's rated power, fold it
    into the daily row, and flip the segment to COMPLETE. Returns the number of segments
    closed. Self-healing — called on every /runs/active poll and exposed manually via
    POST /runs/close-stale."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=settings.max_run_hours)
    stale = (
        db.query(MtMachineRunSegment)
        .filter(MtMachineRunSegment.status == _RUNNING, MtMachineRunSegment.started_at < cutoff)
        .all()
    )
    if not stale:
        return 0

    asset_ids = {s.machine_id for s in stale if s.machine_id}
    assets = {
        a.asset_id: a
        for a in db.query(MtAsset).filter(MtAsset.asset_id.in_(asset_ids)).all()
    } if asset_ids else {}
    daily_ids = {s.daily_id for s in stale}
    dailies = {
        d.id: d
        for d in db.query(MachineDailyKwh).filter(MachineDailyKwh.id.in_(daily_ids)).all()
    }

    for s in stale:
        capped_end = s.started_at + timedelta(hours=settings.max_run_hours)
        asset = assets.get(s.machine_id)
        rated_kw = parse_kw(asset.power_load) if asset else 0.0
        kwh = round(rated_kw * settings.max_run_hours * settings.power_factor, 3)
        s.ended_at = capped_end
        s.kwh = kwh
        s.status = _COMPLETE
        s.updated_at = now
        daily = dailies.get(s.daily_id)
        if daily is not None:
            _add_segment_kwh(daily, kwh, capped_end, now)

    for daily in dailies.values():
        _recompute_daily_status(db, daily)
    db.commit()
    return len(stale)


@router.post("/runs/close-stale")
def close_stale_runs(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Manually sweep orphan runs (open > max_run_hours) -> COMPLETE. {closed: n}."""
    return {"closed": _autoclose_stale_runs(db)}


@router.get("/runs/active", response_model=List[ActiveRunDto])
def active_runs(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Every machine with an open run segment, enriched with the building from
    mt_asset_list. `run_id` is the open segment's id (the id you STOP with); operator is
    the segment's operator. `started_at` is the daily row's earliest segment start (epoch
    ms, same units as POST /energy/runs/start). Orphan segments (open > max_run_hours) are
    auto-closed first so they drop off the live list."""
    _autoclose_stale_runs(db)
    segments = (
        db.query(MtMachineRunSegment)
        .filter(MtMachineRunSegment.status == _RUNNING)
        .order_by(MtMachineRunSegment.started_at.desc())
        .all()
    )
    if not segments:
        return []

    asset_ids = {s.machine_id for s in segments if s.machine_id}
    buildings = (
        dict(
            db.query(MtAsset.asset_id, MtAsset.building)
            .filter(MtAsset.asset_id.in_(asset_ids))
            .all()
        )
        if asset_ids
        else {}
    )
    daily_ids = {s.daily_id for s in segments}
    day_start = {
        d.id: d.started_at
        for d in db.query(MachineDailyKwh.id, MachineDailyKwh.started_at)
        .filter(MachineDailyKwh.id.in_(daily_ids))
        .all()
    }

    return [
        ActiveRunDto(
            asset_id=s.machine_id,
            run_id=str(s.id),
            operator_id=s.operator_id,
            operator_name=s.operator_name,
            # earliest segment start of the day (falls back to this segment's start)
            started_at=to_epoch_ms(day_start.get(s.daily_id) or s.started_at) or 0,
            building=buildings.get(s.machine_id),
        )
        for s in segments
    ]


def _find_run_daily(db: Session, machine_id: str, run_date) -> Optional[MachineDailyKwh]:
    return (
        db.query(MachineDailyKwh)
        .filter(
            MachineDailyKwh.machine_id == machine_id,
            MachineDailyKwh.reading_date == run_date,
            MachineDailyKwh.source == _RUN,
        )
        .first()
    )


@router.post("/runs/start", response_model=RunStartResponse)
def start_run(
    req: RunStartRequest,
    db: Session = Depends(get_rds),
    user: User = Depends(get_current_user),
):
    """Operator pressed START: open a new run SEGMENT against the machine's single daily
    row for that date (creating the daily row on the first start of the day). Every
    start/stop on the same machine + day accumulates into that one row — no duplicate
    daily rows. Idempotent on client_run_id: a retried/duplicate tap returns the same
    segment without opening another. Returns run_id = the segment id (used by /stop)."""
    asset = db.query(MtAsset).filter(MtAsset.asset_id == req.machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")
    if is_shut_down(asset.condition):
        raise HTTPException(status_code=409, detail="Machine is shut down")

    # Idempotency: a replayed start (same client_run_id) returns its existing segment.
    seg = (
        db.query(MtMachineRunSegment)
        .filter(MtMachineRunSegment.client_run_id == req.client_run_id)
        .first()
    )
    if seg is not None:
        daily_started = db.query(MachineDailyKwh.started_at).filter(
            MachineDailyKwh.id == seg.daily_id
        ).scalar()
        return RunStartResponse(
            run_id=str(seg.id),
            client_run_id=req.client_run_id,
            started_at=to_epoch_ms(daily_started or seg.started_at) or 0,
            scheduled_end_at=req.scheduled_end_at,
        )

    started = from_epoch_ms(req.started_at)
    run_date = started.date()

    # Find-or-create the machine's single RUN row for the day. The create races another
    # concurrent first-start; the partial unique index (source='RUN') turns that into an
    # IntegrityError, after which we re-read the row the other request just made.
    daily = _find_run_daily(db, req.machine_id, run_date)
    if daily is None:
        daily = MachineDailyKwh(
            machine_id=req.machine_id,
            reading_date=run_date,
            building=asset.building,
            floor=asset.sub_location,
            operator_id=str(user.id),
            operator_name=user.name,
            started_at=started,
            status=_RUNNING,
            daily_kwh=0,
            source=_RUN,
        )
        db.add(daily)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            daily = _find_run_daily(db, req.machine_id, run_date)
            if daily is None:
                raise HTTPException(status_code=409, detail="Could not open the daily run row; please retry")

    # Keep the day's start at the earliest segment start; reopen the row if it had closed.
    if daily.started_at is None or _as_utc(started) < _as_utc(daily.started_at):
        daily.started_at = started
    daily.status = _RUNNING
    daily.updated_at = datetime.utcnow()

    seg = MtMachineRunSegment(
        daily_id=daily.id,
        machine_id=req.machine_id,
        client_run_id=req.client_run_id,
        operator_id=str(user.id),
        operator_name=user.name,
        started_at=started,
        status=_RUNNING,
        source=_RUN,
    )
    db.add(seg)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent replay inserted the same client_run_id first — return that one.
        db.rollback()
        seg = (
            db.query(MtMachineRunSegment)
            .filter(MtMachineRunSegment.client_run_id == req.client_run_id)
            .first()
        )
        if seg is None:
            raise HTTPException(status_code=409, detail="Could not open the run segment; please retry")
    db.refresh(seg)

    return RunStartResponse(
        run_id=str(seg.id),
        client_run_id=req.client_run_id,
        started_at=req.started_at,
        scheduled_end_at=req.scheduled_end_at,
    )


@router.post("/runs/{run_id}/stop", response_model=RunStopResponse)
def stop_run(
    run_id: str,
    req: RunStopRequest,
    db: Session = Depends(get_rds),
    user: User = Depends(get_current_user),
):
    """Operator pressed STOP: close THIS run segment (run_id = segment id), compute its
    kWh from the asset's rated power, and FOLD it into the machine's daily row (add to
    daily_kwh, extend the day's end). The daily row stays RUNNING if the machine still has
    another open segment, else flips to COMPLETE. No new row is inserted. Idempotent —
    stopping an already-closed segment returns its stored kWh without re-adding."""
    try:
        seg = db.get(MtMachineRunSegment, int(run_id))
    except (TypeError, ValueError):
        seg = None
    if seg is None:
        raise HTTPException(status_code=404, detail="Run not found")
    asset = db.query(MtAsset).filter(MtAsset.asset_id == seg.machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")

    # Already stopped -> idempotent: return the segment's stored kWh, don't re-add.
    if seg.status == _COMPLETE and seg.ended_at is not None:
        return RunStopResponse(
            run_id=str(seg.id),
            ended_at=to_epoch_ms(seg.ended_at) or req.ended_at,
            computed_kwh=float(seg.kwh or 0.0),
        )

    ended_at = from_epoch_ms(req.ended_at)
    duration_hours = _segment_hours(seg.started_at or ended_at, ended_at)
    rated_kw = parse_kw(asset.power_load)
    kwh = round(rated_kw * duration_hours * settings.power_factor, 3)
    now = datetime.utcnow()

    seg.ended_at = from_epoch_ms(req.ended_at)
    seg.kwh = kwh
    seg.status = _COMPLETE
    seg.updated_at = now

    daily = db.get(MachineDailyKwh, seg.daily_id)
    if daily is not None:
        _add_segment_kwh(daily, kwh, seg.ended_at, now)
        _recompute_daily_status(db, daily)
    db.commit()

    return RunStopResponse(run_id=str(seg.id), ended_at=req.ended_at, computed_kwh=kwh)


@router.get("/machines/{machine_id}/history", response_model=List[DailyHistoryDto])
def machine_history(
    machine_id: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
    db: Session = Depends(get_rds),
    user: User = Depends(get_current_user),
):
    asset = db.query(MtAsset).filter(MtAsset.asset_id == machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")

    start_dt = from_epoch_ms(from_)
    end_dt = from_epoch_ms(to)

    runs = (
        db.query(MachineDailyKwh)
        .filter(
            and_(
                MachineDailyKwh.machine_id == machine_id,
                MachineDailyKwh.started_at >= start_dt,
                MachineDailyKwh.started_at <= end_dt,
            )
        )
        .order_by(MachineDailyKwh.started_at.asc())
        .all()
    )

    # RUN-day run-hours = SUM of that day's segment durations (excludes idle gaps between
    # pause/resume). Fetch every segment for these daily rows once and total per daily id.
    run_daily_ids = [r.id for r in runs if (r.source or _RUN) == _RUN]
    seg_hours: dict[int, float] = {}
    if run_daily_ids:
        for s in (
            db.query(MtMachineRunSegment)
            .filter(MtMachineRunSegment.daily_id.in_(run_daily_ids))
            .all()
        ):
            seg_hours[s.daily_id] = seg_hours.get(s.daily_id, 0.0) + _segment_hours(s.started_at, s.ended_at)

    by_day: dict[str, list[MachineDailyKwh]] = {}
    for r in runs:
        key = (r.started_at or datetime.utcnow()).date().isoformat()
        by_day.setdefault(key, []).append(r)

    out: list[DailyHistoryDto] = []
    for date_str, day_runs in sorted(by_day.items(), reverse=True):
        total_h = 0.0
        total_kwh = 0.0
        dtos: list[DailyRunDto] = []
        for r in day_runs:
            if (r.source or _RUN) == _RUN:
                # Summed segment hours (idle gaps excluded), so run-hours match the kWh.
                dh = seg_hours.get(r.id, 0.0)
            elif r.started_at is not None and r.ended_at is not None:
                dh = _segment_hours(r.started_at, r.ended_at)
            else:
                dh = 0.0
            kwh = float(r.daily_kwh or 0.0)
            total_h += dh
            total_kwh += kwh
            dtos.append(DailyRunDto(
                id=str(r.id),
                started_at=to_epoch_ms(r.started_at) or 0,
                ended_at=to_epoch_ms(r.ended_at),
                duration_hours=round(dh, 2),
                kwh=round(kwh, 2),
            ))
        out.append(DailyHistoryDto(
            date=date_str,
            total_run_hours=round(total_h, 2),
            total_kwh=round(total_kwh, 2),
            estimated_cost=round(total_kwh * settings.cost_per_kwh, 2),
            runs=dtos,
        ))
    return out
