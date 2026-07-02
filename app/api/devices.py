"""POST /devices/token — register/refresh this device's FCM push token.

Part of the P2 push scaffolding: tokens are stored now, but nothing is sent until
settings.fcm_enabled is flipped (see app/notifications/fanout.py)."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtDeviceToken, MtUser
from ..schemas import DeviceTokenRequest, DeviceTokenResponse
from ..auth import get_current_user

router = APIRouter(tags=["devices"])


@router.post("/devices/token", response_model=DeviceTokenResponse)
def register_device_token(
    req: DeviceTokenRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Upsert on the (unique) token so a device re-registering updates in place; a
    user may have several devices. `user_id` defaults to the authenticated caller."""
    now = datetime.utcnow()
    row = db.query(MtDeviceToken).filter(MtDeviceToken.token == req.token).first()
    if row is None:
        row = MtDeviceToken(token=req.token, created_at=now)
        db.add(row)
    row.user_id = req.user_id or str(user.id)
    row.platform = req.platform or "android"
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return DeviceTokenResponse(id=row.id, user_id=row.user_id, platform=row.platform)
