"""User roster reads — currently just the role-filtered list used by the PM
plan editor to pick an assigned technician. mt_users.role is free-text managed in
pgAdmin, so filtering is done on the normalized (trimmed, uppercased) role."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtUser
from ..schemas import UserRosterDto
from ..auth import get_current_user

router = APIRouter(tags=["users"])


@router.get("/users", response_model=List[UserRosterDto])
def list_users(
    role: Optional[str] = Query(None, description="Filter by role, e.g. TECHNICIAN (any spelling/case)"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All users, optionally filtered by role (normalized compare so 'technician',
    'Technician ', 'TECHNICIAN' all match `role=TECHNICIAN`). Any authenticated
    caller. Returns id/name/role/plant_id snapshots the app displays."""
    wanted = (role or "").strip().upper()
    rows = db.query(MtUser).order_by(MtUser.name.asc()).all()
    out: List[UserRosterDto] = []
    for u in rows:
        if wanted and u.norm_role != wanted:
            continue
        out.append(UserRosterDto(
            id=str(u.id),
            name=u.name,
            role=u.norm_role,
            plant_id=u.plant_id,
        ))
    return out
