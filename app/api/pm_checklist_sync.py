"""Mirror a QC-closed PM work order into the controlled 50a/50b checklist document.

When a machine's PM is QC-closed, its row in the CURRENT period's auto-maintained DRAFT
document flips from UNSET to OK/NOT_OK (+ technician remark + close date). There is exactly
one canonical auto-doc per (warehouse, form, period), marked created_by='pm-auto';
concurrent closes are serialized with a Postgres advisory lock. Best-effort + idempotent
(latest-wins), so a later close for the same machine simply re-writes its cells.

50a = MONTHLY (period YYYY-MM); 50b = QUARTERLY (period YYYY-Qn).
"""
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import MtPmChecklistLink, MtPmWorkOrder, MtAsset, PreventiveMaintenanceDoc
from ..checklist_catalog import full_form_items, DOC_NO, is_after_maintenance

AUTO_MARKER = "pm-auto"


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _period_key(form_type: str, when: datetime) -> str:
    if form_type == "QUARTERLY":
        return f"{when.year}-Q{(when.month - 1) // 3 + 1}"   # e.g. 2026-Q3 (7 chars, fits `month`)
    return when.strftime("%Y-%m")


def _building(db: Session, asset_id: str) -> str:
    row = db.query(MtAsset.building).filter(MtAsset.asset_id == asset_id).first()
    return (row[0] if row else None) or "W-202"


def _find_or_create_doc(db: Session, warehouse: str, form: str, period: str) -> PreventiveMaintenanceDoc:
    doc = (
        db.query(PreventiveMaintenanceDoc)
        .filter(
            PreventiveMaintenanceDoc.created_by == AUTO_MARKER,
            PreventiveMaintenanceDoc.warehouse == warehouse,
            PreventiveMaintenanceDoc.month == period,
            PreventiveMaintenanceDoc.rows["form_type"].astext == form,
        )
        .first()
    )
    if doc is not None:
        return doc
    doc = PreventiveMaintenanceDoc(
        month=period,
        warehouse=warehouse,
        created_by=AUTO_MARKER,
        checked_by="",
        verified_by="",
        rows={
            "form_type": form,
            "doc_no": DOC_NO.get(form, ""),
            "status": "DRAFT",
            "checklist_date": "",
            "done_by": "",
            "checked_by": "",
            "verified_by": "",
            "remarks": "",
            "created_by": AUTO_MARKER,
            "plant_id": warehouse,
            "items": full_form_items(form),   # full form, every cell UNSET
        },
    )
    db.add(doc)
    db.flush()
    return doc


def _apply(doc: PreventiveMaintenanceDoc, link: MtPmChecklistLink, wo: MtPmWorkOrder, when: datetime) -> None:
    """Flip this machine's cells (matched by sr_no + equipment + checkpoint text).
    Maintenance checkpoints come from the technician's task logs; the 4 After-Maintenance
    checks come from the QC blob (`qc_checklist.after_maintenance`)."""
    # technician's maintenance results
    logs: dict[str, tuple] = {}
    for tl in (wo.task_logs or []):
        if isinstance(tl, dict):
            logs[_norm(tl.get("title"))] = (tl.get("status"), tl.get("notes"))
    # QC's after-maintenance results (blob shape from the app: {checklist:{after_maintenance:[...]}})
    after: dict[str, tuple] = {}
    blob = wo.qc_checklist if isinstance(wo.qc_checklist, dict) else {}
    inner = blob.get("checklist")
    am_src = (inner if isinstance(inner, dict) else blob).get("after_maintenance") or []
    for am in am_src:
        if isinstance(am, dict):
            after[_norm(am.get("checkpoint"))] = (am.get("status"), am.get("remarks"))

    def to_status(raw, current):
        s = (raw or "").upper()
        if s in ("OK", "PASS"):
            return "OK"
        if s in ("NOT_OK", "FAIL"):
            return "NOT_OK"
        return current

    rows = doc.rows or {}
    items = rows.get("items") or []
    date_iso = when.date().isoformat()
    changed = False
    for it in items:
        if it.get("sr_no") != link.sr_no or _norm(it.get("equipment")) != _norm(link.equipment):
            continue
        cp = it.get("checkpoint")
        src = after.get(_norm(cp)) if is_after_maintenance(cp) else logs.get(_norm(cp))
        if src is None:
            continue
        status, remarks = src
        it["status"] = to_status(status, it.get("status", "UNSET"))
        it["remarks"] = remarks or ""
        it["equipment_date"] = date_iso
        changed = True
    if changed:
        doc.rows = dict(rows)   # reassign so the JSONB column is flushed


def sync_wo_to_checklist(db: Session, wo: MtPmWorkOrder) -> None:
    """Called from qc_approve after the WO is CLOSED (same transaction, in a SAVEPOINT).
    No-op for machines that aren't linked to a checklist form."""
    links = db.query(MtPmChecklistLink).filter(MtPmChecklistLink.asset_id == wo.machine_id).all()
    if not links:
        return
    when = wo.closed_at or datetime.utcnow()
    warehouse = _building(db, wo.machine_id)
    for link in links:
        period = _period_key(link.form_type, when)
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{warehouse}|{link.form_type}|{period}"},
        )
        doc = _find_or_create_doc(db, warehouse, link.form_type, period)
        _apply(doc, link, wo, when)
        # Trace: record which checklist document this PM fed (last link wins if an asset
        # is on both the monthly and quarterly form).
        wo.checklist_doc_id = doc.id
