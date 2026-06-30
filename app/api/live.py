from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MachineDailyKwh, MtUser, BreakdownRecord
from ..schemas import LiveMachineDto
from ..auth import get_current_user
from ..utils import iso_z, norm_plant, scoped_buildings

router = APIRouter(tags=["head"])


@router.get("/head/machines/live", response_model=List[LiveMachineDto])
def live_machines(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Each machine's current run state so a Head can see who's running what.
    Scoped to the caller's plant(s) — HEAD sees both A-185 and W-202. RUNNING when
    an open run exists (a mt_machine_daily_kwh row with status='RUNNING');
    PENDING_QC when the machine has a breakdown still awaiting QC; otherwise IDLE."""
    buildings = scoped_buildings(user)
    if not buildings:
        return []

    assets = (
        db.query(MtAsset)
        .filter(MtAsset.building.in_(buildings))
        .order_by(MtAsset.building, MtAsset.asset_name)
        .all()
    )

    # Machines with a breakdown not yet CLOSED -> PENDING_QC
    # (Production Start stays blocked until QC clears the breakdown).
    pending_qc = {
        r.machine_id
        for r in db.query(BreakdownRecord.machine_id)
        .filter(BreakdownRecord.status != "CLOSED")
        .all()
    }

    # Latest open run per machine (asc order -> last write wins = most recent start).
    # operator_name is stored on the row, so no mt_users join is needed.
    open_runs = (
        db.query(MachineDailyKwh)
        .filter(MachineDailyKwh.status == "RUNNING")
        .order_by(MachineDailyKwh.started_at.asc())
        .all()
    )
    run_by_machine = {r.machine_id: r for r in open_runs}

    out: List[LiveMachineDto] = []
    for a in assets:
        run = run_by_machine.get(a.asset_id) if a.asset_id else None
        if run is None:
            out.append(LiveMachineDto(
                machine_id=a.asset_id or "",
                name=a.asset_name,
                building=a.building,
                plant_id=norm_plant(a.building),
                status="PENDING_QC" if a.asset_id in pending_qc else "IDLE",
            ))
        else:
            out.append(LiveMachineDto(
                machine_id=a.asset_id or "",
                name=a.asset_name,
                building=a.building,
                plant_id=norm_plant(a.building),
                status="RUNNING",
                current_operator_id=run.operator_id,
                current_operator_name=run.operator_name,
                run_started_at=iso_z(run.started_at),
            ))
    return out
