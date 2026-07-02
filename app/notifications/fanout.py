"""FCM push fan-out (P2) — flag-gated scaffolding.

The Android app currently polls existing endpoints and computes its reminder
escalations on-device. When we move off polling we flip settings.fcm_enabled and
provide the Firebase service-account JSON; until then this module is inert:

- POST /devices/token keeps storing tokens (mt_device_tokens), but
- send() is a no-op while fcm_enabled is false (returns 0 without pushing), so we
  never double-notify a device that is also polling.

What is intentionally NOT here yet (held until we commit to server push): the
deadline-based escalation scheduler (Render Cron -> an escalation endpoint) and
the send-exactly-once ledger (mt_notifications_sent). This module only provides
the envelope shape, audience resolution, and the gated sender they will call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import MtDeviceToken, MtUser
from ..utils import building_for

log = logging.getLogger("factoryops.notifications")

# Notification types the client maps to its in-app renderer, grouped by category.
BREAKDOWN_TYPES = {"B1_NEW_BREAKDOWN", "B2_ACK_STALE", "B3_AWAITING_QC", "B4_REOPENED"}
PM_TYPES = {"P2_AWAITING_SUPERVISOR", "P3_SUPERVISOR_REJECTED",
            "P4_AWAITING_QC", "P5_QC_REJECTED"}

_CATEGORY_FOR = {**{t: "BREAKDOWN" for t in BREAKDOWN_TYPES},
                 **{t: "PM" for t in PM_TYPES}}
# Deep-link extra key the client reads to open the right screen.
_DEEPLINK_KEY = {"BREAKDOWN": "ticket_id", "PM": "pm_wo_id"}


@dataclass
class Notification:
    """One notification to fan out. `tier` is the escalation level (0 = first nudge,
    higher = escalated). `target_user_id` narrows to a single user when set."""
    type: str
    entity_id: str
    target_role: str
    title: str
    body: str
    tier: int = 0
    target_user_id: Optional[str] = None

    @property
    def category(self) -> str:
        return _CATEGORY_FOR.get(self.type, "BREAKDOWN")

    def envelope(self) -> dict:
        """The FCM *data* message (not notification-only). All values are strings —
        FCM data payloads are string->string — matching the client's parser."""
        category = self.category
        return {
            "type": self.type,
            "category": category,
            "entityId": self.entity_id,
            "targetRole": self.target_role,
            "targetUserId": self.target_user_id or "",
            "title": self.title,
            "body": self.body,
            "tier": str(self.tier),
            "deepLinkExtraKey": _DEEPLINK_KEY[category],
        }


def resolve_recipients(
    db: Session,
    target_role: str,
    building: Optional[str] = None,
    target_user_id: Optional[str] = None,
) -> List[MtUser]:
    """Recipients of a notification: the single user when `target_user_id` is set,
    otherwise every mt_user whose normalized role == target_role and whose plant
    matches `building` (mt_users.location is free-text, matched via building_for;
    building=None means all plants)."""
    role = (target_role or "").strip().upper()
    out: List[MtUser] = []
    for u in db.query(MtUser).all():
        if target_user_id is not None:
            if str(u.id) == str(target_user_id):
                out.append(u)
            continue
        if u.norm_role != role:
            continue
        if building is None or building_for(u.location) == building:
            out.append(u)
    return out


def tokens_for(db: Session, users: List[MtUser]) -> List[str]:
    """Every registered device token for the given users."""
    ids = [str(u.id) for u in users]
    if not ids:
        return []
    rows = db.query(MtDeviceToken).filter(MtDeviceToken.user_id.in_(ids)).all()
    return [r.token for r in rows]


def send(db: Session, notif: Notification, building: Optional[str] = None) -> int:
    """Resolve recipients and push `notif` as an FCM data message. Returns the
    number of device tokens targeted. No-op returning 0 while settings.fcm_enabled
    is false (the app still polls; live push would double-notify)."""
    if not settings.fcm_enabled:
        log.debug("FCM disabled — not sending %s for %s", notif.type, notif.entity_id)
        return 0
    users = resolve_recipients(db, notif.target_role, building, notif.target_user_id)
    tokens = tokens_for(db, users)
    if not tokens:
        return 0
    _push(tokens, notif.envelope())
    return len(tokens)


def _push(tokens: List[str], data: dict) -> None:
    """Send one FCM data message to many tokens. firebase-admin is imported lazily
    so the dependency is only required once FCM is actually enabled; if it's absent
    we log and skip rather than crash."""
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError:
        log.error("fcm_enabled but firebase-admin is not installed — skipping push")
        return
    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            credentials.Certificate(settings.fcm_credentials_file)
        )
    messaging.send_each_for_multicast(
        messaging.MulticastMessage(
            tokens=tokens,
            data={k: str(v) for k, v in data.items()},
        )
    )
