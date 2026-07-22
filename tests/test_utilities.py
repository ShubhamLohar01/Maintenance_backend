"""/utilities/* — daily Diesel / Gas / Electricity / Water logs.

The app computes the derived values and sends them; the backend upserts on
(plant, reading_date) and stores what it receives. Plant spelling is normalized.
"""
from app.models import MtUtilityWater, MtUtilityDiesel


def test_water_upsert_stores_inputs_and_recomputed(login_as, db_session):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "water_rate": 24})
    c = login_as(role="TECHNICIAN", location="A-185")
    body = {
        "plant": "A185", "reading_date": "2026-04-01",         # compact plant spelling
        "water_meter_opening": 402.971, "water_meter_closing": 426.86,
        "water_rate": 999, "production_units": None,            # 999 must be ignored
        "remark": "ok",
    }
    r = c.post("/utilities/water", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["plant"] == "A-185"                              # normalized
    assert out["water_rate"] == 24                              # from config, not 999
    assert out["water_consumed"] == 23.889                      # 426.86 - 402.971
    assert round(out["daily_water_cost"], 2) == 573.34          # 23.889 * 24
    assert out["cost_per_unit"] is None                         # production None -> null
    assert isinstance(out["id"], int)

    row = db_session.query(MtUtilityWater).one()
    assert row.plant == "A-185"
    assert float(row.water_consumed) == 23.889


def test_upsert_is_idempotent_on_plant_and_date(login_as, db_session):
    login_as(role="SUPERVISOR", location="W-202").put(
        "/utilities/rates", json={"plant": "W-202", "water_rate": 24})
    c = login_as(role="TECHNICIAN", location="W-202")
    base = {"plant": "W-202", "reading_date": "2026-04-02",
            "water_meter_opening": 10, "water_meter_closing": 15}
    r1 = c.post("/utilities/water", json=base)
    # same plant+date, corrected reading -> should UPDATE the same row, not insert
    r2 = c.post("/utilities/water", json={**base, "water_meter_closing": 20})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]                   # same row
    assert db_session.query(MtUtilityWater).count() == 1
    assert float(db_session.query(MtUtilityWater).one().daily_water_cost) == 240.0  # (20-10)*24


def test_diesel_upsert_and_list_roundtrip(auth_client, db_session):
    body = {"plant": "A-185", "reading_date": "2026-04-01", "initial_kwh_reading": 71629,
            "final_kwh_reading": 71815, "start_dg_run_hour": 181.5, "stop_dg_run_hour": 181.5,
            "diesel_l_per_hour": 37.5, "diesel_rate": 95, "diesel_received_l": 140,
            "total_consumption": 186, "total_run_hour": 0, "total_diesel_l": 0, "total_fuel_cost": 0}
    assert auth_client.post("/utilities/diesel", json=body).status_code == 200
    assert db_session.query(MtUtilityDiesel).count() == 1

    lst = auth_client.get("/utilities/diesel?plant=A185&from=2026-04-01&to=2026-04-30").json()
    assert len(lst) == 1
    assert lst[0]["plant"] == "A-185"
    assert lst[0]["total_consumption"] == 186


def test_unknown_plant_400(auth_client, db_session):
    r = auth_client.post("/utilities/water", json={"plant": "Z-999", "reading_date": "2026-04-01"})
    assert r.status_code == 400
    assert "plant" in r.json()["detail"].lower()


def test_utilities_requires_auth_401(client):
    assert client.get("/utilities/water").status_code == 401


def test_reading_date_missing_400(auth_client):
    r = auth_client.post("/utilities/water", json={"plant": "A-185"})
    assert r.status_code == 400
    assert "reading_date" in r.json()["detail"].lower()


def test_reading_date_unparseable_400(auth_client):
    r = auth_client.post("/utilities/water", json={"plant": "A-185", "reading_date": "15th April"})
    assert r.status_code == 400
    assert "reading_date" in r.json()["detail"].lower()


def test_water_closing_less_than_opening_400(auth_client, db_session):
    body = {"plant": "A-185", "reading_date": "2026-04-05",
            "water_meter_opening": 100, "water_meter_closing": 50}
    r = auth_client.post("/utilities/water", json=body)
    assert r.status_code == 400
    assert db_session.query(MtUtilityWater).count() == 0


def test_diesel_run_hour_closing_less_than_opening_400(auth_client, db_session):
    body = {"plant": "A-185", "reading_date": "2026-04-05",
            "start_dg_run_hour": 200, "stop_dg_run_hour": 100}
    r = auth_client.post("/utilities/diesel", json=body)
    assert r.status_code == 400
    assert db_session.query(MtUtilityDiesel).count() == 0


def test_gas_closing_less_than_opening_400(auth_client):
    body = {"plant": "A-185", "reading_date": "2026-04-05",
            "gas_meter_opening": 500, "gas_meter_closing": 400}
    r = auth_client.post("/utilities/gas", json=body)
    assert r.status_code == 400


def test_electricity_closing_less_than_opening_400(auth_client):
    body = {"plant": "A-185", "reading_date": "2026-04-05",
            "energy_meter_opening_kwh": 500, "energy_meter_closing_kwh": 400}
    r = auth_client.post("/utilities/electricity", json=body)
    assert r.status_code == 400


def test_created_by_stamped_from_authenticated_user(auth_client, db_session):
    body = {"plant": "A-185", "reading_date": "2026-04-06",
            "water_meter_opening": 1, "water_meter_closing": 2}
    r = auth_client.post("/utilities/water", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["created_by"] == "tester"
    row = db_session.query(MtUtilityWater).filter_by(reading_date="2026-04-06").one()
    assert row.created_by == "tester"


def test_created_by_preserved_on_update_by_a_different_user(login_as, db_session):
    c = login_as(username="alice")
    body = {"plant": "A-185", "reading_date": "2026-04-07",
            "water_meter_opening": 1, "water_meter_closing": 2}
    c.post("/utilities/water", json=body)

    c2 = login_as(username="bob")
    r = c2.post("/utilities/water", json={**body, "water_meter_closing": 3})
    assert r.status_code == 200, r.text
    assert r.json()["created_by"] == "alice"                   # original creator preserved


def test_list_orders_by_reading_date_desc_then_id_desc(auth_client):
    auth_client.post("/utilities/water", json={"plant": "A-185", "reading_date": "2026-04-10",
                                                "water_meter_opening": 1, "water_meter_closing": 2})
    auth_client.post("/utilities/water", json={"plant": "W-202", "reading_date": "2026-04-10",
                                                "water_meter_opening": 1, "water_meter_closing": 2})
    auth_client.post("/utilities/water", json={"plant": "A-185", "reading_date": "2026-04-11",
                                                "water_meter_opening": 1, "water_meter_closing": 2})
    lst = auth_client.get("/utilities/water").json()
    assert [r["reading_date"] for r in lst] == ["2026-04-11", "2026-04-10", "2026-04-10"]
    assert lst[1]["plant"] == "W-202"                           # inserted 2nd of the tied pair -> higher id -> first
