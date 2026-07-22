"""Supervisor Reports — GET /reports/machines + GET /reports/floor-readings.

Read-only historical listings (no aggregation): machines reading mirrors
mt_machine_daily_kwh rows directly, floor readings mirrors
mt_floor_utility_readings rows directly. Both default to the last 30 days,
newest first, and scope by plant the same way every other supervisor-facing
endpoint does (scoped_buildings — SUPERVISOR/HEAD see both, narrowed by an
explicit ?plant=; OPERATOR/TECHNICIAN always see only their own plant).
"""
from datetime import datetime, date, timedelta

from app.models import MtAsset, MachineDailyKwh, MtFloorUtilityReading


def _kwh_row(db, machine_id, building, on, kwh, asset_name="Sealer", floor="1st floor",
             operator_name="Tester", status="COMPLETE", source="RUN"):
    db.add(MachineDailyKwh(
        machine_id=machine_id, building=building, floor=floor, asset_name=asset_name,
        reading_date=on, daily_kwh=kwh, status=status, source=source,
        operator_name=operator_name, started_at=datetime(on.year, on.month, on.day, 8),
        ended_at=datetime(on.year, on.month, on.day, 10),
    ))


def _floor_row(db, building, floor, on, meter_reading, daily_kwh):
    db.add(MtFloorUtilityReading(
        building=building, floor=floor, reading_date=on,
        meter_reading=meter_reading, daily_kwh=daily_kwh,
    ))


def test_machines_reading_defaults_to_last_30_days(login_as, db_session):
    today = date.today()
    _kwh_row(db_session, "A185-1", "A-185", today, 10)
    _kwh_row(db_session, "A185-1", "A-185", today - timedelta(days=29), 5)
    _kwh_row(db_session, "A185-1", "A-185", today - timedelta(days=31), 999)  # outside window
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    resp = c.get("/reports/machines")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 2
    assert {r["daily_kwh"] for r in rows} == {10.0, 5.0}
    assert rows[0]["reading_date"] == today.isoformat()   # newest first


def test_machines_reading_plant_filter(login_as, db_session):
    today = date.today()
    _kwh_row(db_session, "A185-1", "A-185", today, 10)
    _kwh_row(db_session, "W202-1", "W-202", today, 20)
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    resp = c.get("/reports/machines", params={"plant": "A185"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["building"] == "A-185"


def test_machines_reading_explicit_date_range(login_as, db_session):
    _kwh_row(db_session, "A185-1", "A-185", date(2026, 6, 1), 10)
    _kwh_row(db_session, "A185-1", "A-185", date(2026, 6, 15), 20)
    _kwh_row(db_session, "A185-1", "A-185", date(2026, 7, 1), 30)
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    resp = c.get("/reports/machines", params={"from": "2026-06-01", "to": "2026-06-30"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert {r["daily_kwh"] for r in rows} == {10.0, 20.0}


def test_machines_reading_bad_date_400(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="both")
    assert c.get("/reports/machines", params={"from": "not-a-date"}).status_code == 400
    assert c.get("/reports/machines", params={"to": "not-a-date"}).status_code == 400


def test_machines_reading_from_after_to_400(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="both")
    resp = c.get("/reports/machines", params={"from": "2026-07-10", "to": "2026-07-01"})
    assert resp.status_code == 400


def test_machines_reading_operator_scoped_to_own_plant(login_as, db_session):
    today = date.today()
    _kwh_row(db_session, "A185-1", "A-185", today, 10)
    _kwh_row(db_session, "W202-1", "W-202", today, 20)
    db_session.commit()

    # TECHNICIAN in A-185 must see only A-185, even without passing ?plant=
    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.get("/reports/machines")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["building"] == "A-185"


def test_machines_reading_backfills_asset_name_for_legacy_rows(login_as, db_session):
    db_session.add(MtAsset(asset_id="A185-1", building="A-185", asset_name="Legacy Sealer"))
    today = date.today()
    _kwh_row(db_session, "A185-1", "A-185", today, 10, asset_name=None)
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    resp = c.get("/reports/machines")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"][0]["asset_name"] == "Legacy Sealer"


def test_machines_reading_row_shape(login_as, db_session):
    today = date.today()
    _kwh_row(db_session, "A185-1", "A-185", today, 10.5, asset_name="Sealer",
              floor="1st floor", operator_name="Karan", status="COMPLETE", source="RUN")
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    row = c.get("/reports/machines").json()["rows"][0]
    assert row["machine_id"] == "A185-1"
    assert row["asset_name"] == "Sealer"
    assert row["floor"] == "1st floor"
    assert row["operator_name"] == "Karan"
    assert row["status"] == "COMPLETE"
    assert row["source"] == "RUN"
    assert isinstance(row["started_at"], int)
    assert isinstance(row["ended_at"], int)


def test_floor_readings_report_basic(login_as, db_session):
    today = date.today()
    _floor_row(db_session, "A-185", "Ground floor", today, 100.5, 12.0)
    _floor_row(db_session, "W-202", "Terrace", today, 50.0, 9.0)
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    resp = c.get("/reports/floor-readings", params={"plant": "A185"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["building"] == "A-185"
    assert rows[0]["floor"] == "Ground floor"
    assert rows[0]["meter_reading"] == 100.5
    assert rows[0]["daily_kwh"] == 12.0


def test_floor_readings_report_defaults_to_last_30_days(login_as, db_session):
    today = date.today()
    _floor_row(db_session, "A-185", "Ground floor", today, 10, 10)
    _floor_row(db_session, "A-185", "Ground floor", today - timedelta(days=45), 999, 999)
    db_session.commit()

    c = login_as(role="SUPERVISOR", location="both")
    rows = c.get("/reports/floor-readings").json()["rows"]
    assert len(rows) == 1
    assert rows[0]["meter_reading"] == 10.0


def test_reports_require_auth_401(client):
    assert client.get("/reports/machines").status_code == 401
    assert client.get("/reports/floor-readings").status_code == 401
