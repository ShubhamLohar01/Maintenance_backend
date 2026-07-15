"""app/scheduler.py — the in-process daily trigger for the asset-schedule sweep.

Tests the WIRING (job registered, correct trigger time, start/stop idempotent,
disabled flag honored) — not the sweep's own logic (that's test_asset_schedules.py)
and not an actual 21:00 fire (impractical/flaky to wait for in a test).
"""
import app.scheduler as scheduler_module
from app.config import settings


def teardown_function(_):
    # Always leave the module-global scheduler stopped between tests.
    scheduler_module.stop_scheduler()


def test_start_scheduler_registers_daily_job_at_configured_hour():
    settings.scheduler_enabled = True
    settings.scheduler_hour_ist = 21
    try:
        scheduler_module.start_scheduler()
        sched = scheduler_module._scheduler
        assert sched is not None
        job = sched.get_job(scheduler_module._JOB_ID)
        assert job is not None
        # CronTrigger fields expose the configured hour/minute.
        field_map = {f.name: str(f) for f in job.trigger.fields}
        assert field_map["hour"] == "21"
        assert field_map["minute"] == "0"
    finally:
        settings.scheduler_enabled = False  # restore the test-suite default


def test_start_scheduler_respects_configured_hour():
    settings.scheduler_enabled = True
    settings.scheduler_hour_ist = 9
    try:
        scheduler_module.start_scheduler()
        job = scheduler_module._scheduler.get_job(scheduler_module._JOB_ID)
        field_map = {f.name: str(f) for f in job.trigger.fields}
        assert field_map["hour"] == "9"
    finally:
        settings.scheduler_enabled = False
        settings.scheduler_hour_ist = 21  # restore default


def test_start_scheduler_noop_when_disabled():
    settings.scheduler_enabled = False
    scheduler_module.start_scheduler()
    assert scheduler_module._scheduler is None


def test_start_scheduler_idempotent():
    settings.scheduler_enabled = True
    try:
        scheduler_module.start_scheduler()
        first = scheduler_module._scheduler
        scheduler_module.start_scheduler()  # second call must not replace/duplicate
        assert scheduler_module._scheduler is first
    finally:
        settings.scheduler_enabled = False


def test_stop_scheduler_clears_and_is_safe_when_not_running():
    settings.scheduler_enabled = True
    try:
        scheduler_module.start_scheduler()
        assert scheduler_module._scheduler is not None
        scheduler_module.stop_scheduler()
        assert scheduler_module._scheduler is None
        scheduler_module.stop_scheduler()  # calling again must not raise
        assert scheduler_module._scheduler is None
    finally:
        settings.scheduler_enabled = False


def test_app_boot_does_not_start_scheduler_in_test_suite():
    """conftest.py sets scheduler_enabled=False before importing app.main — confirms
    that guard actually holds (no test accidentally flips it back on and leaves it)."""
    assert settings.scheduler_enabled is False
    assert scheduler_module._scheduler is None
