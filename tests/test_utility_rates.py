"""/utilities/rates — supervisor-managed current prices (one row per plant).

Only SUPERVISOR/HEAD/ADMIN may PUT; any authenticated user may GET (the
technician app reads these to display the read-only price).
"""


def test_set_and_get_rates_as_supervisor(login_as):
    sup = login_as(role="SUPERVISOR", location="A-185")
    r = sup.put("/utilities/rates", json={"plant": "A185", "diesel_rate": 100, "gas_rate": 30})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["plant"] == "A-185"          # normalized
    assert out["diesel_rate"] == 100
    assert out["gas_rate"] == 30
    assert out["set_by"] == "tester"        # StubUser default username

    got = sup.get("/utilities/rates?plant=A-185").json()
    assert len(got) == 1
    assert got[0]["diesel_rate"] == 100


def test_set_rates_forbidden_for_technician(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    r = tech.put("/utilities/rates", json={"plant": "A-185", "diesel_rate": 50})
    assert r.status_code == 403


def test_technician_may_read_rates(login_as):
    login_as(role="SUPERVISOR").put("/utilities/rates", json={"plant": "W-202", "water_rate": 24})
    tech = login_as(role="TECHNICIAN", location="W-202")
    got = tech.get("/utilities/rates?plant=W-202").json()
    assert got[0]["water_rate"] == 24


def test_set_rates_partial_update_keeps_other_rates(login_as):
    sup = login_as(role="SUPERVISOR")
    sup.put("/utilities/rates", json={"plant": "W-202", "diesel_rate": 90, "gas_rate": 30})
    sup.put("/utilities/rates", json={"plant": "W-202", "diesel_rate": 92})   # only diesel
    row = sup.get("/utilities/rates?plant=W-202").json()[0]
    assert row["diesel_rate"] == 92
    assert row["gas_rate"] == 30            # untouched


def test_set_rates_empty_body_400(login_as):
    sup = login_as(role="SUPERVISOR")
    r = sup.put("/utilities/rates", json={"plant": "A-185"})
    assert r.status_code == 400


def test_get_rates_all_plants(login_as):
    sup = login_as(role="SUPERVISOR")
    sup.put("/utilities/rates", json={"plant": "A-185", "diesel_rate": 95})
    sup.put("/utilities/rates", json={"plant": "W-202", "diesel_rate": 97})
    got = login_as(role="TECHNICIAN").get("/utilities/rates").json()
    assert {r["plant"] for r in got} == {"A-185", "W-202"}


def test_diesel_submit_uses_supervisor_rate_and_recomputes(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "diesel_rate": 100})
    tech = login_as(role="TECHNICIAN", location="A-185")
    body = {"plant": "A-185", "reading_date": "2026-05-01",
            "initial_kwh_reading": 71629, "final_kwh_reading": 71815,
            "start_dg_run_hour": 100, "stop_dg_run_hour": 110,
            "diesel_l_per_hour": 37.5,
            "diesel_rate": 1,            # bogus — must be ignored
            "total_fuel_cost": 999999}   # bogus — must be recomputed
    out = tech.post("/utilities/diesel", json=body).json()
    assert out["diesel_rate"] == 100         # from config, not the body
    assert out["total_consumption"] == 186   # 71815 - 71629
    assert out["total_run_hour"] == 10       # 110 - 100
    assert out["total_diesel_l"] == 375      # 37.5 * 10
    assert out["total_fuel_cost"] == 37500   # 375 * 100


def test_water_cost_per_unit_null_when_production_zero(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "water_rate": 24})
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.post("/utilities/water", json={
        "plant": "A-185", "reading_date": "2026-05-02",
        "water_meter_opening": 10, "water_meter_closing": 20,
        "production_units": 0}).json()
    assert out["water_consumed"] == 10
    assert out["daily_water_cost"] == 240    # 10 * 24
    assert out["cost_per_unit"] is None       # div-by-zero -> null


def test_submit_with_no_config_rate_stores_null_cost(login_as):
    # No rate set for W-202 -> rate overridden to null -> cost null.
    tech = login_as(role="TECHNICIAN", location="W-202")
    out = tech.post("/utilities/water", json={
        "plant": "W-202", "reading_date": "2026-05-03",
        "water_meter_opening": 10, "water_meter_closing": 20,
        "water_rate": 999, "daily_water_cost": 999}).json()
    assert out["water_rate"] is None
    assert out["water_consumed"] == 10        # consumption still computed
    assert out["daily_water_cost"] is None


def test_prefill_uses_last_actual_closing_across_skipped_day(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "water_rate": 24})
    tech = login_as(role="TECHNICIAN", location="A-185")
    tech.post("/utilities/water", json={"plant": "A-185", "reading_date": "2026-06-01",
                                        "water_meter_opening": 10, "water_meter_closing": 20})
    # 2026-06-02 skipped; open the 2026-06-03 form
    out = tech.get("/utilities/water/prefill?plant=A-185&date=2026-06-03").json()
    assert out["openings"]["water_meter_opening"] == 20   # previous closing
    assert out["source_date"] == "2026-06-01"
    assert out["rate"] == 24


def test_prefill_diesel_maps_both_opening_fields(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    tech.post("/utilities/diesel", json={"plant": "A-185", "reading_date": "2026-06-01",
                                         "initial_kwh_reading": 100, "final_kwh_reading": 150,
                                         "start_dg_run_hour": 5, "stop_dg_run_hour": 9})
    out = tech.get("/utilities/diesel/prefill?plant=A-185&date=2026-06-02").json()
    assert out["openings"]["initial_kwh_reading"] == 150   # <- final
    assert out["openings"]["start_dg_run_hour"] == 9       # <- stop


def test_prefill_null_when_no_earlier_row(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.get("/utilities/water/prefill?plant=A-185&date=2026-06-01").json()
    assert out["openings"]["water_meter_opening"] is None
    assert out["source_date"] is None


def test_prefill_unknown_utility_404(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    assert tech.get("/utilities/plutonium/prefill?plant=A-185").status_code == 404


def test_gas_submit_uses_supervisor_rate_and_recomputes(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "gas_rate": 10})
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.post("/utilities/gas", json={
        "plant": "A-185", "reading_date": "2026-05-04",
        "gas_meter_opening": 100, "gas_meter_closing": 200,
        "gas_conversion_factor": 1.5,
        "gas_rate": 999, "daily_gas_cost": 999999}).json()   # bogus — must be recomputed
    assert out["gas_rate"] == 10                              # from config, not the body
    assert out["gas_consumed_m3"] == 150                      # (200 - 100) * 1.5
    assert out["daily_gas_cost"] == 1500                      # 150 * 10


def test_electricity_submit_uses_supervisor_rate_and_recomputes(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "electricity_rate": 8})
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.post("/utilities/electricity", json={
        "plant": "A-185", "reading_date": "2026-05-05",
        "energy_meter_opening_kwh": 1000, "energy_meter_closing_kwh": 1100,
        "ct_multiplier": 4,
        "energy_meter_opening_kvah": 2000, "energy_meter_closing_kvah": 2100,
        "electricity_rate": 999, "daily_electricity_cost": 999999}).json()  # bogus
    assert out["electricity_rate"] == 8                       # from config, not the body
    assert out["electricity_consumed_kwh"] == 400             # (1100 - 1000) * 4
    assert out["electricity_consumed_kvah"] == 100            # 2100 - 2000 (no ct multiplier)
    assert out["daily_electricity_cost"] == 3200              # 400 * 8


def test_cost_per_unit_computed_when_production_positive(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "electricity_rate": 8})
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.post("/utilities/electricity", json={
        "plant": "A-185", "reading_date": "2026-05-06",
        "energy_meter_opening_kwh": 1000, "energy_meter_closing_kwh": 1100,
        "ct_multiplier": 4,
        "production_units": 200}).json()
    assert out["daily_electricity_cost"] == 3200              # 400 * 8
    assert out["cost_per_unit"] == 16                         # 3200 / 200 (division branch)
