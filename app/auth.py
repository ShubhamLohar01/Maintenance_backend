from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .database import get_rds
from .models import MtUser

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_access_token(user_id: str, role: str, plant_id: str) -> tuple[str, int]:
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expires_hours)
    payload = {
        "sub": user_id,
        "role": role,
        "plant_id": plant_id,
        "exp": expires,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(expires.timestamp() * 1000)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_rds),
) -> MtUser:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = creds.credentials

    # Dev bypass — first user in mt_users
    if token == settings.dev_bypass_token:
        user = db.query(MtUser).first()
        if user is None:
            raise HTTPException(status_code=401, detail="No mt_users available")
        return user

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    try:
        user = db.get(MtUser, int(user_id))
    except (TypeError, ValueError):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
