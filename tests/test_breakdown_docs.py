"""POST /preventive-maintenance/breakdowns — CFPLA.C4.F.06 sheet -> mt_doc_breakdown
(one row per entry). Moved off mt_breakdown_records when that table was slimmed to
the live workflow."""

from app.models import BreakdownDoc

ENDPOINT = "/preventive-maintenance/breakdowns"


def test_submit_creates_one_row_per_entry(auth_client, db_session):
    body = {
        "doc_no": "CFPLA.C4.F.06",
        "verified_by": "Ravi",
        "entries": [
            {"record_date": "2026-06-22", "location": "Lower Basement",
             "machine_name": "Auto L-sealer", "problem_in_brief": "Heater coil not heating"},
            {"record_date": "2026-06-23", "machine_name": "Capper", "problem_in_brief": "Jam"},
        ],
    }
    resp = auth_client.post(ENDPOINT, json=body)
    assert resp.status_code == 201, resp.text
    ids = resp.json()["ids"]
    assert len(ids) == 2

    rows = db_session.query(BreakdownDoc).order_by(BreakdownDoc.sr_no).all()
    assert [r.sr_no for r in rows] == [1, 2]
    assert {r.id for r in rows} == set(ids)
    assert all(r.verified_by == "Ravi" for r in rows)
    assert all(r.created_by == "tester" for r in rows)
    assert rows[0].machine_name == "Auto L-sealer"
    assert rows[0].location == "Lower Basement"


def test_empty_entries_400(auth_client):
    resp = auth_client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": []})
    assert resp.status_code == 400


def test_null_record_date_ok(auth_client, db_session):
    resp = auth_client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": [{"machine_name": "X"}]})
    assert resp.status_code == 201, resp.text
    resp2 = auth_client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": [{"record_date": "", "machine_name": "Z"}]})
    assert resp2.status_code == 201, resp2.text
    rows = db_session.query(BreakdownDoc).all()
    assert len(rows) == 2
    assert all(r.record_date is None for r in rows)


def test_requires_auth_401(client):
    resp = client.post(ENDPOINT, json={"verified_by": "Ravi", "entries": [{"machine_name": "X"}]})
    assert resp.status_code == 401


# --- GET read-back (mirrors GET /preventive-maintenance/checklists) ---

def test_list_returns_rows_newest_first(auth_client, db_session):
    body = {"doc_no": "CFPLA.C4.F.06", "verified_by": "Ravi", "entries": [
        {"record_date": "2026-06-22", "location": "Lower Basement",
         "machine_name": "Auto L-sealer", "equipment_model_no": "W202-0005",
         "problem_in_brief": "Heater coil", "type_of_maintenance": "Temporary",
         "part_of_machine": "coil", "temporary_reason": "no spare",
         "duration_start": "10:30", "duration_end": "12:00",
         "machine_operator_sign": "Anil", "maintenance_person_sign": "Suresh",
         "qc_clearance_sign": "Ravi"},
        {"machine_name": "Capper"},
    ]}
    ids = auth_client.post(ENDPOINT, json=body).json()["ids"]

    resp = auth_client.get(ENDPOINT)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list) and len(rows) == 2
    assert [r["id"] for r in rows] == sorted(ids, reverse=True)   # newest first

    by_id = {r["id"]: r for r in rows}
    full = by_id[ids[0]]
    assert full["doc_no"] == "CFPLA.C4.F.06"
    assert full["record_date"] == "2026-06-22"
    assert full["machine_name"] == "Auto L-sealer"
    assert full["equipment_model_no"] == "W202-0005"
    assert full["problem_in_brief"] == "Heater coil"
    assert full["duration_start"] == "10:30"
    assert full["verified_by"] == "Ravi"
    assert isinstance(full["id"], int)
    assert full["created_at"].endswith("Z")

    sparse = by_id[ids[1]]
    assert sparse["machine_name"] == "Capper"
    assert sparse["record_date"] == ""      # null date -> ""
    assert sparse["location"] == ""         # null string -> ""


def test_list_empty_returns_empty_array(auth_client):
    resp = auth_client.get(ENDPOINT)
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_requires_auth_401(client):
    assert client.get(ENDPOINT).status_code == 401
