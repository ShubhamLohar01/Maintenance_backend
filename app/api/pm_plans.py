"""Preventive-Maintenance PLANS — CRUD for the supervisor's plan editor.

A plan = a checklist bound to one asset + a recurring schedule + an assigned
technician. Ids are server-generated on create ('PLANAA001', sequential; legacy rows
keep their old 'plan-<uuid>'), and creation is idempotent on `client_ref` (the app's
local uuid) so an offline re-sync never duplicates. Writes are SUPERVISOR-only; reads
are open to any authenticated caller. DELETE is a soft-delete (is_active=false) so
historical work orders that reference the plan stay intact.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtAsset, MtPmPlan, MtUser
from ..schemas import PmPlanRequest, PmPlanDto
from ..auth import get_current_user
from .pm_common import require_role, ms_to_naive, resolve_user_name, plan_to_dto, next_plan_code

router = APIRouter(prefix="/pm/plans", tags=["pm-plans"])


def _validate(req: PmPlanRequest, db: Session) -> None:
    """Reject bad plans with a clean 400 (rather than letting a DB CHECK 500)."""
    if (req.trigger_type or "").upper() not in ("TIME", "USAGE"):
        raise HTTPException(status_code=400, detail="trigger_type must be TIME or USAGE")
    if req.trigger_interval is None or req.trigger_interval < 1:
        raise HTTPException(status_code=400, detail="trigger_interval must be >= 1")
    if not (req.machine_id or "").strip():
        raise HTTPException(status_code=400, detail="machine_id is required")
    if not (req.assigned_technician_id or "").strip():
        raise HTTPException(status_code=400, detail="assigned_technician_id is required")
    asset = db.query(MtAsset).filter(MtAsset.asset_id == req.machine_id).first()
    if asset is None:
        raise HTTPException(status_code=400, detail=f"machine_id {req.machine_id} not found in mt_asset_list")


def _apply(req: PmPlanRequest, plan: MtPmPlan, user: MtUser, creating: bool, db: Session) -> None:
    now = datetime.utcnow()
    plan.machine_id = req.machine_id
    plan.machine_name = req.machine_name
    plan.description = req.description or ""
    plan.items = [it.model_dump() for it in req.items]
    plan.trigger_type = (req.trigger_type or "TIME").upper()
    plan.trigger_interval = req.trigger_interval
    # epoch-ms from the app -> naive-UTC datetime; fall back to created_at/now if omitted.
    plan.next_due_at = ms_to_naive(req.next_due_at) or ms_to_naive(req.created_at) or now
    plan.last_completed_at = ms_to_naive(req.last_completed_at)
    plan.assigned_technician_id = req.assigned_technician_id
    # Name ALWAYS comes from the real mt_users directory — never app-supplied/seed.
    # (null if the id isn't a real mt_users row, which flags bad data to fix there.)
    plan.assigned_technician_name = resolve_user_name(db, req.assigned_technician_id)
    plan.is_active = req.is_active
    plan.updated_at = now
    if creating:
        plan.created_at = ms_to_naive(req.created_at) or now
        plan.created_by = user.username  # authoritative — the logged-in supervisor


@router.post("", response_model=PmPlanDto, status_code=201)
def create_plan(
    req: PmPlanRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Create a plan. The backend assigns the id (server-generated 'PLANAA001…'); any
    `id` in the body is ignored. Idempotent on `client_ref` (the app's local uuid): a
    re-post with a client_ref that already exists updates that plan instead of making a
    duplicate — so a lost-response retry is safe. SUPERVISOR only."""
    require_role(user, {"SUPERVISOR"})
    _validate(req, db)

    # Offline re-sync: same client_ref -> update the existing plan (no duplicate).
    if req.client_ref:
        existing = db.query(MtPmPlan).filter(MtPmPlan.client_ref == req.client_ref).first()
        if existing is not None:
            _apply(req, existing, user, creating=False, db=db)
            db.commit()
            db.refresh(existing)
            return plan_to_dto(existing)

    # New plan: assign the next sequential code. next_plan_code isn't race-proof on its
    # own, so on the rare concurrent-insert primary-key collision we re-read and retry.
    for _ in range(5):
        plan = MtPmPlan(id=next_plan_code(db), client_ref=req.client_ref or None)
        _apply(req, plan, user, creating=True, db=db)
        db.add(plan)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(plan)
        return plan_to_dto(plan)

    raise HTTPException(status_code=503, detail="could not allocate a plan id, please retry")


@router.get("", response_model=List[PmPlanDto])
def list_plans(
    include_inactive: bool = Query(False, description="Include soft-deleted (is_active=false) plans"),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """All plans, newest first. Soft-deleted plans are hidden unless
    include_inactive=true. Any authenticated caller."""
    q = db.query(MtPmPlan)
    if not include_inactive:
        q = q.filter(MtPmPlan.is_active.is_(True))
    rows = q.order_by(MtPmPlan.created_at.desc(), MtPmPlan.id.desc()).all()
    return [plan_to_dto(p) for p in rows]


@router.get("/{plan_id}", response_model=PmPlanDto)
def get_plan(
    plan_id: str,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """One plan (incl. soft-deleted, so the editor can still open it). 404 if unknown."""
    plan = db.get(MtPmPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan_to_dto(plan)


@router.put("/{plan_id}", response_model=PmPlanDto)
def update_plan(
    plan_id: str,
    req: PmPlanRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Replace a plan's checklist / schedule / assignment. SUPERVISOR only. The path
    id wins over any id in the body. 404 if unknown."""
    require_role(user, {"SUPERVISOR"})
    plan = db.get(MtPmPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    _validate(req, db)
    _apply(req, plan, user, creating=False, db=db)
    db.commit()
    db.refresh(plan)
    return plan_to_dto(plan)


@router.delete("/{plan_id}", response_model=PmPlanDto)
def delete_plan(
    plan_id: str,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Soft-delete: sets is_active=false so the plan stops generating work orders but
    its history (and any work orders that reference it) is preserved. SUPERVISOR only."""
    require_role(user, {"SUPERVISOR"})
    plan = db.get(MtPmPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    plan.is_active = False
    plan.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return plan_to_dto(plan)
