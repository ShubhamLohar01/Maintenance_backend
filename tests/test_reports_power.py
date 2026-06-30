"""GET /reports/power — per-warehouse energy aggregation for the Head Reports view."""

from datetime import date
from decimal import Decimal

from app.models import MtAsset, MachineDailyKwh


def _kwh(db, machine_id, building, d, kwh, floor="F1"):
    db.add(MachineDailyKwh(
        machine_id=machine_id, building=building, reading_date=d,
        daily_kwh=Decimal(str(kwh)), floor=floor,
    ))


def test_power_single_plant_aggregates(auth_client, db_session):
    db_session.add(MtAsset(asset_id="A185-1", building="A-185", asset_name="Sealer"))
    db_session.add(MtAsset(asset_id="A185-2", building="A-185", asset_name="Roaster"))
    _kwh(db_session, "A185-1", "A-185", date(2026, 6, 1), 10)
    _kwh(db_session, "A185-1", "A-185", date(2026, 6, 2), 5)
    _kwh(db_session, "A185-2", "A-185", date(2026, 6, 1), 20)
    _kwh(db_session, "A185-1", "A-185", date(2026, 5, 30), 99)  # out of range
    db_session.commit()

    resp = auth_client.get(
        "/reports/power",
        params={"plant_id": "A185", "from": "2026-06-01", "to": "2026-06-23"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plant_id"] == "A185"
    assert body["from"] == "2026-06-01"
    assert body["to"] == "2026-06-23"
    assert body["total_kwh"] == 35.0
    assert {d["date"]: d["kwh"] for d in body["by_day"]} == {
        "2026-06-01": 30.0, "2026-06-02": 5.0,
    }
    by_machine = {m["machine_id"]: m for m in body["by_machine"]}
    assert by_machine["A185-1"]["kwh"] == 15.0
    assert by_machine["A185-1"]["name"] == "Sealer"
    assert by_machine["A185-2"]["kwh"] == 20.0


def test_power_multi_plant_returns_array(auth_client, db_session):
    _kwh(db_session, "A185-1", "A-185", date(2026, 6, 1), 10)
    _kwh(db_session, "W202-1", "W-202", date(2026, 6, 1), 7)
    db_session.commit()

    resp = auth_client.get(
        "/reports/power",
        params={"plant_id": "A185,W202", "from": "2026-06-01", "to": "2026-06-23"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    by_plant = {p["plant_id"]: p for p in body}
    assert set(by_plant) == {"A185", "W202"}
    assert by_plant["A185"]["total_kwh"] == 10.0
    assert by_plant["W202"]["total_kwh"] == 7.0


def test_power_non_head_cannot_read_other_plant(login_as, db_session):
    _kwh(db_session, "A185-1", "A-185", date(2026, 6, 1), 10)
    _kwh(db_session, "W202-1", "W-202", date(2026, 6, 1), 7)
    db_session.commit()
    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.get(
        "/reports/power",
        params={"plant_id": "W202", "from": "2026-06-01", "to": "2026-06-23"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plant_id"] == "A185"      # forced to own plant
    assert body["total_kwh"] == 10.0


def test_power_bad_date_400(auth_client):
    resp = auth_client.get(
        "/reports/power",
        params={"plant_id": "A185", "from": "nope", "to": "2026-06-23"},
    )
    assert resp.status_code == 400


def test_power_requires_auth_401(client):
    resp = client.get(
        "/reports/power",
        params={"plant_id": "A185", "from": "2026-06-01", "to": "2026-06-23"},
    )
    assert resp.status_code == 401
