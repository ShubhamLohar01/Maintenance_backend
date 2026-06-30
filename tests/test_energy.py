"""/energy/runs/* — active runs contract + stale-run auto-close.

Runs live as rows in mt_machine_daily_kwh (status RUNNING -> COMPLETE).
"""

from datetime import datetime, timedelta, timezone

from app.models import MtAsset, MachineDailyKwh


def _asset(db, asset_id="A185-1", building="A-185", name="Sealer", power_load="5kw"):
    db.add(MtAsset(asset_id=asset_id, building=building, asset_name=name, power_load=power_load))


def _running(db, machine_id="A185-1", building="A-185", started_at=None, op="7", name="Amar"):
    started_at = started_at or datetime.utcnow()
    db.add(MachineDailyKwh(
        machine_id=machine_id, reading_date=started_at.date(), building=building,
        operator_id=op, operator_name=name, started_at=started_at,
        status="RUNNING", source="RUN",
    ))


def _ms(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_active_runs_includes_run_id_operator_and_epoch_millis(auth_client, db_session):
    _asset(db_session)
    started = datetime.utcnow() - timedelta(hours=2)
    _running(db_session, started_at=started, op="7", name="Amar Bahudar Yadav")
    db_session.commit()

    resp = auth_client.get("/energy/runs/active")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    it = items[0]
    assert it["asset_id"] == "A185-1"
    assert it["operator_id"] == "7"
    assert it["operator_name"] == "Amar Bahudar Yadav"
    assert it["building"] == "A-185"

    # started_at is epoch MILLIS (not seconds / ISO), matching /energy/runs/start
    assert isinstance(it["started_at"], int)
    assert it["started_at"] > 1_000_000_000_000          # millis, not seconds
    assert abs(it["started_at"] - _ms(started)) < 2000

    # run_id is present and is exactly the id you stop with
    rid = it["run_id"]
    assert rid
    stop = auth_client.post(f"/energy/runs/{rid}/stop", json={"ended_at": _ms(started) + 3_600_000})
    assert stop.status_code == 200, stop.text
    assert stop.json()["run_id"] == rid


def test_stale_run_auto_closed_on_active_poll(auth_client, db_session):
    _asset(db_session, power_load="5kw")
    started = datetime.utcnow() - timedelta(hours=115)   # the orphan
    _running(db_session, started_at=started)
    db_session.commit()

    resp = auth_client.get("/energy/runs/active")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []                              # orphan swept out of active

    row = db_session.query(MachineDailyKwh).one()
    assert row.status == "COMPLETE"
    assert row.ended_at is not None
    assert row.daily_kwh is not None
    capped_hours = (row.ended_at - row.started_at).total_seconds() / 3600.0
    assert abs(capped_hours - 16.0) < 0.01               # capped at max, not 115h


def test_fresh_run_not_auto_closed(auth_client, db_session):
    _asset(db_session)
    _running(db_session, started_at=datetime.utcnow() - timedelta(hours=2))
    db_session.commit()

    resp = auth_client.get("/energy/runs/active")
    assert len(resp.json()) == 1
    assert db_session.query(MachineDailyKwh).one().status == "RUNNING"


def test_close_stale_endpoint(auth_client, db_session):
    _asset(db_session)
    _running(db_session, started_at=datetime.utcnow() - timedelta(hours=20))
    db_session.commit()

    resp = auth_client.post("/energy/runs/close-stale")
    assert resp.status_code == 200, resp.text
    assert resp.json()["closed"] == 1
    assert db_session.query(MachineDailyKwh).one().status == "COMPLETE"


def test_active_runs_requires_auth_401(client):
    assert client.get("/energy/runs/active").status_code == 401
