"""Machine transfer acknowledgement: a transfer is PENDING until the RECEIVING
warehouse confirms receipt (status -> APPROVED). A SUPERVISOR may acknowledge any;
a TECHNICIAN only transfers whose destination (to_warehouse) is their own plant."""
from datetime import date

from app.models import MachineTransfer, MtAsset


def _mk(db, frm="A185", to="W202", name="Pan Coater", status="PENDING"):
    row = MachineTransfer(
        transfer_date=date(2026, 7, 1),
        from_warehouse=frm, to_warehouse=to, machine_name=name,
        status=status, created_by="tester",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_list_defaults_pending_supervisor_can_ack(login_as, db_session):
    _mk(db_session, to="W202")
    rows = login_as(role="SUPERVISOR", location="A-185").get("/machine-transfers").json()
    assert len(rows) == 1
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["can_acknowledge"] is True          # supervisor: any


def test_technician_can_ack_only_own_destination(login_as, db_session):
    _mk(db_session, to="W202")
    own = login_as(role="TECHNICIAN", location="W-202").get("/machine-transfers").json()[0]
    assert own["can_acknowledge"] is True              # destination = their plant
    other = login_as(role="TECHNICIAN", location="A-185").get("/machine-transfers").json()[0]
    assert other["can_acknowledge"] is False           # not their plant


def test_acknowledge_sets_approved(login_as, db_session):
    t = _mk(db_session, to="W202")
    r = login_as(role="TECHNICIAN", location="W-202", name="Manish").post(
        f"/machine-transfers/{t.id}/acknowledge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["acknowledged_by"] == "Manish"
    assert body["acknowledged_at"] is not None
    assert body["can_acknowledge"] is False            # already approved
    db_session.refresh(t)
    assert t.status == "APPROVED"


def test_acknowledge_wrong_warehouse_403(login_as, db_session):
    t = _mk(db_session, to="W202")
    assert login_as(role="TECHNICIAN", location="A-185").post(
        f"/machine-transfers/{t.id}/acknowledge").status_code == 403


def test_head_cannot_acknowledge_403(login_as, db_session):
    t = _mk(db_session, to="W202")
    assert login_as(role="HEAD", location="A-185").post(
        f"/machine-transfers/{t.id}/acknowledge").status_code == 403


def test_acknowledge_idempotent(login_as, db_session):
    t = _mk(db_session, to="W202")
    c = login_as(role="SUPERVISOR")
    assert c.post(f"/machine-transfers/{t.id}/acknowledge").status_code == 200
    r2 = c.post(f"/machine-transfers/{t.id}/acknowledge")   # again -> unchanged, still 200
    assert r2.status_code == 200 and r2.json()["status"] == "APPROVED"


def test_acknowledge_unknown_404(login_as, db_session):
    assert login_as(role="SUPERVISOR").post(
        "/machine-transfers/99999/acknowledge").status_code == 404


# ---- duplicate-while-pending guard -----------------------------------------

def test_duplicate_pending_blocked_by_asset_id(auth_client, db_session):
    db_session.add(MtAsset(asset_id="W202-PAN1", asset_name="Choc Pan", building="W-202"))
    db_session.commit()
    ok = auth_client.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Choc Pan", "asset_id": "W202-PAN1"})
    assert ok.status_code == 201, ok.text
    dup = auth_client.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Choc Pan", "asset_id": "W202-PAN1"})
    assert dup.status_code == 409


def test_duplicate_pending_blocked_by_name_when_no_asset_id(auth_client, db_session):
    ok = auth_client.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185", "machine_name": "Manual Machine"})
    assert ok.status_code == 201, ok.text
    # same name (case-insensitive), even a different direction -> still blocked
    dup = auth_client.post("/machine-transfers", data={
        "from_warehouse": "A185", "to_warehouse": "W202", "machine_name": "manual machine"})
    assert dup.status_code == 409


def test_transfer_allowed_again_after_acknowledge(login_as, db_session):
    db_session.add(MtAsset(asset_id="W202-PAN2", asset_name="Pan Two", building="W-202"))
    db_session.commit()
    sup = login_as(role="SUPERVISOR", location="A-185")
    r1 = sup.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Pan Two", "asset_id": "W202-PAN2"})
    assert r1.status_code == 201, r1.text
    tid = r1.json()["id"]
    # blocked while pending
    assert sup.post("/machine-transfers", data={
        "from_warehouse": "A185", "to_warehouse": "W202",
        "machine_name": "Pan Two", "asset_id": "W202-PAN2"}).status_code == 409
    # acknowledge -> APPROVED, then a new transfer is allowed
    assert sup.post(f"/machine-transfers/{tid}/acknowledge").status_code == 200
    r2 = sup.post("/machine-transfers", data={
        "from_warehouse": "A185", "to_warehouse": "W202",
        "machine_name": "Pan Two", "asset_id": "W202-PAN2"})
    assert r2.status_code == 201, r2.text


# ---- creator edit / delete -------------------------------------------------

def test_creator_can_delete_pending_and_reverts_building(auth_client, db_session):
    db_session.add(MtAsset(asset_id="W202-DEL1", asset_name="Del Machine", building="W-202"))
    db_session.commit()
    tid = auth_client.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Del Machine", "asset_id": "W202-DEL1"}).json()["id"]
    db_session.expire_all()
    assert db_session.query(MtAsset).filter_by(asset_id="W202-DEL1").one().building == "A-185"  # moved on create
    assert auth_client.delete(f"/machine-transfers/{tid}").status_code == 204
    db_session.expire_all()
    assert db_session.get(MachineTransfer, tid) is None                                          # row gone
    assert db_session.query(MtAsset).filter_by(asset_id="W202-DEL1").one().building == "W-202"    # reverted


def test_non_creator_cannot_delete_403(login_as, db_session):
    tid = login_as(username="alice", role="SUPERVISOR").post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185", "machine_name": "X"}).json()["id"]
    assert login_as(username="bob", role="SUPERVISOR").delete(
        f"/machine-transfers/{tid}").status_code == 403


def test_cannot_delete_after_acknowledge_409(login_as, db_session):
    c = login_as(username="alice", role="SUPERVISOR")
    tid = c.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185", "machine_name": "Y"}).json()["id"]
    assert c.post(f"/machine-transfers/{tid}/acknowledge").status_code == 200
    assert c.delete(f"/machine-transfers/{tid}").status_code == 409


def test_delete_unknown_404(auth_client, db_session):
    assert auth_client.delete("/machine-transfers/99999").status_code == 404


def test_creator_can_edit_pending_fields(auth_client, db_session):
    tid = auth_client.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Editable", "condition": "Good"}).json()["id"]
    r = auth_client.put(f"/machine-transfers/{tid}", json={"condition": "Damaged", "reason": "typo"})
    assert r.status_code == 200, r.text
    assert r.json()["condition"] == "Damaged"


def test_edit_repoints_asset_building(auth_client, db_session):
    db_session.add(MtAsset(asset_id="W202-ED1", asset_name="Ed Machine", building="W-202"))
    db_session.commit()
    tid = auth_client.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185",
        "machine_name": "Ed Machine", "asset_id": "W202-ED1"}).json()["id"]
    db_session.expire_all()
    assert db_session.query(MtAsset).filter_by(asset_id="W202-ED1").one().building == "A-185"
    # reverse the direction -> asset should end back at W-202
    r = auth_client.put(f"/machine-transfers/{tid}", json={
        "from_warehouse": "A185", "to_warehouse": "W202"})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.query(MtAsset).filter_by(asset_id="W202-ED1").one().building == "W-202"


def test_can_edit_flag_creator_only_and_locks_after_ack(login_as, db_session):
    creator = login_as(username="alice", role="SUPERVISOR", location="A-185")
    tid = creator.post("/machine-transfers", data={
        "from_warehouse": "W202", "to_warehouse": "A185", "machine_name": "Flag"}).json()["id"]
    mine = next(r for r in creator.get("/machine-transfers").json() if r["id"] == tid)
    assert mine["can_edit"] is True
    theirs = next(r for r in login_as(username="bob", role="SUPERVISOR").get(
        "/machine-transfers").json() if r["id"] == tid)
    assert theirs["can_edit"] is False
    creator.post(f"/machine-transfers/{tid}/acknowledge")   # APPROVED -> locked
    locked = next(r for r in creator.get("/machine-transfers").json() if r["id"] == tid)
    assert locked["can_edit"] is False
