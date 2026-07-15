"""Schedule Electric Assets: per-asset daily recording window on mt_asset_list,
lazy-backfilled into mt_machine_daily_kwh (source='SCHEDULE'). SUPERVISOR writes,
HEAD read-only. daily_kwh = rated_kw x window-hours x power_factor (0.99)."""
from datetime import datetime, date

import pytest

from app.models import MtAsset, MachineDailyKwh
from app.api.asset_schedules import generate_due_rows, IST


def _seed(db, asset_id="A185-LIGHT1", power="1000Watt", building="A-185",
          category="Electric Asset"):
    if db.query(MtAsset).filter(MtAsset.asset_id == asset_id).first() is None:
        db.add(MtAsset(
            asset_id=asset_id, asset_name="Tubelight", building=building,
            category=category, sub_location="LB", power_load=power,
        ))
        db.commit()
    return asset_id


def _set_schedule(db, asset_id, start_min, end_min, active=True,
                  last_generated=None, updated_at=datetime(2026, 7, 1, 10, 0),
                  power=None):
    a = db.query(MtAsset).filter(MtAsset.asset_id == asset_id).first()
    a.schedule_start_min = start_min
    a.schedule_end_min = end_min
    a.schedule_active = active
    a.schedule_last_generated = last_generated
    a.schedule_updated_at = updated_at
    if power is not None:
        a.power_load = power
    db.commit()
    return a


# ---- listing / read access -------------------------------------------------

def test_list_returns_only_electric_assets(auth_client, db_session):
    _seed(db_session, "A185-LIGHT1")
    _seed(db_session, "A185-MACH1", category="Machinery")
    rows = auth_client.get("/asset-schedules").json()
    ids = [r["asset_id"] for r in rows]
    assert "A185-LIGHT1" in ids
    assert "A185-MACH1" not in ids
    light = next(r for r in rows if r["asset_id"] == "A185-LIGHT1")
    assert light["active"] is False and light["start_min"] is None


# ---- permissions -----------------------------------------------------------

def test_head_cannot_write_403(auth_client, db_session):
    # auth_client default StubUser is HEAD
    _seed(db_session)
    r = auth_client.put("/asset-schedules/A185-LIGHT1",
                        json={"start_min": 600, "end_min": 1200, "active": True})
    assert r.status_code == 403


def test_supervisor_sets_and_reads_back(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="A-185")
    _seed(db_session, power="1000Watt")  # 1 kW
    r = c.put("/asset-schedules/A185-LIGHT1",
              json={"start_min": 600, "end_min": 1200, "active": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start_min"] == 600 and body["end_min"] == 1200
    assert body["active"] is True
    assert body["hours"] == 10.0
    assert body["est_daily_kwh"] == 9.9   # 1 kW * 10 h * 0.99


def test_labels_are_human_readable_12h(login_as, db_session):
    # Alongside the minute-of-day numbers, expose readable 12h AM/PM labels so the
    # DB/reports don't need to decode 600/1140 by hand. Derived, not stored.
    c = login_as(role="SUPERVISOR", location="A-185")
    _seed(db_session, power="1000Watt")
    body = c.put("/asset-schedules/A185-LIGHT1",
                 json={"start_min": 600, "end_min": 1140, "active": True}).json()
    assert body["start_label"] == "10:00 AM"
    assert body["end_label"] == "7:00 PM"


def test_labels_null_when_no_schedule(auth_client, db_session):
    _seed(db_session, "A185-LIGHT1")  # no window set
    light = next(r for r in auth_client.get("/asset-schedules").json()
                 if r["asset_id"] == "A185-LIGHT1")
    assert light["start_label"] is None and light["end_label"] is None


# ---- validation ------------------------------------------------------------

def test_bad_window_rejected(login_as, db_session):
    c = login_as(role="SUPERVISOR")
    _seed(db_session)
    assert c.put("/asset-schedules/A185-LIGHT1",
                 json={"start_min": 1200, "end_min": 600}).status_code == 400
    assert c.put("/asset-schedules/A185-LIGHT1",
                 json={"start_min": 600, "end_min": 600}).status_code == 400


def test_non_electric_asset_rejected(login_as, db_session):
    c = login_as(role="SUPERVISOR")
    _seed(db_session, "A185-MACH1", category="Machinery")
    assert c.put("/asset-schedules/A185-MACH1",
                 json={"start_min": 600, "end_min": 1200}).status_code == 400


def test_unknown_asset_404(login_as, db_session):
    c = login_as(role="SUPERVISOR")
    assert c.put("/asset-schedules/ZZZ-9",
                 json={"start_min": 600, "end_min": 1200}).status_code == 404


# ---- backfill generation ---------------------------------------------------

def test_backfill_generates_elapsed_days_only(db_session):
    _seed(db_session, power="1000Watt")
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, last_generated=date(2026, 7, 1))
    # 7/2, 7/3, 7/4 windows (end 20:00) all elapsed by 23:00 on 7/4; 7/5 not started.
    now = datetime(2026, 7, 4, 23, 0, tzinfo=IST)
    assert generate_due_rows(db_session, now=now) == 3
    rows = db_session.query(MachineDailyKwh).filter(
        MachineDailyKwh.source == "SCHEDULE").all()
    assert len(rows) == 3
    assert all(abs(float(r.daily_kwh) - 9.9) < 1e-6 for r in rows)
    assert {r.reading_date for r in rows} == {date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 4)}
    # high-water mark advanced
    a = db_session.query(MtAsset).filter(MtAsset.asset_id == "A185-LIGHT1").first()
    assert a.schedule_last_generated == date(2026, 7, 4)


def test_backfill_is_idempotent(db_session):
    _seed(db_session, power="1000Watt")
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, last_generated=date(2026, 7, 1))
    now = datetime(2026, 7, 4, 23, 0, tzinfo=IST)
    assert generate_due_rows(db_session, now=now) == 3
    assert generate_due_rows(db_session, now=now) == 0  # nothing new second time
    assert db_session.query(MachineDailyKwh).count() == 3


def test_today_not_recorded_until_window_ends(db_session):
    _seed(db_session, power="1000Watt")
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, last_generated=date(2026, 7, 1))
    # 7/2 window ends 20:00; at 19:00 IST on 7/2 nothing is fully elapsed yet.
    now = datetime(2026, 7, 2, 19, 0, tzinfo=IST)
    assert generate_due_rows(db_session, now=now) == 0


def test_paused_schedule_not_generated(db_session):
    _seed(db_session, power="1000Watt")
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, active=False,
                  last_generated=date(2026, 7, 1))
    now = datetime(2026, 7, 4, 23, 0, tzinfo=IST)
    assert generate_due_rows(db_session, now=now) == 0


def test_missing_power_load_skipped(db_session):
    _seed(db_session, power=None)
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, last_generated=date(2026, 7, 1))
    now = datetime(2026, 7, 4, 23, 0, tzinfo=IST)
    assert generate_due_rows(db_session, now=now) == 0


def test_power_load_change_only_affects_future_rows(db_session):
    _seed(db_session, power="1000Watt")  # 1 kW
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, last_generated=date(2026, 7, 1))
    assert generate_due_rows(db_session, now=datetime(2026, 7, 2, 23, 0, tzinfo=IST)) == 1
    # bump the rating; only rows generated AFTER this use the new value
    a = db_session.query(MtAsset).filter(MtAsset.asset_id == "A185-LIGHT1").first()
    a.power_load = "2000Watt"  # 2 kW
    db_session.commit()
    assert generate_due_rows(db_session, now=datetime(2026, 7, 3, 23, 0, tzinfo=IST)) == 1
    by_date = {r.reading_date: float(r.daily_kwh)
               for r in db_session.query(MachineDailyKwh).all()}
    assert abs(by_date[date(2026, 7, 2)] - 9.9) < 1e-6    # old rating kept
    assert abs(by_date[date(2026, 7, 3)] - 19.8) < 1e-6   # new rating


def test_clear_schedule_keeps_past_rows(login_as, db_session):
    c = login_as(role="SUPERVISOR")
    _seed(db_session, power="1000Watt")
    _set_schedule(db_session, "A185-LIGHT1", 600, 1200, last_generated=date(2026, 7, 1))
    generate_due_rows(db_session, now=datetime(2026, 7, 3, 23, 0, tzinfo=IST))
    before = db_session.query(MachineDailyKwh).count()
    assert before >= 1
    r = c.delete("/asset-schedules/A185-LIGHT1")
    assert r.status_code == 200
    assert r.json()["active"] is False and r.json()["start_min"] is None
    assert db_session.query(MachineDailyKwh).count() == before  # history untouched


def test_concurrent_sweeps_never_double_insert_same_day(db_session):
    """The real scenario this guards: the new 21:00 in-process cron (app/scheduler.py)
    and a lazy on-read sweep (GET /asset-schedules) can now genuinely run at the same
    moment, in two separate sessions. Both could pass the "does this row exist?"
    application-level check before either commits (TOCTOU). Calling the low-level
    insert twice with the SAME client_run_id in the SAME still-open transaction
    reproduces exactly that: the DB's UNIQUE constraint (not just app logic) is what
    actually stops the duplicate, and the second caller must lose gracefully — no
    crash, no second row — exactly like a losing concurrent sweep would."""
    from app.api.asset_schedules import _try_insert_schedule_row

    _seed(db_session, power="1000Watt")
    asset = db_session.query(MtAsset).filter(MtAsset.asset_id == "A185-LIGHT1").first()
    d = date(2026, 7, 5)
    started = datetime(2026, 7, 5, 4, 30)
    ended = datetime(2026, 7, 5, 14, 30)
    client_run_id = f"sched-{asset.asset_id}-{d.isoformat()}"

    winner = _try_insert_schedule_row(db_session, asset, d, 9.9, client_run_id, started, ended)
    loser = _try_insert_schedule_row(db_session, asset, d, 9.9, client_run_id, started, ended)
    db_session.commit()  # the outer transaction must still be healthy after the collision

    assert winner is True
    assert loser is False                        # lost the race — no exception raised
    rows = db_session.query(MachineDailyKwh).filter(
        MachineDailyKwh.client_run_id == client_run_id).all()
    assert len(rows) == 1                         # exactly one row — never doubled

    # The outer session/transaction is still usable afterward (the SAVEPOINT rollback
    # didn't poison the rest of the sweep for other assets/days).
    _seed(db_session, asset_id="A185-LIGHT2", power="1000Watt")
    asset2 = db_session.query(MtAsset).filter(MtAsset.asset_id == "A185-LIGHT2").first()
    ok = _try_insert_schedule_row(
        db_session, asset2, d, 5.0, f"sched-A185-LIGHT2-{d.isoformat()}", started, ended)
    db_session.commit()
    assert ok is True
    assert db_session.query(MachineDailyKwh).count() == 2


def test_client_run_id_is_unique_at_db_level(db_session):
    """The constraint itself — proves the safety net is a real DB guarantee, not just
    the application's "check then insert" logic (which alone is race-prone)."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(MachineDailyKwh(
        machine_id="A185-1", reading_date=date(2026, 7, 5), building="A-185",
        client_run_id="sched-A185-1-2026-07-05", status="COMPLETE",
        daily_kwh=1.0, source="SCHEDULE",
    ))
    db_session.commit()

    db_session.add(MachineDailyKwh(
        machine_id="A185-1", reading_date=date(2026, 7, 5), building="A-185",
        client_run_id="sched-A185-1-2026-07-05",  # same key -> must violate the constraint
        status="COMPLETE", daily_kwh=1.0, source="SCHEDULE",
    ))
    try:
        with pytest.raises(IntegrityError):
            db_session.commit()
    finally:
        db_session.rollback()
