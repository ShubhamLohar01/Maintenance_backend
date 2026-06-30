from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Machine, User, UserMachineAssignment
from ..schemas import MachineDto
from ..auth import get_current_user
from ..utils import to_epoch_ms

router = APIRouter(prefix="/machines", tags=["machines"])


def _to_dto(m: Machine) -> MachineDto:
    return MachineDto(
        id=m.id,
        code=m.code,
        name=m.name,
        location=m.location,
        plant_id=m.plant_id,
        rated_kw=m.rated_kw,
        load_factor=m.load_factor,
        load_factor_source=m.load_factor_source,
        criticality=m.criticality,
        expected_run_hours=m.expected_run_hours,
        current_status=m.current_status,
        category=m.category,
        building=m.building,
        sub_location=m.sub_location,
        updated_at=to_epoch_ms(m.updated_at) or 0,
    )


@router.get("/assigned", response_model=List[MachineDto])
def get_assigned(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Returns all machines assigned to the current operator.

    If there are no assignment rows for this user, fall back to **all** machines
    in the user's plant — useful for the dev seed where every operator should
    see the full machine list.
    """
    q = (
        db.query(Machine)
        .join(UserMachineAssignment, UserMachineAssignment.machine_id == Machine.id)
        .filter(UserMachineAssignment.user_id == user.id)
    )
    machines = q.all()
    if not machines:
        machines = db.query(Machine).filter(Machine.plant_id == user.plant_id).all()
    return [_to_dto(m) for m in machines]
