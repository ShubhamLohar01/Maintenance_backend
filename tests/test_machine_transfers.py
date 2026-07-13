"""POST /machine-transfers — records a transfer AND moves the asset's `building`
in mt_asset_list to the destination warehouse. Match is precise by `asset_id`, with
a unique-name-within-source-warehouse fallback; ambiguous names leave the register
untouched (transfer still saves)."""

from app.models import MachineTransfer, MtAsset

EP = "/machine-transfers"


def _seed(db):
    db.add_all([
        MtAsset(asset_id="A185-0007", asset_name="Pan Coater", building="A-185"),
        MtAsset(asset_id="W202-0009", asset_name="Band Sealer", building="W-202"),
        # two assets share a name in A-185 -> ambiguous by name alone
        MtAsset(asset_id="A185-0010", asset_name="Tube Light", building="A-185"),
        MtAsset(asset_id="A185-0011", asset_name="Tube Light", building="A-185"),
    ])
    db.commit()


def test_transfer_with_asset_id_moves_building(auth_client, db_session):
    _seed(db_session)
    r = auth_client.post(EP, data={
        "from_warehouse": "A185", "to_warehouse": "W202",
        "machine_name": "Pan Coater", "asset_id": "A185-0007"})
    assert r.status_code == 201, r.text
    db_session.expire_all()
    assert db_session.query(MtAsset).filter_by(asset_id="A185-0007").one().building == "W-202"
    assert db_session.query(MachineTransfer).count() == 1


def test_transfer_unique_name_moves_building(auth_client, db_session):
    _seed(db_session)
    # no asset_id; "Band Sealer" is unique within the source warehouse (W-202)
    r = auth_client.post(EP, data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Band Sealer"})
    assert r.status_code == 201, r.text
    db_session.expire_all()
    assert db_session.query(MtAsset).filter_by(asset_id="W202-0009").one().building == "A-185"


def test_transfer_ambiguous_name_leaves_register(auth_client, db_session):
    _seed(db_session)
    # no asset_id; two "Tube Light" rows in A-185 -> skip the move, still save transfer
    r = auth_client.post(EP, data={
        "from_warehouse": "A185", "to_warehouse": "W202",
        "machine_name": "Tube Light"})
    assert r.status_code == 201, r.text
    db_session.expire_all()
    buildings = {a.building for a in db_session.query(MtAsset).filter_by(asset_name="Tube Light").all()}
    assert buildings == {"A-185"}                       # unchanged
    assert db_session.query(MachineTransfer).count() == 1


def test_transfer_bad_asset_id_still_saves_and_skips_move(auth_client, db_session):
    _seed(db_session)
    # asset_id doesn't exist and the name is ambiguous -> no move, transfer still saved
    r = auth_client.post(EP, data={
        "from_warehouse": "A185", "to_warehouse": "W202",
        "machine_name": "Tube Light", "asset_id": "NOPE-9999"})
    assert r.status_code == 201, r.text
    db_session.expire_all()
    assert {a.building for a in db_session.query(MtAsset).filter_by(asset_name="Tube Light").all()} == {"A-185"}


def test_transfer_requires_auth_401(client):
    assert client.post(EP, data={
        "from_warehouse": "A185", "to_warehouse": "W202", "machine_name": "Pan Coater"}).status_code == 401


# --- acknowledge (receiving-warehouse confirmation: PENDING -> APPROVED) ------

def _make_transfer(db, to_wh="W202"):
    t = MachineTransfer(
        from_warehouse="A185", to_warehouse=to_wh, machine_name="Pan Coater",
        created_by="tester",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t.id


def test_ack_supervisor_approves(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(role="SUPERVISOR", location="A-185")   # supervisor: any transfer
    r = c.post(f"/machine-transfers/{tid}/acknowledge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["acknowledged_by"] == "Tester"          # caller's name
    assert body["acknowledged_at"] and body["acknowledged_at"].endswith("Z")
    assert body["can_acknowledge"] is False              # already approved


def test_ack_technician_of_destination_ok(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(role="TECHNICIAN", location="W-202")   # destination plant
    assert c.post(f"/machine-transfers/{tid}/acknowledge").json()["status"] == "APPROVED"


def test_ack_technician_wrong_plant_403(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(role="TECHNICIAN", location="A-185")   # NOT the destination plant
    assert c.post(f"/machine-transfers/{tid}/acknowledge").status_code == 403


def test_ack_head_is_view_only_403(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(role="HEAD", location="A-185")         # HEAD is view-only here
    assert c.post(f"/machine-transfers/{tid}/acknowledge").status_code == 403


def test_ack_unknown_id_404(login_as, db_session):
    c = login_as(role="SUPERVISOR", location="A-185")
    assert c.post("/machine-transfers/99999/acknowledge").status_code == 404


def test_ack_is_idempotent(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(role="SUPERVISOR", location="A-185")
    assert c.post(f"/machine-transfers/{tid}/acknowledge").json()["status"] == "APPROVED"
    r2 = c.post(f"/machine-transfers/{tid}/acknowledge")     # re-ack: no-op, still 200
    assert r2.status_code == 200 and r2.json()["status"] == "APPROVED"


def test_list_reports_status_and_can_acknowledge(login_as, db_session):
    _make_transfer(db_session, to_wh="W202")
    rows = login_as(role="SUPERVISOR", location="A-185").get(EP).json()
    assert rows and rows[0]["status"] == "PENDING"
    assert rows[0]["can_acknowledge"] is True            # a supervisor may ack a pending row


# --- edit / delete (creator-only, PENDING-only) -------------------------------

def test_edit_creator_updates_pending(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")       # created_by = "tester"
    c = login_as(username="tester", role="SUPERVISOR", location="A-185")
    r = c.put(f"{EP}/{tid}", json={"condition": "Damaged", "reason": "fix"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["condition"] == "Damaged" and body["reason"] == "fix"
    assert body["can_edit"] is True                      # still pending + still creator


def test_edit_non_creator_403(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(username="someone_else", role="SUPERVISOR", location="A-185")
    assert c.put(f"{EP}/{tid}", json={"condition": "Damaged"}).status_code == 403


def test_edit_after_acknowledge_409(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    login_as(role="SUPERVISOR", location="A-185").post(f"{EP}/{tid}/acknowledge")   # -> APPROVED
    c = login_as(username="tester", role="SUPERVISOR", location="A-185")
    assert c.put(f"{EP}/{tid}", json={"condition": "Damaged"}).status_code == 409


def test_edit_unknown_404(login_as):
    c = login_as(username="tester", role="SUPERVISOR", location="A-185")
    assert c.put(f"{EP}/99999", json={"condition": "X"}).status_code == 404


def test_delete_creator_204(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(username="tester", role="SUPERVISOR", location="A-185")
    assert c.delete(f"{EP}/{tid}").status_code == 204
    db_session.expire_all()
    assert db_session.get(MachineTransfer, tid) is None


def test_delete_non_creator_403(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    c = login_as(username="someone_else", role="SUPERVISOR", location="A-185")
    assert c.delete(f"{EP}/{tid}").status_code == 403


def test_delete_after_acknowledge_409(login_as, db_session):
    tid = _make_transfer(db_session, to_wh="W202")
    login_as(role="SUPERVISOR", location="A-185").post(f"{EP}/{tid}/acknowledge")   # -> APPROVED
    c = login_as(username="tester", role="SUPERVISOR", location="A-185")
    assert c.delete(f"{EP}/{tid}").status_code == 409
