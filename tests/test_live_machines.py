"""GET /machines/live — Head's live machine list (who's running what)."""

from datetime import datetime, timedelta

from app.models import MtAsset, MachineDailyKwh


def _asset(db, asset_id, building, name):
    db.add(MtAsset(asset_id=asset_id, building=building, asset_name=name))


def test_live_running_and_idle(auth_client, db_session):
    _asset(db_session, "A185-1", "A-185", "Band Sealer")
    _asset(db_session, "A185-2", "A-185", "Roaster")
    now = datetime.utcnow()
    db_session.add(MachineDailyKwh(  # running
        machine_id="A185-1", reading_date=now.date(), building="A-185",
        operator_id="7", operator_name="Ramesh K",
        started_at=now - timedelta(hours=1), status="RUNNING"))
    db_session.add(MachineDailyKwh(  # completed -> idle
        machine_id="A185-2", reading_date=now.date(), building="A-185",
        operator_id="7", operator_name="Ramesh K",
        started_at=now - timedelta(hours=5), ended_at=now - timedelta(hours=4),
        status="COMPLETE", daily_kwh=3))
    db_session.commit()

    resp = auth_client.get("/head/machines/live")
    assert resp.status_code == 200, resp.text
    rows = {r["machine_id"]: r for r in resp.json()}

    assert rows["A185-1"]["status"] == "RUNNING"
    assert rows["A185-1"]["current_operator_id"] == "7"
    assert rows["A185-1"]["current_operator_name"] == "Ramesh K"
    assert rows["A185-1"]["run_started_at"] is not None
    assert rows["A185-1"]["plant_id"] == "A185"
    assert rows["A185-1"]["building"] == "A-185"

    assert rows["A185-2"]["status"] == "IDLE"
    assert rows["A185-2"]["current_operator_id"] is None
    assert rows["A185-2"]["current_operator_name"] is None
    assert rows["A185-2"]["run_started_at"] is None


def test_live_non_head_scoped_to_own_plant(login_as, db_session):
    _asset(db_session, "A185-1", "A-185", "Band Sealer")
    _asset(db_session, "W202-1", "W-202", "Capper")
    db_session.commit()
    c = login_as(role="OPERATOR", location="A-185")
    resp = c.get("/head/machines/live")
    assert resp.status_code == 200
    assert {r["machine_id"] for r in resp.json()} == {"A185-1"}


def test_live_head_sees_both_plants(auth_client, db_session):
    _asset(db_session, "A185-1", "A-185", "Band Sealer")
    _asset(db_session, "W202-1", "W-202", "Capper")
    db_session.commit()
    resp = auth_client.get("/head/machines/live")
    assert {r["machine_id"] for r in resp.json()} == {"A185-1", "W202-1"}


def test_live_supervisor_sees_both_plants(login_as, db_session):
    _asset(db_session, "A185-1", "A-185", "Band Sealer")
    _asset(db_session, "W202-1", "W-202", "Capper")
    db_session.commit()
    c = login_as(role="SUPERVISOR", location="A-185")
    resp = c.get("/head/machines/live")
    assert resp.status_code == 200
    assert {r["machine_id"] for r in resp.json()} == {"A185-1", "W202-1"}


def test_live_technician_scoped_to_own_plant(login_as, db_session):
    _asset(db_session, "A185-1", "A-185", "Band Sealer")
    _asset(db_session, "W202-1", "W-202", "Capper")
    db_session.commit()
    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.get("/head/machines/live")
    assert resp.status_code == 200
    assert {r["machine_id"] for r in resp.json()} == {"A185-1"}


def test_live_requires_auth_401(client):
    assert client.get("/head/machines/live").status_code == 401
