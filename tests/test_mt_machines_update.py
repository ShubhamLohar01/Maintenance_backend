"""PUT /mt-machines/{asset_id} — editable asset register (Supervisor edits a
machine from its detail page and saves to mt_asset_list). Also covers GET
returning the `remarks` column the edit form pre-fills from."""

import pytest

from app.models import MtAsset

ENDPOINT = "/mt-machines"


def _seed_asset(db, **over):
    row = MtAsset(
        asset_id=over.get("asset_id", "W202-0092"),
        building=over.get("building", "W-202"),
        asset_name=over.get("asset_name", "Old name"),
        category=over.get("category", "Old cat"),
        sub_location=over.get("sub_location", "OLD"),
        quantity=over.get("quantity", 2),
        model_no=over.get("model_no", "OLD-MODEL"),
        serial_no=over.get("serial_no", "OLD-SN"),
        power_load=over.get("power_load", "4 KW"),
        condition=over.get("condition", "Fair"),
        assigned_to=over.get("assigned_to", None),
        remarks=over.get("remarks", "old remark"),
    )
    db.add(row)
    db.commit()
    return row


# Full body the app sends on every save (full update, not a patch).
def _full_body(**over):
    body = {
        "building": "W-202",
        "asset_name": "10 kg loose wt. Probe",
        "category": "Lab Equipment",
        "sub_location": "LAB",
        "quantity": 1,
        "model_no": "ABC-123",
        "serial_no": "SN-0099",
        "power_load": "120Watt",
        "condition": "Good",
        "remarks": "calibrated 2026-06",
    }
    body.update(over)
    return body


def test_put_updates_and_returns_full_row(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="SUPERVISOR", location="W-202")

    resp = c.put(f"{ENDPOINT}/W202-0092", json=_full_body())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["asset_id"] == "W202-0092"          # immutable path id echoed
    assert body["building"] == "W-202"
    assert body["asset_name"] == "10 kg loose wt. Probe"
    assert body["category"] == "Lab Equipment"
    assert body["sub_location"] == "LAB"
    assert body["quantity"] == 1
    assert body["model_no"] == "ABC-123"
    assert body["serial_no"] == "SN-0099"
    assert body["power_load"] == "120Watt"
    assert body["condition"] == "Good"
    assert body["remarks"] == "calibrated 2026-06"
    assert body["assigned_to"] is None
    # rated_kw is recomputed server-side from power_load (120 W -> 0.12 kW)
    assert body["rated_kw"] == pytest.approx(0.12)


def test_put_recomputes_rated_kw_from_power_load(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="SUPERVISOR")
    resp = c.put(f"{ENDPOINT}/W202-0092", json=_full_body(power_load="1.5kw"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["rated_kw"] == pytest.approx(1.5)


def test_put_persists_changes_to_db(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="SUPERVISOR")
    c.put(f"{ENDPOINT}/W202-0092", json=_full_body())

    row = db_session.query(MtAsset).filter(MtAsset.asset_id == "W202-0092").one()
    assert row.asset_name == "10 kg loose wt. Probe"
    assert row.building == "W-202"
    assert row.sub_location == "LAB"
    assert row.model_no == "ABC-123"
    assert row.serial_no == "SN-0099"
    assert row.remarks == "calibrated 2026-06"
    assert row.condition == "Good"
    assert row.quantity == 1


def test_put_404_when_asset_missing(login_as):
    c = login_as(role="SUPERVISOR")
    resp = c.put(f"{ENDPOINT}/NOPE-9999", json=_full_body())
    assert resp.status_code == 404, resp.text


def test_put_403_for_operator(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="OPERATOR")
    resp = c.put(f"{ENDPOINT}/W202-0092", json=_full_body())
    assert resp.status_code == 403, resp.text


def test_put_401_without_token(client, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    resp = client.put(f"{ENDPOINT}/W202-0092", json=_full_body())
    assert resp.status_code == 401, resp.text


def test_put_400_on_blank_required_field(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="SUPERVISOR")
    # blank building is a bad body
    resp = c.put(f"{ENDPOINT}/W202-0092", json=_full_body(building="  "))
    assert resp.status_code == 400, resp.text
    # missing asset_name entirely is a bad body
    body = _full_body()
    del body["asset_name"]
    resp2 = c.put(f"{ENDPOINT}/W202-0092", json=body)
    assert resp2.status_code == 400, resp2.text


def test_put_allows_head_and_admin(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    for role in ("HEAD", "ADMIN"):
        c = login_as(role=role)
        resp = c.put(f"{ENDPOINT}/W202-0092", json=_full_body())
        assert resp.status_code == 200, f"{role}: {resp.text}"


def test_put_nullable_fields_accept_null(login_as, db_session):
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="SUPERVISOR")
    resp = c.put(
        f"{ENDPOINT}/W202-0092",
        json=_full_body(model_no=None, serial_no=None, power_load=None,
                        quantity=None, condition=None, remarks=None),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_no"] is None
    assert body["serial_no"] is None
    assert body["remarks"] is None
    assert body["quantity"] is None
    # rated_kw can't be parsed from a null power_load
    assert body["rated_kw"] is None


def test_get_returns_remarks(auth_client, db_session):
    _seed_asset(db_session, asset_id="W202-0092", remarks="calibrated 2026-06")
    resp = auth_client.get(ENDPOINT)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["remarks"] == "calibrated 2026-06"


def test_shut_down_condition_round_trips(login_as, db_session):
    """The app soft-decommissions a machine by writing condition="Shut Down" and
    restores it with null. The reserved sentinel must survive PUT->GET verbatim."""
    _seed_asset(db_session, asset_id="W202-0092")
    c = login_as(role="SUPERVISOR", location="W-202")

    r = c.put(f"{ENDPOINT}/W202-0092", json=_full_body(condition="Shut Down"))
    assert r.status_code == 200, r.text
    assert r.json()["condition"] == "Shut Down"
    assert c.get(ENDPOINT).json()[0]["condition"] == "Shut Down"

    r2 = c.put(f"{ENDPOINT}/W202-0092", json=_full_body(condition=None))
    assert r2.status_code == 200, r2.text
    assert r2.json()["condition"] is None
    assert c.get(ENDPOINT).json()[0]["condition"] is None
