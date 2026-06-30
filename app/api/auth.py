from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtUser
from ..schemas import LoginRequest, LoginResponse
from ..auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

# mt_users has no password column yet — every user shares this password for now.
FIXED_PASSWORD = "pass123"


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_rds)):
    user = db.query(MtUser).filter(MtUser.username == req.username.strip().lower()).first()
    if user is None or req.password.strip() != FIXED_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, expires_at = create_access_token(str(user.id), user.norm_role, user.plant_id)
    return LoginResponse(
        token=token,
        user_id=str(user.id),
        name=user.name,
        role=user.norm_role,
        plant_id=user.plant_id,
        expires_at=expires_at,
    )
