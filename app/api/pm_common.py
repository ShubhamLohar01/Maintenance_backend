"""Shared helpers for the Preventive-Maintenance endpoints (plans + work orders).

Kept in one place so pm_plans.py and pm_work_orders.py agree on role enforcement,
time handling, user-name resolution, and ORM -> DTO mapping.

Storage vs wire: the DB columns are readable naive-UTC DateTime (timestamp), but the
app speaks epoch-ms (`Long`). So we convert AT THE BOUNDARY — `ms_to_naive` on the way
in, `to_epoch_ms` on the way out — and the JSON contract stays epoch-ms. The work
order's checklist steps (`task_logs`) + `spares` are JSONB on the row (no child table).
"""
from datetime import datetime
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import MtUser, MtPmPlan, MtPmWorkOrder
from ..schemas import PmPlanDto, PmPlanItemDto, PmTaskLogDto, PmSpareDto, PmWorkOrderDto
from ..utils import to_epoch_ms, from_epoch_ms

# QC covers whatever the free-text mt_users.role normalizes to. Existing data may
# hold a bare 'QC'; the spec splits it into QC_MEMBER / QC_HEAD. Accept all three
# for QC actions, and treat QC_HEAD as the only role that may override-acknowledge.
QC_ROLES = {"QC", "QC_MEMBER", "QC_HEAD"}


def ms_to_naive(ms: Optional[int]) -> Optional[datetime]:
    """epoch-ms (from the app) -> naive UTC datetime for the DB columns. Naive so it
    never mixes tz-aware/naive when compared against datetime.utcnow()."""
    if ms is None:
        return None
    return from_epoch_ms(ms).replace(tzinfo=None)


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
        next_due_at=to_epoch_ms(p.next_due_at),
        last_completed_at=to_epoch_ms(p.last_completed_at),
        assigned_technician_id=p.assigned_technician_id,
        assigned_technician_name=p.assigned_technician_name,
        is_active=bool(p.is_active),
        created_by=p.created_by,
        created_at=to_epoch_ms(p.created_at),
        updated_at=to_epoch_ms(p.updated_at),
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
        scheduled_date=to_epoch_ms(wo.scheduled_date),
        generated_at=to_epoch_ms(wo.generated_at),
        status=wo.status or "NOTIFIED",
        assigned_technician_id=wo.assigned_technician_id,
        assigned_technician_name=wo.assigned_technician_name,
        acknowledged_at=to_epoch_ms(wo.acknowledged_at),
        started_at=to_epoch_ms(wo.started_at),
        submitted_at=to_epoch_ms(wo.submitted_at),
        final_notes=wo.final_notes,
        supervisor_approved_by=wo.supervisor_approved_by,
        supervisor_approved_by_name=wo.supervisor_approved_by_name,
        supervisor_approved_at=to_epoch_ms(wo.supervisor_approved_at),
        supervisor_rejected_at=to_epoch_ms(wo.supervisor_rejected_at),
        supervisor_rejection_notes=wo.supervisor_rejection_notes,
        qc_acknowledged_by=wo.qc_acknowledged_by,
        qc_acknowledged_by_name=wo.qc_acknowledged_by_name,
        qc_acknowledged_at=to_epoch_ms(wo.qc_acknowledged_at),
        qc_checklist=wo.qc_checklist,
        closed_at=to_epoch_ms(wo.closed_at),
        created_at=to_epoch_ms(wo.created_at),
        updated_at=to_epoch_ms(wo.updated_at),
        task_logs=[PmTaskLogDto.model_validate(t) for t in (wo.task_logs or []) if isinstance(t, dict)],
        spares=[PmSpareDto.model_validate(s) for s in (wo.spares or []) if isinstance(s, dict)],
    )
