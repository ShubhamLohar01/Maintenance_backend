"""In-process daily scheduler — a real, unattended trigger for the Schedule Electric
Assets sweep, replacing "whoever happens to open that screen next" (see
app/api/asset_schedules.generate_due_rows for the sweep itself).

Runs INSIDE the FastAPI web process via APScheduler (no separate cron service, no new
auth surface — it calls the Python function directly, not over HTTP). Started/stopped
from app/main.py's startup/shutdown hooks.

Reliability note: if the host process is asleep at the scheduled hour (e.g. a
free/idle-sleep hosting tier), the job simply fires once the process next wakes up,
within `_MISFIRE_GRACE_SECONDS` of the scheduled time — it is never silently dropped
past that window. Even a fully missed day is not lost data: generate_due_rows() is
idempotent and lazily backfills any elapsed-but-unrecorded day on the next call, exactly
as it already does today on a manual GET /asset-schedules. This scheduler only removes
the dependency on a human opening that screen; it does not replace the safety net.
"""
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .database import SessionRds

log = logging.getLogger("uvicorn.error")

IST = ZoneInfo("Asia/Kolkata")
_JOB_ID = "asset_schedule_daily_sweep"
_MISFIRE_GRACE_SECONDS = 6 * 3600  # still fire up to 6h late if the process was asleep

_scheduler: BackgroundScheduler | None = None


def _run_asset_schedule_sweep() -> None:
    """The actual job body: one throwaway RDS session, one sweep, always closed."""
    from .api.asset_schedules import generate_due_rows  # local import: avoid import-time cycle with main

    db = SessionRds()
    try:
        n = generate_due_rows(db)
        log.info("scheduler: asset-schedule sweep generated %d row(s)", n)
    except Exception:  # noqa: BLE001 — a failed sweep must not crash the scheduler thread
        log.exception("scheduler: asset-schedule sweep failed")
    finally:
        db.close()


def start_scheduler() -> None:
    """Start the background scheduler (no-op if already running or disabled).
    Called once from main.py's startup hook."""
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("scheduler: disabled (settings.scheduler_enabled=false) — skipping start")
        return
    if _scheduler is not None:
        return

    sched = BackgroundScheduler(timezone=IST)
    sched.add_job(
        _run_asset_schedule_sweep,
        trigger=CronTrigger(hour=settings.scheduler_hour_ist, minute=0, timezone=IST),
        id=_JOB_ID,
        replace_existing=True,
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
        coalesce=True,  # if multiple fires were missed, run once (not once-per-missed-fire)
        max_instances=1,
    )
    sched.start()
    _scheduler = sched
    log.info(
        "scheduler: started — asset-schedule sweep daily at %02d:00 IST",
        settings.scheduler_hour_ist,
    )


def stop_scheduler() -> None:
    """Stop the background scheduler (no-op if not running). Called from main.py's
    shutdown hook so the process exits cleanly instead of hanging on a live thread."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler: stopped")
