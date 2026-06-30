"""GET /head/escalations — overdue operator breakdowns by tier (HEAD = top tier).

Operator flags live in mt_breakdown_records (source='OPERATOR_FLAG'); escalations
scope by asset_id -> mt_asset_list.building."""

from datetime import datetime, timedelta

from app.models import MtAsset, BreakdownRecord


def _seed_assets(db):
    if db.query(MtAsset).filter(MtAsset.asset_id == "A185-1").first() is None:
        db.add_all([
            MtAsset(asset_id="A185-1", building="A-185", asset_name="Sealer"),
            MtAsset(asset_id="W202-1", building="W-202", asset_name="Wrapper"),
        ])
        db.commit()


def _flag(db, asset_id, reported_at, status="OPEN", severity="MAJOR"):
    rec = BreakdownRecord(
        machine_id=asset_id, operator_raise_person="Anil",
        severity=severity, description="x", status=status, start_time=reported_at,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return str(rec.id)


def test_escalations_default_returns_head_tier_only(auth_client, db_session):
    _seed_assets(db_session)
    now = datetime.utcnow()
    f1 = _flag(db_session, "A185-1", now - timedelta(days=3, hours=1))  # tier 3
    _flag(db_session, "A185-1", now - timedelta(days=2, hours=1))       # tier 2
    _flag(db_session, "A185-1", now - timedelta(hours=5))               # <1d, excluded

    resp = auth_client.get("/head/escalations")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert {i["flag_id"] for i in items} == {f1}
    it = items[0]
    assert it["type"] == "BREAKDOWN"
    assert it["tier"] == 3
    assert it["tier_role"] == "HEAD"
    assert it["days_overdue"] == 3
    assert it["machine_name"] == "Sealer"
    assert it["plant_id"] == "A185"
    assert it["raised_at"] is not None


def test_escalations_min_tier_widens(auth_client, db_session):
    _seed_assets(db_session)
    now = datetime.utcnow()
    f1 = _flag(db_session, "A185-1", now - timedelta(days=3, hours=1))
    f2 = _flag(db_session, "A185-1", now - timedelta(days=2, hours=1))
    f3 = _flag(db_session, "A185-1", now - timedelta(days=1, hours=1))

    resp = auth_client.get("/head/escalations", params={"min_tier": 1})
    assert resp.status_code == 200
    tiers = {i["flag_id"]: i["tier"] for i in resp.json()}
    assert tiers == {f1: 3, f2: 2, f3: 1}


def test_escalations_excludes_qc_approved(auth_client, db_session):
    _seed_assets(db_session)
    now = datetime.utcnow()
    _flag(db_session, "A185-1", now - timedelta(days=5), status="CLOSED")   # cleared
    f2 = _flag(db_session, "A185-1", now - timedelta(days=5), status="ACKNOWLEDGED")
    resp = auth_client.get("/head/escalations")
    assert {i["flag_id"] for i in resp.json()} == {f2}


def test_escalations_head_sees_both_plants(auth_client, db_session):
    _seed_assets(db_session)
    now = datetime.utcnow()
    a = _flag(db_session, "A185-1", now - timedelta(days=4))
    w = _flag(db_session, "W202-1", now - timedelta(days=4))
    resp = auth_client.get("/head/escalations")
    assert {i["flag_id"] for i in resp.json()} == {a, w}


def test_escalations_non_head_scoped_to_own(login_as, db_session):
    _seed_assets(db_session)
    now = datetime.utcnow()
    a = _flag(db_session, "A185-1", now - timedelta(days=4))
    _flag(db_session, "W202-1", now - timedelta(days=4))
    c = login_as(role="TECHNICIAN", location="A-185")
    resp = c.get("/head/escalations", params={"min_tier": 1})
    assert {i["flag_id"] for i in resp.json()} == {a}


def test_escalations_requires_auth_401(client):
    assert client.get("/head/escalations").status_code == 401
