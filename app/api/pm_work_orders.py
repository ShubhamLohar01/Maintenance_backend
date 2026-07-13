"""Preventive-Maintenance WORK ORDERS — reads, the due-plan generator, the
execute→approve→QC lifecycle, and photo upload.

Generation is LAZY (mirrors app/api/asset_schedules.generate_due_rows): every
work-order list read first runs a sweep that turns any plan due within
`pm_generation_lead_days` into a NOTIFIED work order, snapshotting the plan's
checklist into the WO's `task_logs` JSONB. `POST /pm/work-orders/generate` forces
the same sweep (for a cron/manual trigger); no standalone worker process is needed.

Times are stored as readable naive-UTC DateTime and surfaced as epoch-ms on the wire.
`task_logs` and `spares` are JSONB on the work order (no child table). Photos use the
same S3 helper as breakdowns: uploaded via `POST /pm/photos` and referenced by URL
inside the submit task_logs / the QC checklist blob.
"""
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_rds
from ..models import MtPmPlan, MtPmWorkOrder, MtUser
from ..schemas import (
    PmWorkOrderDto, PmAckRequest, PmStartRequest, PmSubmitRequest,
    PmSupervisorApproveRequest, PmSupervisorRejectRequest, PmQcAckRequest,
    PmQcDecisionRequest, PmGenerateResponse, PmPhotoUploadResponse,
)
from ..auth import get_current_user
from ..storage import upload_bytes, image_ext_for
from ..config import settings
from .pm_common import (
    require_role, ms_to_naive, resolve_user_name, wo_to_dto, QC_ROLES, next_wo_code,
)

router = APIRouter(prefix="/pm", tags=["pm-work-orders"])

MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB
_OPEN_STATUSES_EXCLUDED = ["CLOSED", "CANCELLED"]  # a plan with any other WO is "open"


# --- photo upload (mirrors breakdowns._upload_photo) ------------------------

async def _upload_photo(photo: Optional[UploadFile], key: str) -> Optional[str]:
    """Validate + upload an optional image part to S3, returning its URL (None when no
    photo attached). type/size checked here so the client gets a clean 400. `key` is the
    S3 object key WITHOUT extension."""
    if photo is None or not (photo.filename or "").strip():
        return None
    content_type = (photo.content_type or "").strip().lower()
    ext = image_ext_for(content_type)
    if ext is None:
        raise HTTPException(status_code=400, detail="photo must be image/jpeg or image/png")
    data = await photo.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="photo must be <= 10 MB")
    if not data:
        return None
    return upload_bytes(f"{key}.{ext}", data, content_type)


def _get_wo(db: Session, wo_id: str) -> MtPmWorkOrder:
    wo = db.get(MtPmWorkOrder, wo_id)
    if wo is None:
        raise HTTPException(status_code=404, detail="work order not found")
    return wo


def _qc_blob(req: PmQcDecisionRequest, decision: str):
    """Build the qc_checklist JSONB. When the app sends its own `checklist` blob we
    store it verbatim; otherwise we synthesize a small record from the decider/notes so
    nothing is lost (there are no dedicated qc_decided_* columns in this schema)."""
    if req.checklist is not None:
        return req.checklist
    parts: dict = {"decision": decision}
    if req.user_id:
        parts["decided_by"] = req.user_id
    if req.user_name:
        parts["decided_by_name"] = req.user_name
    if req.notes:
        parts["notes"] = req.notes
    return parts


# --- generator --------------------------------------------------------------

def generate_due_work_orders(db: Session) -> int:
    """Turn every active plan due within the lead window into a NOTIFIED work order
    (unless it already has an open one), snapshotting the checklist into task_logs.
    Mirrors the app's PmSchedulerWorker. Idempotent; safe on every read. Returns the
    number of WOs inserted."""
    now = datetime.utcnow()
    lead = timedelta(days=settings.pm_generation_lead_days)
    plans = db.query(MtPmPlan).filter(MtPmPlan.is_active.is_(True)).all()

    inserted = 0
    for plan in plans:
        base = plan.last_completed_at or plan.created_at or now
        if (plan.trigger_type or "TIME").upper() == "USAGE":
            # USAGE (running-hours) integration deferred — mirror the app's 30-day fallback.
            next_due = base + timedelta(days=30)
        elif plan.last_completed_at is not None:
            # A cycle has completed — schedule from that completion.
            next_due = plan.last_completed_at + timedelta(days=plan.trigger_interval or 0)
        else:
            # FIRST cycle: honour the supervisor-chosen first due date the app stored in
            # next_due_at at plan creation (may be sooner than created_at + interval).
            # Fall back to created_at + interval when absent.
            next_due = plan.next_due_at or (base + timedelta(days=plan.trigger_interval or 0))

        if plan.next_due_at != next_due:
            plan.next_due_at = next_due  # keep the plan list's due date fresh

        if (next_due - now) > lead:
            continue  # too far out

        open_exists = (
            db.query(MtPmWorkOrder.id)
            .filter(
                MtPmWorkOrder.plan_id == plan.id,
                MtPmWorkOrder.status.not_in(_OPEN_STATUSES_EXCLUDED),
            )
            .first()
        )
        if open_exists is not None:
            continue  # a WO for this cycle is already in flight

        # Sequential human-readable id (WOAA001…), mirroring plan codes. next_wo_code
        # isn't race-proof on its own (two concurrent sweeps can read the same MAX), so
        # commit per work order and retry with a fresh code on a primary-key collision —
        # already-committed WOs from this sweep survive a late collision.
        for _ in range(5):
            wo_id = next_wo_code(db)
            task_logs = []
            for idx, it in enumerate(plan.items or []):
                if not isinstance(it, dict):
                    continue
                item_id = str(it.get("id") or idx)
                task_logs.append({
                    "id": f"log-{wo_id}-{item_id}",
                    "template_item_id": str(it.get("id")) if it.get("id") else None,
                    "order_index": int(it.get("order_index") or 0),
                    "title": str(it.get("title") or ""),
                    "description": str(it.get("description") or ""),
                    "expected_result": str(it.get("expected_result") or ""),
                    "requires_photo": bool(it.get("requires_photo")),
                    "requires_measurement": bool(it.get("requires_measurement")),
                    "measurement_unit": it.get("measurement_unit"),
                    "measurement_min": it.get("measurement_min"),
                    "measurement_max": it.get("measurement_max"),
                    "status": "PENDING",
                    "measurement_value": None,
                    "photo_url": None,
                    "notes": None,
                    "completed_at": None,
                    "completed_by": None,
                })

            db.add(MtPmWorkOrder(
                id=wo_id,
                plan_id=plan.id,
                machine_id=plan.machine_id,
                machine_name=plan.machine_name,
                template_name=plan.machine_name,   # plan/checklist name snapshot
                estimated_duration_minutes=0,
                scheduled_date=next_due,
                generated_at=now,
                status="NOTIFIED",
                assigned_technician_id=plan.assigned_technician_id,
                assigned_technician_name=resolve_user_name(db, plan.assigned_technician_id),
                task_logs=task_logs,
                spares=[],
                created_at=now,
                updated_at=now,
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                continue
            inserted += 1
            break

    # Commit any remaining next_due_at freshness updates for plans that didn't
    # generate a work order this sweep.
    db.commit()
    return inserted


# --- reads ------------------------------------------------------------------

@router.get("/work-orders", response_model=List[PmWorkOrderDto])
def list_work_orders(
    technician_id: Optional[str] = Query(None, description="= mt_users.id (the assignee)"),
    status: Optional[str] = Query(None, description="Comma-separated statuses, e.g. NOTIFIED,ACKNOWLEDGED,IN_PROGRESS"),
    plan_id: Optional[str] = Query(None),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Work orders, filtered by technician / status / plan. Runs the due-plan sweep
    first so newly-due WOs appear without a separate cron. Each WO includes its
    task_logs[] + spares[]. Any authenticated caller."""
    generate_due_work_orders(db)

    q = db.query(MtPmWorkOrder)
    if technician_id:
        q = q.filter(MtPmWorkOrder.assigned_technician_id == technician_id)
    if plan_id:
        q = q.filter(MtPmWorkOrder.plan_id == plan_id)
    if status:
        wanted = [s.strip().upper() for s in status.split(",") if s.strip()]
        if wanted:
            q = q.filter(MtPmWorkOrder.status.in_(wanted))
    rows = q.order_by(MtPmWorkOrder.scheduled_date.asc(), MtPmWorkOrder.id.asc()).all()
    return [wo_to_dto(w) for w in rows]


@router.post("/work-orders/generate", response_model=PmGenerateResponse)
def generate_now(
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Force a generation sweep (a cron or admin can hit this). The list endpoint
    already sweeps on read. Any authenticated caller. {generated: n}."""
    return PmGenerateResponse(generated=generate_due_work_orders(db))


@router.get("/work-orders/{wo_id}", response_model=PmWorkOrderDto)
def get_work_order(
    wo_id: str,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """One work order with its full task_logs[] + spares[]. 404 if unknown."""
    return wo_to_dto(_get_wo(db, wo_id))


# --- lifecycle: technician --------------------------------------------------

@router.post("/work-orders/{wo_id}/acknowledge", response_model=PmWorkOrderDto)
def acknowledge(
    wo_id: str,
    req: PmAckRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Technician acknowledges the notified WO -> ACKNOWLEDGED."""
    require_role(user, {"TECHNICIAN"})
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.status = "ACKNOWLEDGED"
    wo.acknowledged_at = ms_to_naive(req.at) or now
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


@router.post("/work-orders/{wo_id}/start", response_model=PmWorkOrderDto)
def start(
    wo_id: str,
    req: PmStartRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Technician starts the job -> IN_PROGRESS."""
    require_role(user, {"TECHNICIAN"})
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.status = "IN_PROGRESS"
    wo.started_at = ms_to_naive(req.at) or now
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


@router.post("/work-orders/{wo_id}/submit", response_model=PmWorkOrderDto)
def submit(
    wo_id: str,
    req: PmSubmitRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Technician submits the completed checklist -> SUBMITTED. Replaces task_logs with
    the submitted array (status/measurement/photo_url/notes) and stores the spares list.
    Photos are already-uploaded S3 URLs (see POST /pm/photos)."""
    require_role(user, {"TECHNICIAN"})
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.task_logs = [tl.model_dump() for tl in req.task_logs]
    wo.spares = [s.model_dump() for s in req.spares]
    wo.final_notes = req.final_notes or None
    wo.status = "SUBMITTED"
    wo.submitted_at = ms_to_naive(req.at) or now
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


# --- lifecycle: supervisor --------------------------------------------------

@router.post("/work-orders/{wo_id}/supervisor/approve", response_model=PmWorkOrderDto)
def supervisor_approve(
    wo_id: str,
    req: PmSupervisorApproveRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Supervisor approves the submitted WO -> PENDING_QC (moves to the QC inbox)."""
    require_role(user, {"SUPERVISOR"})
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.supervisor_approved_by = req.supervisor_id or str(user.id)
    wo.supervisor_approved_by_name = req.supervisor_name or resolve_user_name(db, req.supervisor_id, user.name)
    wo.supervisor_approved_at = ms_to_naive(req.at) or now
    wo.status = "PENDING_QC"
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


@router.post("/work-orders/{wo_id}/supervisor/reject", response_model=PmWorkOrderDto)
def supervisor_reject(
    wo_id: str,
    req: PmSupervisorRejectRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Supervisor sends the WO back to the technician -> IN_PROGRESS, with notes."""
    require_role(user, {"SUPERVISOR"})
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.supervisor_approved_by = req.supervisor_id or str(user.id)
    wo.supervisor_approved_by_name = req.supervisor_name or resolve_user_name(db, req.supervisor_id, user.name)
    wo.supervisor_rejected_at = now
    wo.supervisor_rejection_notes = req.notes or None
    wo.status = "IN_PROGRESS"
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


# --- lifecycle: QC ----------------------------------------------------------

@router.post("/work-orders/{wo_id}/qc/acknowledge", response_model=PmWorkOrderDto)
def qc_acknowledge(
    wo_id: str,
    req: PmQcAckRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """QC picks up an awaiting-QC WO -> stamps qc_acknowledged_* (status stays
    PENDING_QC through review, mirroring the breakdown QC pickup)."""
    require_role(user, QC_ROLES)
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.qc_acknowledged_by = req.user_id or str(user.id)
    wo.qc_acknowledged_by_name = req.user_name or resolve_user_name(db, req.user_id, user.name)
    wo.qc_acknowledged_at = ms_to_naive(req.at) or now
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


@router.post("/work-orders/{wo_id}/qc/override-acknowledge", response_model=PmWorkOrderDto)
def qc_override_acknowledge(
    wo_id: str,
    req: PmQcAckRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """QC_HEAD takes over an awaiting-QC WO even if a member already acknowledged it."""
    require_role(user, {"QC_HEAD"})
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    wo.qc_acknowledged_by = req.user_id or str(user.id)
    wo.qc_acknowledged_by_name = req.user_name or resolve_user_name(db, req.user_id, user.name)
    wo.qc_acknowledged_at = ms_to_naive(req.at) or now
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


@router.post("/work-orders/{wo_id}/qc/approve", response_model=PmWorkOrderDto)
def qc_approve(
    wo_id: str,
    req: PmQcDecisionRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """QC approves -> CLOSED (machine returns to service). Stores the sign-off blob in
    qc_checklist and advances the plan's schedule (last_completed_at = now, so the next
    cycle is scheduled from here). Any QC after-photo is uploaded via POST /pm/photos and
    referenced inside the checklist blob."""
    require_role(user, QC_ROLES)
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    # Capture who did QC even if they skipped the explicit acknowledge step.
    if not wo.qc_acknowledged_by:
        wo.qc_acknowledged_by = req.user_id or str(user.id)
        wo.qc_acknowledged_by_name = req.user_name or resolve_user_name(db, req.user_id, user.name)
        wo.qc_acknowledged_at = ms_to_naive(req.at) or now
    wo.qc_checklist = _qc_blob(req, "APPROVED")
    wo.closed_at = ms_to_naive(req.at) or now
    wo.status = "CLOSED"
    wo.updated_at = now

    plan = db.get(MtPmPlan, wo.plan_id)
    if plan is not None:
        plan.last_completed_at = now
        if (plan.trigger_type or "TIME").upper() != "USAGE":
            plan.next_due_at = now + timedelta(days=plan.trigger_interval or 0)
        plan.updated_at = now

    db.commit()
    return wo_to_dto(wo)


@router.post("/work-orders/{wo_id}/qc/disapprove", response_model=PmWorkOrderDto)
def qc_disapprove(
    wo_id: str,
    req: PmQcDecisionRequest,
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """QC disapproves -> back to SUBMITTED (returns to the supervisor's queue). The
    reason is kept in the qc_checklist blob."""
    require_role(user, QC_ROLES)
    wo = _get_wo(db, wo_id)
    now = datetime.utcnow()
    if not wo.qc_acknowledged_by:
        wo.qc_acknowledged_by = req.user_id or str(user.id)
        wo.qc_acknowledged_by_name = req.user_name or resolve_user_name(db, req.user_id, user.name)
        wo.qc_acknowledged_at = ms_to_naive(req.at) or now
    wo.qc_checklist = _qc_blob(req, "DISAPPROVED")
    wo.status = "SUBMITTED"
    wo.updated_at = now
    db.commit()
    return wo_to_dto(wo)


# --- photo upload -----------------------------------------------------------

@router.post("/photos", response_model=PmPhotoUploadResponse)
async def upload_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_rds),
    user: MtUser = Depends(get_current_user),
):
    """Upload one image (jpeg/png, <= 10 MB) to S3 and return its URL. The app calls this
    per task-log photo and for the QC after-photo, then references the returned URL in the
    submit / approve payloads. Same S3 storage as breakdowns."""
    url = await _upload_photo(file, f"pm/photos/{uuid.uuid4().hex}")
    if url is None:
        raise HTTPException(status_code=400, detail="file is required and must be a non-empty image")
    return PmPhotoUploadResponse(url=url)
