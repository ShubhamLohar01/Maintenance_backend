"""Technician Daily Reading — GET /floor-readings/system + POST /floor-readings."""

from datetime import datetime, timedelta

from app.models import MtAsset, MachineDailyKwh, MtFloorUtilityReading


def _asset(db, asset_id, building, floor, name="M"):
    db.add(MtAsset(asset_id=asset_id, building=building, asset_name=name, sub_location=floor))


def _run(db, machine_id, building, floor, on, kwh):
    db.add(MachineDailyKwh(
        machine_id=machine_id, building=building, floor=floor, reading_date=on,
        status="COMPLETE", daily_kwh=kwh, started_at=datetime(on.year, on.month, on.day, 8),
    ))


def test_fetch_lists_all_building_floors_with_system_totals(login_as, db_session):
    on = datetime.utcnow().date()   # explicit date -> independent of the no-date default
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    _asset(db_session, "A185-2", "A-185", "1st floor")
    _asset(db_session, "A185-3", "A-185", "1st floor")   # same floor, second machine
    _asset(db_session, "W202-1", "W-202", "Terrace")     # other building — excluded
    # two completed runs on 1st floor -> summed; Ground floor idle -> 0
    _run(db_session, "A185-2", "A-185", "1st floor", on, 10)
    _run(db_session, "A185-3", "A-185", "1st floor", on, 5)
    db_session.commit()

    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.get("/floor-readings/system", params={"date": on.isoformat()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["building"] == "A-185"
    assert body["reading_date"] == on.isoformat()
    by_floor = {f["floor"]: f for f in body["floors"]}
    assert set(by_floor) == {"Ground floor", "1st floor"}   # only A-185 floors
    assert by_floor["1st floor"]["system_reading"] == 15.0
    assert by_floor["Ground floor"]["system_reading"] == 0.0
    assert by_floor["1st floor"]["meter_reading"] is None    # nothing saved yet


def test_fetch_with_no_date_defaults_to_yesterday_not_today(login_as, db_session):
    """A technician's morning round reports the PREVIOUS day's full consumption —
    today's isn't over yet, so the no-date default must be yesterday, not today."""
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    _asset(db_session, "A185-1", "A-185", "1st floor")
    _run(db_session, "A185-1", "A-185", "1st floor", yesterday, 20)  # yesterday's run
    _run(db_session, "A185-1", "A-185", "1st floor", today, 999)     # today's run -> must be ignored
    db_session.commit()

    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.get("/floor-readings/system")  # no ?date= -> should default to yesterday
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reading_date"] == yesterday.isoformat()
    assert body["floors"][0]["system_reading"] == 20.0


def test_submit_upserts_and_recomputes_system(login_as, db_session):
    on = datetime.utcnow().date()   # explicit reading_date -> independent of the no-date default
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    _asset(db_session, "A185-2", "A-185", "1st floor")
    _run(db_session, "A185-2", "A-185", "1st floor", on, 12)
    db_session.commit()

    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.post("/floor-readings", json={
        "reading_date": on.isoformat(),
        "rows": [
            {"floor": "Ground floor", "meter_reading": 100.5},
            {"floor": "1st floor", "meter_reading": 250.0},
        ]
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["saved"] == 2

    rows = {r.floor: r for r in db_session.query(MtFloorUtilityReading).all()}
    assert float(rows["Ground floor"].meter_reading) == 100.5
    assert float(rows["Ground floor"].daily_kwh) == 0.0      # system recomputed, no runs
    assert float(rows["1st floor"].meter_reading) == 250.0
    assert float(rows["1st floor"].daily_kwh) == 12.0        # system recomputed from runs

    # Re-submit same day overwrites (upsert on building/floor/date), no duplicate row
    resp2 = c.post("/floor-readings", json={
        "reading_date": on.isoformat(),
        "rows": [{"floor": "1st floor", "meter_reading": 260.0}],
    })
    assert resp2.status_code == 200
    again = db_session.query(MtFloorUtilityReading).filter_by(floor="1st floor").all()
    assert len(again) == 1
    assert float(again[0].meter_reading) == 260.0


def test_submit_with_no_reading_date_defaults_to_yesterday(login_as, db_session):
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    _asset(db_session, "A185-1", "A-185", "1st floor")
    db_session.commit()

    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.post("/floor-readings", json={"rows": [{"floor": "1st floor", "meter_reading": 42.0}]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["reading_date"] == yesterday.isoformat()
    saved = db_session.query(MtFloorUtilityReading).filter_by(floor="1st floor").one()
    assert saved.reading_date == yesterday


def test_fetch_echoes_saved_meter_reading(login_as, db_session):
    on = datetime.utcnow().date()
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    db_session.add(MtFloorUtilityReading(
        building="A-185", floor="Ground floor", reading_date=on,
        meter_reading=77.0, daily_kwh=0,
    ))
    db_session.commit()
    c = login_as(role="TECHNICIAN", location="A-185")
    body = c.get("/floor-readings/system", params={"date": on.isoformat()}).json()
    g = next(f for f in body["floors"] if f["floor"] == "Ground floor")
    assert g["meter_reading"] == 77.0


def test_head_get_defaults_to_first_building(login_as, db_session):
    # HEAD oversees both; GET (read-only) defaults to the first scoped plant so the
    # screen still loads. POST stays strict (see test_head_post_needs_building).
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    _asset(db_session, "W202-1", "W-202", "Terrace")
    db_session.commit()
    c = login_as(role="HEAD", location="both")
    resp = c.get("/floor-readings/system")
    assert resp.status_code == 200, resp.text
    assert resp.json()["building"] == "A-185"  # ALL_BUILDINGS order


def test_head_post_needs_building(login_as, db_session):
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    db_session.commit()
    c = login_as(role="HEAD", location="both")
    resp = c.post("/floor-readings", json={"rows": [{"floor": "Ground floor", "meter_reading": 1.0}]})
    assert resp.status_code == 400
    assert "building" in resp.json()["detail"].lower()


def test_descriptive_location_resolves(login_as, db_session):
    # Real mt_users.location values are descriptive, e.g. 'A-185-Koparkhairne'.
    on = datetime.utcnow().date()
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    _run(db_session, "A185-1", "A-185", "Ground floor", on, 4)
    db_session.commit()
    c = login_as(role="TECHNICIAN", location="A-185-Koparkhairne")
    resp = c.get("/floor-readings/system", params={"date": on.isoformat()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["building"] == "A-185"
    assert resp.json()["floors"][0]["system_reading"] == 4.0


def test_head_with_building_param_works(login_as, db_session):
    on = datetime.utcnow().date()
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    _asset(db_session, "W202-1", "W-202", "Terrace")
    _run(db_session, "W202-1", "W-202", "Terrace", on, 9)
    db_session.commit()
    c = login_as(role="HEAD", location="A-185")
    resp = c.get("/floor-readings/system", params={"building": "W202", "date": on.isoformat()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["building"] == "W-202"
    assert {f["floor"] for f in body["floors"]} == {"Terrace"}
    assert body["floors"][0]["system_reading"] == 9.0


def test_technician_bad_location_gets_clear_error(login_as, db_session):
    _asset(db_session, "A185-1", "A-185", "Ground floor")
    db_session.commit()
    c = login_as(role="TECHNICIAN", location="Head Office")  # not a plant code
    resp = c.get("/floor-readings/system")
    assert resp.status_code == 400
    assert "Head Office" in resp.json()["detail"]  # echoes the bad plant_id


def test_requires_auth_401(client):
    assert client.get("/floor-readings/system").status_code == 401
