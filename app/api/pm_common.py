"""Shared helpers for the Preventive-Maintenance endpoints (plans + work orders).

Kept in one place so pm_plans.py and pm_work_orders.py agree on role enforcement,
epoch-ms time handling, user-name resolution, and ORM -> DTO mapping.

The finalized RDS schema stores EVERY wall-clock field as BIGINT epoch-ms, and the
work order's checklist steps (`task_logs`) + `spares` as JSONB on the row — so there
is no boundary conversion and no child table to join. Times are read and written
verbatim as ints (matching the app's `Long`).
"""
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import MtUser, MtPmPlan, MtPmWorkOrder
from ..schemas import PmPlanDto, PmPlanItemDto, PmTaskLogDto, PmSpareDto, PmWorkOrderDto

DAY_MS = 86_400_000  # ms in a day — matches the app's Constants.DAY_MS

# QC covers whatever the free-text mt_users.role normalizes to. Existing data may
# hold a bare 'QC'; the spec splits it into QC_MEMBER / QC_HEAD. Accept all three
# for QC actions, and treat QC_HEAD as the only role that may override-acknowledge.
QC_ROLES = {"QC", "QC_MEMBER", "QC_HEAD"}


def now_ms() -> int:
    """Current time as epoch-ms (UTC) — the unit every PM *_at column stores."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def require_role(user: MtUser, allowed: Iterable[str]) -> None:
    """403 unless the caller's normalized role is in `allowed`. ADMIN is a superuser
    and always passes. The message names the required role(s) (shown to the app)."""
    role = user.norm_role
    allowed_set = set(allowed)
    if role == "ADMIN" or role in allowed_set:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"This action requires role: {', '.join(sorted(allowed_set))}",
    )


def resolve_user_name(db: Session, uid: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    """mt_users.id -> name (snapshot); `fallback` (e.g. a client-sent name) when the
    id is blank/unknown."""
    if uid and str(uid).isdigit():
        u = db.get(MtUser, int(uid))
        if u is not None:
            return u.name
    return fallback


# --- ORM -> DTO -------------------------------------------------------------

def plan_to_dto(p: MtPmPlan) -> PmPlanDto:
    return PmPlanDto(
        id=p.id,
        machine_id=p.machine_id,
        machine_name=p.machine_name,
        description=p.description or "",
        trigger_type=p.trigger_type or "TIME",
        trigger_interval=p.trigger_interval,
        next_due_at=p.next_due_at,
        last_completed_at=p.last_completed_at,
        assigned_technician_id=p.assigned_technician_id,
        is_active=bool(p.is_active),
        created_by=p.created_by,
        created_at=p.created_at,
        updated_at=p.updated_at,
        items=[PmPlanItemDto.model_validate(it) for it in (p.items or []) if isinstance(it, dict)],
    )


def wo_to_dto(wo: MtPmWorkOrder) -> PmWorkOrderDto:
    return PmWorkOrderDto(
        id=wo.id,
        plan_id=wo.plan_id,
        machine_id=wo.machine_id,
        machine_name=wo.machine_name,
        template_name=wo.template_name,
        estimated_duration_minutes=wo.estimated_duration_minutes or 0,
        scheduled_date=wo.scheduled_date,
        generated_at=wo.generated_at,
        status=wo.status or "NOTIFIED",
        assigned_technician_id=wo.assigned_technician_id,
        assigned_technician_name=wo.assigned_technician_name,
        acknowledged_at=wo.acknowledged_at,
        started_at=wo.started_at,
        submitted_at=wo.submitted_at,
        final_notes=wo.final_notes,
        supervisor_approved_by=wo.supervisor_approved_by,
        supervisor_approved_by_name=wo.supervisor_approved_by_name,
        supervisor_approved_at=wo.supervisor_approved_at,
        supervisor_rejected_at=wo.supervisor_rejected_at,
        supervisor_rejection_notes=wo.supervisor_rejection_notes,
        qc_acknowledged_by=wo.qc_acknowledged_by,
        qc_acknowledged_by_name=wo.qc_acknowledged_by_name,
        qc_acknowledged_at=wo.qc_acknowledged_at,
        qc_checklist=wo.qc_checklist,
        closed_at=wo.closed_at,
        created_at=wo.created_at,
        updated_at=wo.updated_at,
        task_logs=[PmTaskLogDto.model_validate(t) for t in (wo.task_logs or []) if isinstance(t, dict)],
        spares=[PmSpareDto.model_validate(s) for s in (wo.spares or []) if isinstance(s, dict)],
    )
