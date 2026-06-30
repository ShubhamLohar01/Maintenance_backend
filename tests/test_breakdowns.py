"""Operator breakdown workflow on mt_breakdown_records (now a single-purpose table):
flag -> acknowledge -> work-done -> QC approve/reject, plus GET /breakdowns/open.
People are stored as names (resolved from mt_users at write time)."""

from app.models import BreakdownRecord, MtAsset, MtUser
from app.utils import to_epoch_ms

NOW = 1750768500000  # epoch ms


def _seed(db):
    if db.query(MtAsset).filter(MtAsset.asset_id == "W202-0005").first() is None:
        db.add_all([
            MtAsset(asset_id="W202-0005", asset_name="Band Sealer", building="W-202", sub_location="2nd Floor"),
            MtAsset(asset_id="A185-0001", asset_name="Tubelight", building="A-185", sub_location="LB"),
        ])
        db.commit()
    if db.query(MtUser).filter(MtUser.id == 42).first() is None:
        db.add(MtUser(id=42, name="Anil", username="anil", location="W-202", role="OPERATOR"))
        db.commit()


def _flag(c, asset="W202-0005"):
    # multipart/form-data now (was JSON) — the before-photo is an optional file part.
    r = c.post("/breakdowns/flag", data={
        "machine_id": asset, "operator_id": "42", "severity": "MAJOR",
        "description": "jaw not heating", "raised_at": NOW})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_flag_creates_open_record(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    rec = db_session.get(BreakdownRecord, int(fid))
    assert rec.status == "OPEN"
    assert rec.machine_id == "W202-0005"
    assert rec.machine_name == "Band Sealer"
    assert rec.severity == "MAJOR"
    assert rec.description == "jaw not heating"
    assert rec.operator_raise_person == "Anil"          # resolved from mt_users id 42
    assert to_epoch_ms(rec.start_time) == NOW            # round-trips through a tz-naive column


def test_flag_falls_back_to_caller_name_when_unknown_operator(auth_client, db_session):
    _seed(db_session)
    r = auth_client.post("/breakdowns/flag", data={
        "machine_id": "W202-0005", "operator_id": "999", "severity": "MINOR",
        "description": "x", "raised_at": NOW})
    assert r.status_code == 200, r.text
    rec = db_session.get(BreakdownRecord, int(r.json()["id"]))
    assert rec.operator_raise_person == "Tester"        # StubUser.name fallback


def test_flag_unknown_asset_404(auth_client, db_session):
    _seed(db_session)
    r = auth_client.post("/breakdowns/flag", data={
        "machine_id": "ZZZ-9999", "operator_id": "42", "severity": "MINOR",
        "description": "x", "raised_at": NOW})
    assert r.status_code == 404


def test_full_lifecycle(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)

    ack = auth_client.post(f"/breakdowns/{fid}/qc/acknowledge", json={
        "user_id": "7", "user_name": "Ravi", "acknowledged_at": NOW}).json()
    assert ack["ticket_status"] == "ACKNOWLEDGED"
    rec = db_session.get(BreakdownRecord, int(fid))
    db_session.refresh(rec)
    assert rec.technician == "Ravi"
    assert to_epoch_ms(rec.ackn_at) == NOW

    # work-done is multipart now; no photo here -> work_done_des still persists.
    wd = auth_client.post(f"/breakdowns/{fid}/work-done", data={
        "user_id": "7", "user_name": "Ravi", "work_done": "replaced coil",
        "done_at": NOW}).json()
    assert wd["ticket_status"] == "PENDING_QC"
    assert wd["qc_status"] == "PENDING"
    db_session.refresh(rec)
    assert rec.work_done_des == "replaced coil"
    assert rec.photo_url is None                         # no photo attached

    dis = auth_client.post(f"/breakdowns/{fid}/qc/disapprove", json={
        "user_id": "9", "user_name": "Qcuser", "decided_at": NOW,
        "reason": "not fixed"}).json()
    assert dis["ticket_status"] == "OPEN"          # re-opened to the original technician
    assert dis["qc_status"] == "DISAPPROVED"
    db_session.refresh(rec)
    assert rec.qc_reject_reason == "not fixed"
    assert rec.qc_checked_by == "Qcuser"
    assert rec.technician == "Ravi"                # original technician NOT cleared
    # re-appears in the open list (with the QC reason) so another device shows why
    open_row = next(x for x in auth_client.get("/breakdowns/open").json() if x["id"] == fid)
    assert open_row["qc_reject_reason"] == "not fixed"

    app_ = auth_client.post(f"/breakdowns/{fid}/qc/approve", json={
        "user_id": "9", "user_name": "Qcuser", "decided_at": NOW,
        "notes": "ok"}).json()
    assert app_["ticket_status"] == "CLOSED"
    assert app_["qc_status"] == "APPROVED"
    assert app_["machine_status"] == "AVAILABLE"
    db_session.refresh(rec)
    assert rec.qc_checked_by == "Qcuser"
    assert to_epoch_ms(rec.end_time) == NOW


def test_open_endpoint_excludes_closed(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    assert any(x["id"] == fid for x in auth_client.get("/breakdowns/open").json())
    auth_client.post(f"/breakdowns/{fid}/qc/approve", json={
        "user_id": "9", "user_name": "Qcuser", "decided_at": NOW})
    assert fid not in [x["id"] for x in auth_client.get("/breakdowns/open").json()]


def test_open_endpoint_fields(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    row = next(x for x in auth_client.get("/breakdowns/open").json() if x["id"] == fid)
    assert row["asset_id"] == "W202-0005"
    assert row["asset_name"] == "Band Sealer"
    assert row["reporter_name"] == "Anil"
    assert row["reported_at"] == NOW
    assert row["building"] == "W-202"


def test_open_endpoint_plant_scope(auth_client, db_session):
    _seed(db_session)
    w = _flag(auth_client, "W202-0005")
    a = _flag(auth_client, "A185-0001")
    w_ids = [x["id"] for x in auth_client.get("/breakdowns/open?plant_id=W202").json()]
    assert w in w_ids and a not in w_ids
    both = [x["id"] for x in auth_client.get("/breakdowns/open?plant_id=both").json()]
    assert w in both and a in both


def test_acknowledge_persists_qc_checked_by(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    auth_client.post(f"/breakdowns/{fid}/qc/acknowledge", json={
        "user_id": "9", "user_name": "Amar Bahudar Yadav",
        "qc_checked_by": "amar.yadav", "acknowledged_at": NOW})
    rec = db_session.get(BreakdownRecord, int(fid))
    db_session.refresh(rec)
    assert rec.qc_checked_by == "amar.yadav"


def test_acknowledge_without_qc_checked_by_leaves_it_untouched(auth_client, db_session):
    # technician path / older app build (no qc_checked_by) -> column stays NULL
    _seed(db_session)
    fid = _flag(auth_client)
    auth_client.post(f"/breakdowns/{fid}/qc/acknowledge", json={
        "user_id": "7", "user_name": "Ravi", "acknowledged_at": NOW})
    rec = db_session.get(BreakdownRecord, int(fid))
    db_session.refresh(rec)
    assert rec.qc_checked_by is None


def test_requires_auth_401(client):
    # Valid form body so only the missing auth (not body validation) can fail it.
    assert client.post("/breakdowns/flag", data={
        "machine_id": "W202-0005", "operator_id": "42", "severity": "MINOR",
        "description": "x", "raised_at": NOW}).status_code == 401


def test_work_done_uploads_after_photo_to_s3(auth_client, db_session, monkeypatch):
    """The technician's after-photo is uploaded to S3 and its URL (not a device
    path) is stored in photo_url."""
    _seed(db_session)
    fid = _flag(auth_client)
    auth_client.post(f"/breakdowns/{fid}/qc/acknowledge", json={
        "user_id": "7", "user_name": "Ravi", "acknowledged_at": NOW})

    captured = {}

    def _fake_upload(key, data, content_type):
        captured["key"] = key
        captured["content_type"] = content_type
        return f"https://bucket.s3.amazonaws.com/{key}"

    monkeypatch.setattr("app.api.breakdowns.upload_bytes", _fake_upload)

    r = auth_client.post(
        f"/breakdowns/{fid}/work-done",
        data={"user_id": "7", "user_name": "Ravi", "work_done": "new gear", "done_at": NOW},
        files={"after_photo": ("after.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    rec = db_session.get(BreakdownRecord, int(fid))
    db_session.refresh(rec)
    assert rec.work_done_des == "new gear"
    assert rec.photo_url == f"https://bucket.s3.amazonaws.com/breakdowns/{fid}/after.jpg"
    assert captured["key"] == f"breakdowns/{fid}/after.jpg"
    assert captured["content_type"] == "image/jpeg"


def test_work_done_rejects_non_image(auth_client, db_session):
    _seed(db_session)
    fid = _flag(auth_client)
    r = auth_client.post(
        f"/breakdowns/{fid}/work-done",
        data={"user_id": "7", "user_name": "Ravi", "work_done": "x", "done_at": NOW},
        files={"after_photo": ("note.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400


def test_flag_uploads_before_photo_to_s3(auth_client, db_session, monkeypatch):
    """The operator's before-photo is uploaded to S3 at raise time."""
    _seed(db_session)
    monkeypatch.setattr(
        "app.api.breakdowns.upload_bytes",
        lambda key, data, content_type: f"https://bucket.s3.amazonaws.com/{key}",
    )
    r = auth_client.post(
        "/breakdowns/flag",
        data={"machine_id": "W202-0005", "operator_id": "42", "severity": "MAJOR",
              "description": "jaw not heating", "raised_at": NOW},
        files={"before_photo": ("before.png", b"\x89PNGfake", "image/png")},
    )
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    rec = db_session.get(BreakdownRecord, int(fid))
    assert rec.before_photo_url == f"https://bucket.s3.amazonaws.com/breakdowns/{fid}/before.png"
