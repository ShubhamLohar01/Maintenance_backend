"""CRUD for mt_users — the app-managed user directory.

HEAD (and ADMIN, via require_role's superuser bypass) may list/create/update/delete
users. `username` is unique and stored lowercased (login looks it up lowercased). There
is no password column — new users log in with the shared fixed password."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtUser
from ..schemas import MtUserDto, MtUserCreate, MtUserUpdate
from ..auth import get_current_user
from .pm_common import require_role

router = APIRouter(prefix="/mt-users", tags=["mt-users"])

# HEAD manages the user directory. ADMIN also passes (require_role superuser bypass).
_MANAGE_ROLES = {"HEAD"}


def _to_dto(u: MtUser) -> MtUserDto:
    return MtUserDto(
        id=u.id,
        emp_id=u.emp_id,
        name=u.name,
        location=u.location,
        contact_no=u.contact_no,
        email_id=u.email_id,
        role=u.role,
        username=u.username,
        created_at=u.created_at.isoformat() if u.created_at else None,
    )


def _clean(s: Optional[str]) -> Optional[str]:
    """Trim; blank -> None so optional columns stay null, not ''."""
    if s is None:
        return None
    s = s.strip()
    return s or None


@router.get("", response_model=List[MtUserDto])
def list_mt_users(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All users, ordered by name. HEAD/ADMIN only."""
    require_role(user, _MANAGE_ROLES)
    rows = db.query(MtUser).order_by(MtUser.name.asc()).all()
    return [_to_dto(r) for r in rows]


@router.get("/{user_id}", response_model=MtUserDto)
def get_mt_user(
    user_id: int,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    require_role(user, _MANAGE_ROLES)
    row = db.get(MtUser, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_dto(row)


@router.post("", response_model=MtUserDto, status_code=status.HTTP_201_CREATED)
def create_mt_user(
    payload: MtUserCreate,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    require_role(user, _MANAGE_ROLES)
    name = _clean(payload.name)
    username = (payload.username or "").strip().lower()
    if not name or not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name and username are required",
        )
    row = MtUser(
        emp_id=_clean(payload.emp_id),
        name=name,
        location=_clean(payload.location),
        contact_no=_clean(payload.contact_no),
        email_id=_clean(payload.email_id),
        role=_clean(payload.role),
        username=username,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already exists",
        )
    db.refresh(row)
    return _to_dto(row)


@router.put("/{user_id}", response_model=MtUserDto)
def update_mt_user(
    user_id: int,
    payload: MtUserUpdate,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    require_role(user, _MANAGE_ROLES)
    row = db.get(MtUser, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    name = _clean(payload.name)
    username = (payload.username or "").strip().lower()
    if not name or not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name and username are required",
        )
    row.emp_id = _clean(payload.emp_id)
    row.name = name
    row.location = _clean(payload.location)
    row.contact_no = _clean(payload.contact_no)
    row.email_id = _clean(payload.email_id)
    row.role = _clean(payload.role)
    row.username = username
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already exists",
        )
    db.refresh(row)
    return _to_dto(row)


@router.delete("/{user_id}", response_model=MtUserDto)
def delete_mt_user(
    user_id: int,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    require_role(user, _MANAGE_ROLES)
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    row = db.get(MtUser, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    dto = _to_dto(row)
    db.delete(row)
    db.commit()
    return dto
