"""/energy/runs/* — one daily row per (machine, date); runs stored as segments.

A machine started/stopped/paused/resumed on the same calendar day accumulates into
ONE mt_machine_daily_kwh row via child mt_machine_run_segment rows (one per start->stop).
The run_id returned by /start is the SEGMENT id, which /stop closes.
"""

from datetime import datetime, timedelta, timezone

from app.models import MtAsset, MachineDailyKwh, MtMachineRunSegment


def _asset(db, asset_id="A185-1", building="A-185", name="Sealer",
           power_load="5kw", condition=None):
    db.add(MtAsset(asset_id=asset_id, building=building, asset_name=name,
                   power_load=power_load, condition=condition))
    db.commit()


def _ms(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _start(client, machine_id="A185-1", started=None, crid="c-1"):
    started = started or datetime.utcnow()
    return client.post("/energy/runs/start", json={
        "machine_id": machine_id, "started_at": _ms(started),
        "client_run_id": crid, "scheduled_end_at": _ms(started) + 3_600_000})


def _stop(client, run_id, ended):
    return client.post(f"/energy/runs/{run_id}/stop", json={"ended_at": _ms(ended)})


def test_start_creates_one_daily_row_and_active_lists_stoppable_run(auth_client, db_session):
    _asset(db_session)
    started = datetime.utcnow() - timedelta(hours=2)
    r = _start(auth_client, started=started, crid="c-1")
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    # exactly one daily row + one open segment; run_id IS the segment id
    assert db_session.query(MachineDailyKwh).count() == 1
    seg = db_session.query(MtMachineRunSegment).one()
    assert seg.status == "RUNNING"
    assert str(seg.id) == run_id

    items = auth_client.get("/energy/runs/active").json()
    assert len(items) == 1
    it = items[0]
    assert it["asset_id"] == "A185-1"
    assert it["run_id"] == run_id                        # stoppable id
    assert it["operator_name"] == "Tester"
    assert it["building"] == "A-185"
    # started_at is epoch MILLIS (not seconds / ISO)
    assert isinstance(it["started_at"], int)
    assert it["started_at"] > 1_000_000_000_000
    assert abs(it["started_at"] - _ms(started)) < 2000

    assert db_session.query(MachineDailyKwh).one().asset_name == "Sealer"  # denormalized snapshot

    stop = _stop(auth_client, run_id, started + timedelta(hours=1))
    assert stop.status_code == 200, stop.text
    assert stop.json()["run_id"] == run_id


def test_pause_resume_accumulates_into_one_daily_row(auth_client, db_session):
    _asset(db_session, power_load="10kw")
    base = datetime(2026, 6, 27, 8, 0, 0)
    # segment 1: 08:00 -> 09:00
    r1 = _start(auth_client, started=base, crid="s1")
    _stop(auth_client, r1.json()["run_id"], base + timedelta(hours=1))
    # segment 2 (same machine, same day): 10:00 -> 12:00
    r2 = _start(auth_client, started=base + timedelta(hours=2), crid="s2")
    _stop(auth_client, r2.json()["run_id"], base + timedelta(hours=4))

    rows = db_session.query(MachineDailyKwh).all()
    assert len(rows) == 1                                 # ONE daily row, not two
    row = rows[0]
    assert row.status == "COMPLETE"

    segs = db_session.query(MtMachineRunSegment).order_by(MtMachineRunSegment.id).all()
    assert len(segs) == 2
    # daily kWh is the SUM of the segments' kWh
    assert abs(float(row.daily_kwh) - (float(segs[0].kwh) + float(segs[1].kwh))) < 1e-6
    # earliest start / latest end of the day preserved
    assert row.started_at == base
    assert row.ended_at == base + timedelta(hours=4)


def test_history_run_hours_sum_segments_excludes_idle_gap(auth_client, db_session):
    _asset(db_session, power_load="10kw")
    base = datetime(2026, 6, 27, 8, 0, 0)
    r1 = _start(auth_client, started=base, crid="s1")
    _stop(auth_client, r1.json()["run_id"], base + timedelta(hours=4))      # 4h
    r2 = _start(auth_client, started=base + timedelta(hours=6), crid="s2")  # 2h idle gap
    _stop(auth_client, r2.json()["run_id"], base + timedelta(hours=10))     # 4h

    frm, to = _ms(base - timedelta(days=1)), _ms(base + timedelta(days=1))
    hist = auth_client.get(f"/energy/machines/A185-1/history?from={frm}&to={to}").json()
    assert len(hist) == 1
    # 4h + 4h = 8h of actual run time, NOT the 10h wall-clock span (gap excluded)
    assert abs(hist[0]["total_run_hours"] - 8.0) < 0.01


def test_start_idempotent_on_client_run_id(auth_client, db_session):
    _asset(db_session)
    base = datetime.utcnow()
    r1 = _start(auth_client, started=base, crid="dup")
    r2 = _start(auth_client, started=base, crid="dup")          # replayed sync
    assert r1.json()["run_id"] == r2.json()["run_id"]           # same segment
    assert db_session.query(MtMachineRunSegment).count() == 1   # not double-opened
    assert db_session.query(MachineDailyKwh).count() == 1


def test_stop_idempotent_no_double_add(auth_client, db_session):
    _asset(db_session, power_load="10kw")
    base = datetime(2026, 6, 27, 8, 0, 0)
    rid = _start(auth_client, started=base, crid="s1").json()["run_id"]
    s1 = _stop(auth_client, rid, base + timedelta(hours=2))
    s2 = _stop(auth_client, rid, base + timedelta(hours=2))     # replayed stop
    assert s1.json()["computed_kwh"] == s2.json()["computed_kwh"]
    row = db_session.query(MachineDailyKwh).one()
    assert abs(float(row.daily_kwh) - s1.json()["computed_kwh"]) < 1e-6   # added once


def test_stale_segment_auto_closed_on_active_poll(auth_client, db_session):
    _asset(db_session, power_load="5kw")
    started = datetime.utcnow() - timedelta(hours=115)          # the orphan
    assert _start(auth_client, started=started, crid="orphan").status_code == 200

    resp = auth_client.get("/energy/runs/active")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []                                    # orphan swept out of active

    seg = db_session.query(MtMachineRunSegment).one()
    assert seg.status == "COMPLETE"
    assert seg.ended_at is not None
    capped_hours = (seg.ended_at - seg.started_at).total_seconds() / 3600.0
    assert abs(capped_hours - 16.0) < 0.01                      # capped at max, not 115h
    row = db_session.query(MachineDailyKwh).one()
    assert row.status == "COMPLETE"
    assert row.daily_kwh is not None


def test_fresh_segment_not_auto_closed(auth_client, db_session):
    _asset(db_session)
    _start(auth_client, started=datetime.utcnow() - timedelta(hours=2), crid="fresh")
    resp = auth_client.get("/energy/runs/active")
    assert len(resp.json()) == 1
    assert db_session.query(MtMachineRunSegment).one().status == "RUNNING"
    assert db_session.query(MachineDailyKwh).one().status == "RUNNING"


def test_close_stale_endpoint(auth_client, db_session):
    _asset(db_session)
    _start(auth_client, started=datetime.utcnow() - timedelta(hours=20), crid="stale20")
    resp = auth_client.post("/energy/runs/close-stale")
    assert resp.status_code == 200, resp.text
    assert resp.json()["closed"] == 1
    assert db_session.query(MtMachineRunSegment).one().status == "COMPLETE"
    assert db_session.query(MachineDailyKwh).one().status == "COMPLETE"


def test_run_start_rejected_on_shut_down_asset(auth_client, db_session):
    """Server-side defense-in-depth: production must not start on a machine the
    supervisor marked "Shut Down" (condition sentinel), even via a direct API call."""
    _asset(db_session, asset_id="A185-9", power_load="5kw", condition="Shut Down")
    resp = _start(auth_client, machine_id="A185-9", crid="c-1")
    assert resp.status_code == 409, resp.text
    assert "shut down" in resp.json()["detail"].lower()
    assert db_session.query(MachineDailyKwh).count() == 0       # no daily row created
    assert db_session.query(MtMachineRunSegment).count() == 0   # no segment created


def test_active_runs_requires_auth_401(client):
    assert client.get("/energy/runs/active").status_code == 401
