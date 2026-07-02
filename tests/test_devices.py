"""POST /devices/token — FCM device-token registry (P2 push scaffolding).

Fan-out is flag-gated (settings.fcm_enabled, default False), so these cover the
token upsert, the audience/envelope primitives, and the disabled-by-default
no-op path. No live FCM send is exercised (there is no Firebase project wired in
tests, and nothing should send while the app still polls)."""

from app.models import MtDeviceToken, MtUser
from app.notifications import fanout


def _seed_user(db, id=42, role="TECHNICIAN", location="W-202", name="Ravi"):
    if db.query(MtUser).filter(MtUser.id == id).first() is None:
        db.add(MtUser(id=id, name=name, username=f"u{id}", location=location, role=role))
        db.commit()


# --- token registration -----------------------------------------------------

def test_register_token_creates_row(auth_client, db_session):
    r = auth_client.post("/devices/token", json={
        "user_id": "42", "token": "tok-abc", "platform": "android"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "42"
    assert body["platform"] == "android"
    rows = db_session.query(MtDeviceToken).all()
    assert len(rows) == 1 and rows[0].token == "tok-abc"


def test_register_token_upserts_on_repeat(auth_client, db_session):
    auth_client.post("/devices/token", json={
        "user_id": "42", "token": "tok-abc", "platform": "android"})
    # same token again (device re-registers) -> update in place, no duplicate row
    r = auth_client.post("/devices/token", json={
        "user_id": "99", "token": "tok-abc", "platform": "ios"})
    assert r.status_code == 200, r.text
    rows = db_session.query(MtDeviceToken).all()
    assert len(rows) == 1
    assert rows[0].user_id == "99" and rows[0].platform == "ios"


def test_user_can_register_multiple_devices(auth_client, db_session):
    auth_client.post("/devices/token", json={
        "user_id": "42", "token": "tok-1", "platform": "android"})
    auth_client.post("/devices/token", json={
        "user_id": "42", "token": "tok-2", "platform": "android"})
    rows = db_session.query(MtDeviceToken).filter(MtDeviceToken.user_id == "42").all()
    assert {r.token for r in rows} == {"tok-1", "tok-2"}


def test_register_token_defaults_user_to_caller(auth_client, db_session):
    # auth_client's StubUser has id=1; omitting user_id falls back to the caller.
    r = auth_client.post("/devices/token", json={"token": "tok-x", "platform": "android"})
    assert r.status_code == 200, r.text
    assert db_session.query(MtDeviceToken).one().user_id == "1"


def test_register_token_requires_auth_401(client):
    assert client.post("/devices/token", json={
        "user_id": "42", "token": "t", "platform": "android"}).status_code == 401


# --- fan-out envelope + audience (pure, flag-independent) --------------------

def test_envelope_shape_for_breakdown():
    n = fanout.Notification(
        type="B1_NEW_BREAKDOWN", entity_id="flag-123", target_role="TECHNICIAN",
        target_user_id="u-9", title="MAJOR breakdown - Band Sealer",
        body="Belt snapped", tier=0)
    assert n.envelope() == {
        "type": "B1_NEW_BREAKDOWN", "category": "BREAKDOWN", "entityId": "flag-123",
        "targetRole": "TECHNICIAN", "targetUserId": "u-9",
        "title": "MAJOR breakdown - Band Sealer", "body": "Belt snapped",
        "tier": "0", "deepLinkExtraKey": "ticket_id"}


def test_envelope_pm_uses_pm_wo_deeplink():
    n = fanout.Notification(type="P2_AWAITING_SUPERVISOR", entity_id="wo-1",
                            target_role="SUPERVISOR", title="t", body="b", tier=1)
    env = n.envelope()
    assert env["category"] == "PM"
    assert env["deepLinkExtraKey"] == "pm_wo_id"
    assert env["tier"] == "1"
    assert env["targetUserId"] == ""     # unset -> "" (FCM data is string->string)


def test_resolve_recipients_by_role_and_building(db_session):
    _seed_user(db_session, id=1, role="TECHNICIAN", location="W-202")
    _seed_user(db_session, id=2, role="TECHNICIAN", location="A-185")
    _seed_user(db_session, id=3, role="SUPERVISOR", location="W-202")
    users = fanout.resolve_recipients(db_session, "TECHNICIAN", "W-202")
    assert {u.id for u in users} == {1}


# --- flag gate ---------------------------------------------------------------

def test_fanout_is_noop_when_disabled(auth_client, db_session):
    _seed_user(db_session, id=42, role="TECHNICIAN", location="W-202")
    auth_client.post("/devices/token", json={
        "user_id": "42", "token": "tok-1", "platform": "android"})
    n = fanout.Notification(type="B1_NEW_BREAKDOWN", entity_id="f1",
                            target_role="TECHNICIAN", title="t", body="b")
    # settings.fcm_enabled defaults to False -> resolve/push skipped, returns 0.
    assert fanout.send(db_session, n, building="W-202") == 0
