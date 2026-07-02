from datetime import datetime, timedelta, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database import get_rds
from ..models import MtAsset, MachineDailyKwh, User, MtUser
from ..schemas import (
    RunStartRequest, RunStartResponse,
    RunStopRequest, RunStopResponse,
    DailyHistoryDto, DailyRunDto, ActiveRunDto,
)
from ..auth import get_current_user
from ..utils import to_epoch_ms, from_epoch_ms, parse_kw, is_shut_down
from ..config import settings

router = APIRouter(prefix="/energy", tags=["energy"])

# A run/row that has been started but not yet stopped.
_RUNNING = "RUNNING"
_COMPLETE = "COMPLETE"


def _autoclose_stale_runs(db: Session, now: datetime | None = None) -> int:
    """Close RUNNING rows whose operator never pressed STOP. A run open longer than
    settings.max_run_hours is an orphan; we cap its duration at max_run_hours (so the
    115h-style runs stop inflating kWh), compute kWh from the asset's rated power, and
    flip it to COMPLETE. Returns the number of rows closed. Self-healing — called on
    every /runs/active poll and exposed manually via POST /runs/close-stale."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=settings.max_run_hours)
    stale = (
        db.query(MachineDailyKwh)
        .filter(MachineDailyKwh.status == _RUNNING, MachineDailyKwh.started_at < cutoff)
        .all()
    )
    if not stale:
        return 0

    asset_ids = {r.machine_id for r in stale if r.machine_id}
    assets = {
        a.asset_id: a
        for a in db.query(MtAsset).filter(MtAsset.asset_id.in_(asset_ids)).all()
    } if asset_ids else {}

    for r in stale:
        capped_end = r.started_at + timedelta(hours=settings.max_run_hours)
        asset = assets.get(r.machine_id)
        rated_kw = parse_kw(asset.power_load) if asset else 0.0
        r.ended_at = capped_end
        r.daily_kwh = round(rated_kw * settings.max_run_hours * settings.power_factor, 3)
        r.status = _COMPLETE
        r.updated_at = now
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
    """Every machine still RUNNING (status='RUNNING'), enriched with the building
    from mt_asset_list. operator name is stored on the row, so no join is needed.
    `started_at` is epoch ms (same units as POST /energy/runs/start). Orphan runs
    (open > max_run_hours) are auto-closed first so they drop off the live list."""
    _autoclose_stale_runs(db)
    runs = (
        db.query(MachineDailyKwh)
        .filter(MachineDailyKwh.status == _RUNNING)
        .order_by(MachineDailyKwh.started_at.desc())
        .all()
    )
    if not runs:
        return []

    asset_ids = {r.machine_id for r in runs if r.machine_id}
    buildings = (
        dict(
            db.query(MtAsset.asset_id, MtAsset.building)
            .filter(MtAsset.asset_id.in_(asset_ids))
            .all()
        )
        if asset_ids
        else {}
    )

    return [
        ActiveRunDto(
            asset_id=r.machine_id,
            run_id=str(r.id),
            operator_id=r.operator_id,
            operator_name=r.operator_name,
            started_at=to_epoch_ms(r.started_at) or 0,
            building=buildings.get(r.machine_id),
        )
        for r in runs
    ]


@router.post("/runs/start", response_model=RunStartResponse)
def start_run(
    req: RunStartRequest,
    db: Session = Depends(get_rds),
    user: User = Depends(get_current_user),
):
    """Operator pressed START: insert a RUNNING row into mt_machine_daily_kwh.
    Idempotent on client_run_id (a retried/duplicate tap returns the same row)."""
    asset = db.query(MtAsset).filter(MtAsset.asset_id == req.machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")
    if is_shut_down(asset.condition):
        raise HTTPException(status_code=409, detail="Machine is shut down")

    existing = (
        db.query(MachineDailyKwh)
        .filter(MachineDailyKwh.client_run_id == req.client_run_id)
        .first()
    )
    if existing is not None:
        return RunStartResponse(
            run_id=str(existing.id),
            client_run_id=req.client_run_id,
            started_at=to_epoch_ms(existing.started_at) or 0,
            scheduled_end_at=req.scheduled_end_at,
        )

    started = from_epoch_ms(req.started_at)
    run = MachineDailyKwh(
        machine_id=req.machine_id,
        reading_date=started.date(),
        building=asset.building,
        floor=asset.sub_location,
        client_run_id=req.client_run_id,
        operator_id=str(user.id),
        operator_name=user.name,
        started_at=started,
        status=_RUNNING,
        source="RUN",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return RunStartResponse(
        run_id=str(run.id),
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
    """Operator pressed STOP: stamp ended_at, compute daily_kwh from the asset's
    rated power, and flip status to COMPLETE. Idempotent — calling it again on an
    already-COMPLETE row returns the stored kwh without recomputing."""
    try:
        row = db.get(MachineDailyKwh, int(run_id))
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    asset = db.query(MtAsset).filter(MtAsset.asset_id == row.machine_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found in mt_asset_list")

    # Already stopped -> idempotent: return what we stored, don't recompute.
    if row.status == _COMPLETE and row.ended_at is not None:
        return RunStopResponse(
            run_id=str(row.id),
            ended_at=to_epoch_ms(row.ended_at) or req.ended_at,
            computed_kwh=float(row.daily_kwh or 0.0),
        )

    ended_at = from_epoch_ms(req.ended_at)
    started = row.started_at or ended_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    duration_hours = max(0.0, (ended_at - started).total_seconds() / 3600.0)
    rated_kw = parse_kw(asset.power_load)
    kwh = round(rated_kw * duration_hours * settings.power_factor, 3)

    row.ended_at = from_epoch_ms(req.ended_at)
    row.daily_kwh = kwh
    row.status = _COMPLETE
    row.updated_at = datetime.utcnow()
    db.commit()

    return RunStopResponse(run_id=str(row.id), ended_at=req.ended_at, computed_kwh=kwh)


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
            if r.started_at is not None and r.ended_at is not None:
                started = r.started_at.replace(tzinfo=timezone.utc) if r.started_at.tzinfo is None else r.started_at
                ended = r.ended_at.replace(tzinfo=timezone.utc) if r.ended_at.tzinfo is None else r.ended_at
                dh = max(0.0, (ended - started).total_seconds() / 3600.0)
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
