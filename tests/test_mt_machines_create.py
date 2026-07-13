"""POST /mt-machines — add a new asset to mt_asset_list from the app.

Roles SUPERVISOR / HEAD / TECHNICIAN / ADMIN may add (OPERATOR may not). The app
sends the full row with an empty asset_id; the backend assigns a building-prefixed
id (e.g. W202-0008), computes rated_kw from power_load, and returns the MtMachineDto."""

from app.models import MtAsset

ENDPOINT = "/mt-machines"


def _body(**over):
    b = {
        "asset_id": "",                       # empty -> backend assigns
        "building": "W-202",
        "asset_name": "New Roaster",
        "category": "Production Equipment",
        "sub_location": "Floor 2",
        "power_load": "2.2 kW",
        "rated_kw": None,                     # computed server-side
        "quantity": 3,
        "model_no": "RX-9",
        "serial_no": "SN-1",
        "condition": "Good",
        "assigned_to": "Ravi",
        "remarks": "spare belt in store",
    }
    b.update(over)
    return b


def test_create_persists_full_row_and_assigns_id(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="W-202")
    r = c.post(ENDPOINT, json=_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["asset_id"].startswith("W202-")          # server-assigned, building-prefixed
    assert body["asset_name"] == "New Roaster"
    assert body["category"] == "Production Equipment"
    assert body["sub_location"] == "Floor 2"
    assert body["quantity"] == 3
    assert body["model_no"] == "RX-9"
    assert body["serial_no"] == "SN-1"
    assert body["condition"] == "Good"
    assert body["assigned_to"] == "Ravi"
    assert body["remarks"] == "spare belt in store"
    assert body["rated_kw"] == 2.2                        # computed from "2.2 kW"

    row = db_session.query(MtAsset).filter(MtAsset.asset_id == body["asset_id"]).one()
    assert row.assigned_to == "Ravi"                     # full row really stored
    assert row.remarks == "spare belt in store"
    assert row.quantity == 3


def test_create_ignores_client_supplied_asset_id(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="W-202")
    r = c.post(ENDPOINT, json=_body(asset_id="HACKED-1"))
    assert r.status_code == 201, r.text
    assert r.json()["asset_id"] != "HACKED-1"
    assert r.json()["asset_id"].startswith("W202-")


def test_create_increments_from_existing_max(login_as, db_session):
    db_session.add(MtAsset(asset_id="W202-0007", building="W-202", asset_name="Old"))
    db_session.commit()
    c = login_as(role="SUPERVISOR", location="W-202")
    r = c.post(ENDPOINT, json=_body())
    assert r.status_code == 201, r.text
    assert r.json()["asset_id"] == "W202-0008"


def test_create_uses_building_prefix_for_a185(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="A-185")
    r = c.post(ENDPOINT, json=_body(building="A-185"))
    assert r.status_code == 201, r.text
    assert r.json()["asset_id"].startswith("A185-")


def test_create_missing_required_fields_400(login_as, db_session):
    c = login_as(role="SUPERVISOR")
    for field in ("building", "asset_name", "category", "sub_location"):
        body = _body()
        body[field] = "   "                              # blank -> rejected
        r = c.post(ENDPOINT, json=body)
        assert r.status_code == 400, f"{field}: {r.text}"


def test_create_allowed_roles(login_as, db_session):
    for role in ("SUPERVISOR", "HEAD", "TECHNICIAN", "ADMIN"):
        c = login_as(role=role, location="W-202")
        r = c.post(ENDPOINT, json=_body())
        assert r.status_code == 201, f"{role}: {r.text}"


def test_create_operator_forbidden_403(login_as, db_session):
    c = login_as(role="OPERATOR", location="W-202")
    r = c.post(ENDPOINT, json=_body())
    assert r.status_code == 403, r.text


def test_create_requires_auth_401(client):
    assert client.post(ENDPOINT, json=_body()).status_code == 401
