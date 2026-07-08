"""CRUD for mt_users — HEAD/ADMIN only. New users have no password (shared login)."""

from app.models import MtUser

ENDPOINT = "/mt-users"


def _body(**over):
    b = {
        "emp_id": "E-101",
        "name": "Asha Kulkarni",
        "location": "A-185",
        "contact_no": "9876543210",
        "email_id": "asha@candorfoods.in",
        "role": "TECHNICIAN",
        "username": "AshaK",           # stored lowercased
    }
    b.update(over)
    return b


def test_create_persists_row_and_lowercases_username(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    r = c.post(ENDPOINT, json=_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "ashak"          # lowercased
    assert body["name"] == "Asha Kulkarni"
    assert body["emp_id"] == "E-101"
    assert body["role"] == "TECHNICIAN"
    assert isinstance(body["id"], int)

    row = db_session.query(MtUser).filter(MtUser.username == "ashak").one()
    assert row.contact_no == "9876543210"
    assert row.email_id == "asha@candorfoods.in"


def test_blank_optionals_become_null(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    r = c.post(ENDPOINT, json=_body(username="nulls", emp_id="   ", contact_no=""))
    assert r.status_code == 201, r.text
    row = db_session.query(MtUser).filter(MtUser.username == "nulls").one()
    assert row.emp_id is None
    assert row.contact_no is None


def test_list_returns_created_users(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    c.post(ENDPOINT, json=_body(username="one", name="One"))
    c.post(ENDPOINT, json=_body(username="two", name="Two"))
    r = c.get(ENDPOINT)
    assert r.status_code == 200, r.text
    names = [u["name"] for u in r.json()]
    assert "One" in names and "Two" in names


def test_create_missing_required_400(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    assert c.post(ENDPOINT, json=_body(name="   ")).status_code == 400
    assert c.post(ENDPOINT, json=_body(username="  ")).status_code == 400


def test_create_duplicate_username_409(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    assert c.post(ENDPOINT, json=_body(username="dupe")).status_code == 201
    assert c.post(ENDPOINT, json=_body(username="DUPE")).status_code == 409  # case-folded collision


def test_update_overwrites_fields(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    created = c.post(ENDPOINT, json=_body(username="edit_me", name="Before")).json()
    uid = created["id"]
    r = c.put(f"{ENDPOINT}/{uid}", json=_body(username="edit_me", name="After", role="SUPERVISOR"))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "After"
    assert r.json()["role"] == "SUPERVISOR"


def test_update_missing_404(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    assert c.put(f"{ENDPOINT}/123456", json=_body()).status_code == 404


def test_delete_removes_row(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    uid = c.post(ENDPOINT, json=_body(username="gone")).json()["id"]
    assert c.delete(f"{ENDPOINT}/{uid}").status_code == 200
    assert db_session.query(MtUser).filter(MtUser.id == uid).first() is None


def test_delete_missing_404(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    assert c.delete(f"{ENDPOINT}/123456").status_code == 404


def test_delete_self_400(login_as, db_session):
    # Seed a row whose id we authenticate as, then try to delete it.
    row = MtUser(name="Boss", username="boss", role="HEAD")
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    c = login_as(role="HEAD", id=row.id)
    assert c.delete(f"{ENDPOINT}/{row.id}").status_code == 400


def test_manage_roles_allowed(login_as, db_session):
    for role in ("HEAD", "ADMIN"):
        c = login_as(role=role, id=999)
        assert c.post(ENDPOINT, json=_body(username=f"u_{role}")).status_code == 201


def test_non_manage_roles_forbidden_403(login_as, db_session):
    for role in ("OPERATOR", "TECHNICIAN", "SUPERVISOR"):
        c = login_as(role=role, id=999)
        assert c.post(ENDPOINT, json=_body()).status_code == 403
        assert c.get(ENDPOINT).status_code == 403


def test_requires_auth_401(client):
    assert client.post(ENDPOINT, json=_body()).status_code == 401


def test_update_duplicate_username_409(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    c.post(ENDPOINT, json=_body(username="alpha"))
    beta_id = c.post(ENDPOINT, json=_body(username="beta")).json()["id"]
    # renaming beta -> alpha (case-folded) collides with the existing row
    r = c.put(f"{ENDPOINT}/{beta_id}", json=_body(username="ALPHA", name="Beta"))
    assert r.status_code == 409, r.text


def test_get_by_id_200_and_404(login_as, db_session):
    c = login_as(role="HEAD", id=999)
    uid = c.post(ENDPOINT, json=_body(username="single")).json()["id"]
    got = c.get(f"{ENDPOINT}/{uid}")
    assert got.status_code == 200, got.text
    assert got.json()["username"] == "single"
    assert c.get(f"{ENDPOINT}/123456").status_code == 404


def test_put_delete_forbidden_for_non_managers_403(login_as, db_session):
    uid = login_as(role="HEAD", id=999).post(ENDPOINT, json=_body(username="victim")).json()["id"]
    for role in ("OPERATOR", "TECHNICIAN", "SUPERVISOR"):
        c = login_as(role=role, id=1)
        assert c.put(f"{ENDPOINT}/{uid}", json=_body(username="victim", name="X")).status_code == 403
        assert c.delete(f"{ENDPOINT}/{uid}").status_code == 403
