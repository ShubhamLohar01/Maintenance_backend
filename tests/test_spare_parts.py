"""Spare Parts (W-202) — GET /spare-parts (browse) + POST use/restock.

mt_202_spareparts is pre-existing (machine_name free text, parts_name JSONB
{name, unit}, quantity on hand). machine_name is matched best-effort against
mt_asset_list; every use/restock is logged to mt_202_spareparts_log.
"""
from app.models import MtAsset, MtSparePart, MtSparePartLog


def _part(db, machine_name, name, unit, quantity):
    p = MtSparePart(machine_name=machine_name, parts_name={"name": name, "unit": unit}, quantity=quantity)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_list_groups_by_machine_with_matched_assets(auth_client, db_session):
    db_session.add(MtAsset(asset_id="W202-1", building="W-202", asset_name="Kruger Machine"))
    db_session.commit()
    _part(db_session, "kruger machine", "pressure shaft", "nos", 2)
    _part(db_session, "kruger machine", "mixing shaft", "nos", 1)
    _part(db_session, "air compressor", "belt", "nos", 3)   # no matching asset

    resp = auth_client.get("/spare-parts")
    assert resp.status_code == 200, resp.text
    machines = {m["machine_name"]: m for m in resp.json()["machines"]}
    assert set(machines) == {"kruger machine", "air compressor"}

    kruger = machines["kruger machine"]
    assert len(kruger["parts"]) == 2
    assert kruger["matched_assets"] == [{"asset_id": "W202-1", "asset_name": "Kruger Machine"}]
    assert {p["part_name"] for p in kruger["parts"]} == {"pressure shaft", "mixing shaft"}
    assert machines["air compressor"]["matched_assets"] == []


def test_list_groups_null_machine_name_under_empty_string(auth_client, db_session):
    _part(db_session, None, "generic bolt", "nos", 10)
    resp = auth_client.get("/spare-parts")
    machines = {m["machine_name"]: m for m in resp.json()["machines"]}
    assert "" in machines
    assert machines[""]["parts"][0]["part_name"] == "generic bolt"


def test_use_decrements_and_logs(auth_client, db_session):
    p = _part(db_session, "kruger machine", "pressure shaft", "nos", 5)
    resp = auth_client.post(f"/spare-parts/{p.id}/use", json={"quantity": 2, "note": "repair job 123"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity"] == 3

    db_session.refresh(p)
    assert p.quantity == 3
    log = db_session.query(MtSparePartLog).one()
    assert log.action == "USE"
    assert log.quantity == 2
    assert log.spare_part_id == p.id
    assert log.machine_name == "kruger machine"
    assert log.part_name == "pressure shaft"
    assert log.note == "repair job 123"
    assert log.performed_by == "tester"


def test_use_insufficient_stock_400(auth_client, db_session):
    p = _part(db_session, "kruger machine", "pressure shaft", "nos", 1)
    resp = auth_client.post(f"/spare-parts/{p.id}/use", json={"quantity": 5})
    assert resp.status_code == 400
    db_session.refresh(p)
    assert p.quantity == 1                                    # unchanged
    assert db_session.query(MtSparePartLog).count() == 0       # no log written


def test_use_non_positive_quantity_400(auth_client, db_session):
    p = _part(db_session, "kruger machine", "pressure shaft", "nos", 5)
    assert auth_client.post(f"/spare-parts/{p.id}/use", json={"quantity": 0}).status_code == 400
    assert auth_client.post(f"/spare-parts/{p.id}/use", json={"quantity": -1}).status_code == 400


def test_restock_increments_and_logs(auth_client, db_session):
    p = _part(db_session, "kruger machine", "pressure shaft", "nos", 2)
    resp = auth_client.post(f"/spare-parts/{p.id}/restock", json={"quantity": 10})
    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity"] == 12
    log = db_session.query(MtSparePartLog).one()
    assert log.action == "RESTOCK"
    assert log.quantity == 10


def test_restock_non_positive_quantity_400(auth_client, db_session):
    p = _part(db_session, "kruger machine", "pressure shaft", "nos", 2)
    assert auth_client.post(f"/spare-parts/{p.id}/restock", json={"quantity": 0}).status_code == 400


def test_unknown_part_id_404(auth_client, db_session):
    assert auth_client.post("/spare-parts/9999/use", json={"quantity": 1}).status_code == 404
    assert auth_client.post("/spare-parts/9999/restock", json={"quantity": 1}).status_code == 404


def test_requires_auth_401(client):
    assert client.get("/spare-parts").status_code == 401
