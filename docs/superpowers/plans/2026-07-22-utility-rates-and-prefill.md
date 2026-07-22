# Utility Rates + Previous-Closing Auto-fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make utility prices (diesel/gas/water/electricity rates) supervisor-managed and read-only for technicians, enforced server-side, and auto-fill a reading form's opening fields from the previous date's closing.

**Architecture:** A new `mt_utility_rates` table (one row per plant) is the single source of truth for the four rates. `PUT /utilities/rates` (SUPERVISOR/HEAD/ADMIN only) sets them; every technician submit has its rate overwritten from this table and its cost columns recomputed server-side. A `GET /utilities/{utility}/prefill` endpoint returns the last actual closing mapped to the opening fields plus the current rate.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Pydantic v2, pytest + FastAPI `TestClient` over in-memory SQLite. RDS Postgres in prod (no Alembic — manual pgAdmin SQL).

**Spec:** [docs/superpowers/specs/2026-07-22-utility-rates-and-prefill-design.md](../specs/2026-07-22-utility-rates-and-prefill-design.md)

---

## File Structure

- `app/models.py` — add `MtUtilityRate` (after `MtUtilityWater`, ~line 625).
- `app/schemas.py` — add `UtilityRatesDto`, `UtilityRatesUpdateRequest`, `UtilityPrefillDto` (after the utility schemas, ~line 1026).
- `app/api/utilities.py` — add rate helpers, recompute helpers, rate-override in `_upsert`, and 3 endpoints (`GET/PUT /rates`, `GET /{utility}/prefill`).
- `tests/conftest.py` — import + register `MtUtilityRate` in `_TABLES`.
- `tests/test_utility_rates.py` — new test file for rates + prefill + recompute.
- `tests/test_utilities.py` — update the two existing tests that assumed client-trusted rate/cost.
- `migrations/2026-07-22_utility_rates.sql` — create + seed (manual pgAdmin run).
- `docs/handoff/2026-07-22-utility-rates-frontend.md` — Kotlin team instructions.

Router registration is already done ([app/main.py:123](../../../app/main.py#L123)) — no change.

---

## Task 1: `mt_utility_rates` table + rate endpoints (GET/PUT)

**Files:**
- Modify: `app/models.py` (add `MtUtilityRate` after `MtUtilityWater`)
- Modify: `app/schemas.py` (add rate DTOs)
- Modify: `tests/conftest.py` (register model)
- Modify: `app/api/utilities.py` (imports, guard, helpers, endpoints)
- Test: `tests/test_utility_rates.py`

- [ ] **Step 1: Register the model in the test harness first (needed for every later test)**

In `tests/conftest.py`, add `MtUtilityRate` to the model import block (after `MtUtilityWater`, line 39) and to the `_TABLES` list (after `MtUtilityWater`, line 59):

```python
# in the `from app.models import (...)` block:
    MtUtilityWater,
    MtUtilityRate,
```

```python
# in the _TABLES list:
    MtUtilityWater,
    MtUtilityRate,
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_utility_rates.py`:

```python
"""/utilities/rates — supervisor-managed current prices (one row per plant).

Only SUPERVISOR/HEAD/ADMIN may PUT; any authenticated user may GET (the
technician app reads these to display the read-only price).
"""


def test_set_and_get_rates_as_supervisor(login_as):
    sup = login_as(role="SUPERVISOR", location="A-185")
    r = sup.put("/utilities/rates", json={"plant": "A185", "diesel_rate": 100, "gas_rate": 30})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["plant"] == "A-185"          # normalized
    assert out["diesel_rate"] == 100
    assert out["gas_rate"] == 30
    assert out["set_by"] == "tester"        # StubUser default username

    got = sup.get("/utilities/rates?plant=A-185").json()
    assert len(got) == 1
    assert got[0]["diesel_rate"] == 100


def test_set_rates_forbidden_for_technician(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    r = tech.put("/utilities/rates", json={"plant": "A-185", "diesel_rate": 50})
    assert r.status_code == 403


def test_technician_may_read_rates(login_as):
    login_as(role="SUPERVISOR").put("/utilities/rates", json={"plant": "W-202", "water_rate": 24})
    tech = login_as(role="TECHNICIAN", location="W-202")
    got = tech.get("/utilities/rates?plant=W-202").json()
    assert got[0]["water_rate"] == 24


def test_set_rates_partial_update_keeps_other_rates(login_as):
    sup = login_as(role="SUPERVISOR")
    sup.put("/utilities/rates", json={"plant": "W-202", "diesel_rate": 90, "gas_rate": 30})
    sup.put("/utilities/rates", json={"plant": "W-202", "diesel_rate": 92})   # only diesel
    row = sup.get("/utilities/rates?plant=W-202").json()[0]
    assert row["diesel_rate"] == 92
    assert row["gas_rate"] == 30            # untouched


def test_set_rates_empty_body_400(login_as):
    sup = login_as(role="SUPERVISOR")
    r = sup.put("/utilities/rates", json={"plant": "A-185"})
    assert r.status_code == 400


def test_get_rates_all_plants(login_as):
    sup = login_as(role="SUPERVISOR")
    sup.put("/utilities/rates", json={"plant": "A-185", "diesel_rate": 95})
    sup.put("/utilities/rates", json={"plant": "W-202", "diesel_rate": 97})
    got = login_as(role="TECHNICIAN").get("/utilities/rates").json()
    assert {r["plant"] for r in got} == {"A-185", "W-202"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utility_rates.py -q`
Expected: FAIL / errors (404 on `/utilities/rates`, model import error until steps below).

- [ ] **Step 4: Add the `MtUtilityRate` model**

In `app/models.py`, after `MtUtilityWater`'s `__table_args__` (line 624), add:

```python
class MtUtilityRate(RdsBase):
    """Supervisor-managed current utility prices — one row per plant. The rate
    stamped onto each mt_utility_* reading is copied from here at submit time
    (see app/api/utilities.py); a technician submit cannot change it. Only
    SUPERVISOR/HEAD/ADMIN may edit (PUT /utilities/rates)."""
    __tablename__ = "mt_utility_rates"

    plant:            Mapped[str]            = mapped_column(String(16), primary_key=True)  # 'A-185' | 'W-202'
    diesel_rate:      Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    gas_rate:         Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    water_rate:       Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    electricity_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    set_by:           Mapped[str | None]     = mapped_column(String(64), nullable=True)
    set_at:           Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())
```

(`Decimal`, `datetime`, `Mapped`, `mapped_column`, `String`, `Numeric`, `DateTime`, `func` are already imported in this file — they are used by the surrounding utility models.)

- [ ] **Step 5: Add the rate schemas**

In `app/schemas.py`, after `UtilityWaterDto` (line 1025), add:

```python
class UtilityRatesDto(BaseModel):
    """Current supervisor-set prices for one plant."""
    plant: str
    diesel_rate: Optional[float] = None
    gas_rate: Optional[float] = None
    water_rate: Optional[float] = None
    electricity_rate: Optional[float] = None
    set_by: Optional[str] = None
    set_at: Optional[str] = None


class UtilityRatesUpdateRequest(BaseModel):
    """Set one or more rates for a plant. Only the fields present (non-null) are
    changed; the rest keep their current value."""
    plant: str
    diesel_rate: Optional[float] = None
    gas_rate: Optional[float] = None
    water_rate: Optional[float] = None
    electricity_rate: Optional[float] = None
```

(`BaseModel` and `Optional` are already imported at the top of `schemas.py`.)

- [ ] **Step 6: Add imports, guard, and helpers in `utilities.py`**

In `app/api/utilities.py`, extend the model import (line 23-25) and schema import (line 26-31):

```python
from ..models import (
    MtUser, MtUtilityDiesel, MtUtilityGas, MtUtilityElectricity, MtUtilityWater,
    MtUtilityRate,
)
from ..schemas import (
    UtilityDieselRequest, UtilityDieselDto,
    UtilityGasRequest, UtilityGasDto,
    UtilityElectricityRequest, UtilityElectricityDto,
    UtilityWaterRequest, UtilityWaterDto,
    UtilityRatesDto, UtilityRatesUpdateRequest,
)
```

Then, right after `_canon_plant` (line 43), add the guard, float helper, and rate lookup + DTO:

```python
_RATE_EDITOR_ROLES = {"SUPERVISOR", "HEAD", "ADMIN"}


def _require_rate_editor(user: MtUser) -> None:
    """403 unless the caller may set utility rates (SUPERVISOR/HEAD/ADMIN)."""
    if getattr(user, "norm_role", "") not in _RATE_EDITOR_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only SUPERVISOR/HEAD/ADMIN can set utility rates",
        )


def _f(v):
    """Decimal -> float; pass through None/float (SQLite already gives float)."""
    return float(v) if isinstance(v, Decimal) else v


def _current_rate(db: Session, plant: str, field: str):
    """The plant's current rate for `field` (e.g. 'diesel_rate'), or None if the
    plant has no mt_utility_rates row yet."""
    row = db.query(MtUtilityRate).filter(MtUtilityRate.plant == plant).first()
    return getattr(row, field, None) if row else None


def _rates_to_dto(row: MtUtilityRate) -> UtilityRatesDto:
    return UtilityRatesDto(
        plant=row.plant,
        diesel_rate=_f(row.diesel_rate), gas_rate=_f(row.gas_rate),
        water_rate=_f(row.water_rate), electricity_rate=_f(row.electricity_rate),
        set_by=row.set_by, set_at=iso_z(row.set_at),
    )
```

- [ ] **Step 7: Add the GET/PUT `/rates` endpoints**

In `app/api/utilities.py`, at the end of the file, add:

```python
# --- Rates (supervisor-managed current prices) ------------------------------

@router.get("/rates", response_model=List[UtilityRatesDto])
def get_rates(
    plant: Optional[str] = Query(None),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Current prices, one row per plant. `plant` optional (omit for both).
    Any authenticated caller — the technician app reads these to display the
    read-only price."""
    q = db.query(MtUtilityRate)
    if plant:
        q = q.filter(MtUtilityRate.plant == _canon_plant(plant))
    return [_rates_to_dto(r) for r in q.order_by(MtUtilityRate.plant).all()]


@router.put("/rates", response_model=UtilityRatesDto)
def set_rates(
    req: UtilityRatesUpdateRequest,
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Set one or more rates for a plant (SUPERVISOR/HEAD/ADMIN). Partial: only
    the rates present in the body change; the rest are kept."""
    _require_rate_editor(user)
    plant = _canon_plant(req.plant)
    changes = req.model_dump(exclude={"plant"}, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="no rate fields provided")
    row = db.query(MtUtilityRate).filter(MtUtilityRate.plant == plant).first()
    if row is None:
        row = MtUtilityRate(plant=plant, set_by=user.username, **changes)
        db.add(row)
    else:
        for k, v in changes.items():
            setattr(row, k, v)
        row.set_by = user.username
        row.set_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _rates_to_dto(row)
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utility_rates.py -q`
Expected: PASS (all 6 tests in the file so far).

- [ ] **Step 9: Commit**

```bash
cd "d:/Maintenance module/backend" && git add app/models.py app/schemas.py app/api/utilities.py tests/conftest.py tests/test_utility_rates.py && git commit -m "feat(utilities): supervisor-managed utility rates table + GET/PUT /utilities/rates"
```

---

## Task 2: Rate override + server-side cost recompute on submit

**Files:**
- Modify: `app/api/utilities.py` (recompute helpers + `_upsert` + 4 POST handlers)
- Test: `tests/test_utility_rates.py` (append)
- Modify: `tests/test_utilities.py` (fix 2 tests that assumed client-trusted rate)

- [ ] **Step 1: Write the failing test (append to `tests/test_utility_rates.py`)**

```python
def test_diesel_submit_uses_supervisor_rate_and_recomputes(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "diesel_rate": 100})
    tech = login_as(role="TECHNICIAN", location="A-185")
    body = {"plant": "A-185", "reading_date": "2026-05-01",
            "initial_kwh_reading": 71629, "final_kwh_reading": 71815,
            "start_dg_run_hour": 100, "stop_dg_run_hour": 110,
            "diesel_l_per_hour": 37.5,
            "diesel_rate": 1,            # bogus — must be ignored
            "total_fuel_cost": 999999}   # bogus — must be recomputed
    out = tech.post("/utilities/diesel", json=body).json()
    assert out["diesel_rate"] == 100         # from config, not the body
    assert out["total_consumption"] == 186   # 71815 - 71629
    assert out["total_run_hour"] == 10       # 110 - 100
    assert out["total_diesel_l"] == 375      # 37.5 * 10
    assert out["total_fuel_cost"] == 37500   # 375 * 100


def test_water_cost_per_unit_null_when_production_zero(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "water_rate": 24})
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.post("/utilities/water", json={
        "plant": "A-185", "reading_date": "2026-05-02",
        "water_meter_opening": 10, "water_meter_closing": 20,
        "production_units": 0}).json()
    assert out["water_consumed"] == 10
    assert out["daily_water_cost"] == 240    # 10 * 24
    assert out["cost_per_unit"] is None       # div-by-zero -> null


def test_submit_with_no_config_rate_stores_null_cost(login_as):
    # No rate set for W-202 -> rate overridden to null -> cost null.
    tech = login_as(role="TECHNICIAN", location="W-202")
    out = tech.post("/utilities/water", json={
        "plant": "W-202", "reading_date": "2026-05-03",
        "water_meter_opening": 10, "water_meter_closing": 20,
        "water_rate": 999, "daily_water_cost": 999}).json()
    assert out["water_rate"] is None
    assert out["water_consumed"] == 10        # consumption still computed
    assert out["daily_water_cost"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utility_rates.py -q -k "recompute or production_zero or no_config_rate"`
Expected: FAIL (rate not overridden; costs still client values).

- [ ] **Step 3: Add recompute helpers in `utilities.py`**

In `app/api/utilities.py`, after `_rates_to_dto` (from Task 1), add. Each takes the mutable `values` dict (the request minus plant/date/created_by) and the resolved `rate` (float or None), overwrites the rate field, and recomputes derived columns null-safely:

```python
# --- Server-side recompute (authoritative rate + derived costs) -------------
# `values` is the request payload minus plant/reading_date/created_by. Each
# helper overwrites the rate field with the config value and recomputes the
# derived columns from the client's meter readings + factors. Any missing input
# leaves its derived column None (partial saves stay allowed); cost_per_unit is
# None when production_units is 0/blank.

def _sub(a, b):
    return (a - b) if a is not None and b is not None else None


def _mul(a, b):
    return (a * b) if a is not None and b is not None else None


def _per_unit(cost, production_units):
    return (cost / production_units) if cost is not None and production_units not in (None, 0) else None


def _recompute_diesel(values: dict, rate) -> None:
    values["diesel_rate"] = rate
    values["total_consumption"] = _sub(values.get("final_kwh_reading"), values.get("initial_kwh_reading"))
    values["total_run_hour"] = _sub(values.get("stop_dg_run_hour"), values.get("start_dg_run_hour"))
    values["total_diesel_l"] = _mul(values.get("diesel_l_per_hour"), values["total_run_hour"])
    values["total_fuel_cost"] = _mul(values["total_diesel_l"], rate)


def _recompute_gas(values: dict, rate) -> None:
    values["gas_rate"] = rate
    consumed = _mul(_sub(values.get("gas_meter_closing"), values.get("gas_meter_opening")),
                    values.get("gas_conversion_factor"))
    values["gas_consumed_m3"] = consumed
    values["daily_gas_cost"] = _mul(consumed, rate)
    values["cost_per_unit"] = _per_unit(values["daily_gas_cost"], values.get("production_units"))


def _recompute_electricity(values: dict, rate) -> None:
    values["electricity_rate"] = rate
    consumed_kwh = _mul(_sub(values.get("energy_meter_closing_kwh"), values.get("energy_meter_opening_kwh")),
                        values.get("ct_multiplier"))
    values["electricity_consumed_kwh"] = consumed_kwh
    values["electricity_consumed_kvah"] = _sub(values.get("energy_meter_closing_kvah"),
                                               values.get("energy_meter_opening_kvah"))
    values["daily_electricity_cost"] = _mul(consumed_kwh, rate)
    values["cost_per_unit"] = _per_unit(values["daily_electricity_cost"], values.get("production_units"))


def _recompute_water(values: dict, rate) -> None:
    values["water_rate"] = rate
    consumed = _sub(values.get("water_meter_closing"), values.get("water_meter_opening"))
    values["water_consumed"] = consumed
    values["daily_water_cost"] = _mul(consumed, rate)
    values["cost_per_unit"] = _per_unit(values["daily_water_cost"], values.get("production_units"))
```

- [ ] **Step 4: Wire recompute into `_upsert`**

In `app/api/utilities.py`, change the `_upsert` signature and body. Replace lines 84-109 (the whole `_upsert` function) with:

```python
def _upsert(
    db: Session, Model, DtoCls: Type[BaseModel], req: BaseModel, user: MtUser,
    pairs: Sequence[Tuple[str, Optional[float], Optional[float]]] = (),
    recompute=None, rate_field: Optional[str] = None,
) -> BaseModel:
    """Insert, or overwrite the existing (plant, reading_date) row. The rate is
    NOT trusted from the client: `recompute` stamps the current supervisor rate
    (from mt_utility_rates) onto the row and recomputes the derived costs."""
    plant = _canon_plant(req.plant)
    rdate = _parse_reading_date(req.reading_date)
    _check_closing_not_less_than_opening(pairs)
    values = req.model_dump(exclude={"plant", "reading_date", "created_by"})
    if recompute is not None and rate_field is not None:
        recompute(values, _f(_current_rate(db, plant, rate_field)))

    row = (
        db.query(Model)
        .filter(Model.plant == plant, Model.reading_date == rdate)
        .first()
    )
    if row is None:
        row = Model(plant=plant, reading_date=rdate, created_by=user.username, **values)
        db.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
        row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _row_to_dto(DtoCls, row)
```

- [ ] **Step 5: Pass recompute + rate_field from each POST handler**

In `app/api/utilities.py`, update the 4 `_upsert` calls in the POST handlers:

```python
# upsert_diesel:
    return _upsert(db, MtUtilityDiesel, UtilityDieselDto, req, user, pairs,
                   _recompute_diesel, "diesel_rate")
# upsert_gas:
    return _upsert(db, MtUtilityGas, UtilityGasDto, req, user, pairs,
                   _recompute_gas, "gas_rate")
# upsert_electricity:
    return _upsert(db, MtUtilityElectricity, UtilityElectricityDto, req, user, pairs,
                   _recompute_electricity, "electricity_rate")
# upsert_water:
    return _upsert(db, MtUtilityWater, UtilityWaterDto, req, user, pairs,
                   _recompute_water, "water_rate")
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utility_rates.py -q`
Expected: PASS.

- [ ] **Step 7: Fix the 2 existing tests that assumed a client-trusted rate**

The recompute change makes rate/cost authoritative from config, so two tests in `tests/test_utilities.py` must set a rate first. Replace `test_water_upsert_stores_inputs_and_computed` (lines 9-29) with:

```python
def test_water_upsert_stores_inputs_and_recomputed(login_as, db_session):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "water_rate": 24})
    c = login_as(role="TECHNICIAN", location="A-185")
    body = {
        "plant": "A185", "reading_date": "2026-04-01",         # compact plant spelling
        "water_meter_opening": 402.971, "water_meter_closing": 426.86,
        "water_rate": 999, "production_units": None,            # 999 must be ignored
        "remark": "ok",
    }
    r = c.post("/utilities/water", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["plant"] == "A-185"                              # normalized
    assert out["water_rate"] == 24                              # from config, not 999
    assert out["water_consumed"] == 23.889                      # 426.86 - 402.971
    assert round(out["daily_water_cost"], 2) == 573.34          # 23.889 * 24
    assert out["cost_per_unit"] is None                         # production None -> null
    assert isinstance(out["id"], int)

    row = db_session.query(MtUtilityWater).one()
    assert row.plant == "A-185"
    assert float(row.water_consumed) == 23.889
```

And replace `test_upsert_is_idempotent_on_plant_and_date` (lines 32-42) with:

```python
def test_upsert_is_idempotent_on_plant_and_date(login_as, db_session):
    login_as(role="SUPERVISOR", location="W-202").put(
        "/utilities/rates", json={"plant": "W-202", "water_rate": 24})
    c = login_as(role="TECHNICIAN", location="W-202")
    base = {"plant": "W-202", "reading_date": "2026-04-02",
            "water_meter_opening": 10, "water_meter_closing": 15}
    r1 = c.post("/utilities/water", json=base)
    # same plant+date, corrected reading -> should UPDATE the same row, not insert
    r2 = c.post("/utilities/water", json={**base, "water_meter_closing": 20})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]                   # same row
    assert db_session.query(MtUtilityWater).count() == 1
    assert float(db_session.query(MtUtilityWater).one().daily_water_cost) == 240.0  # (20-10)*24
```

- [ ] **Step 8: Run the full utilities suite to confirm nothing else regressed**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utilities.py tests/test_utility_rates.py -q`
Expected: PASS. (The diesel/gas/electricity `closing < opening` 400 tests still pass — validation runs before recompute; `test_diesel_upsert_and_list_roundtrip` still gets `total_consumption == 186` from recompute.)

- [ ] **Step 9: Commit**

```bash
cd "d:/Maintenance module/backend" && git add app/api/utilities.py tests/test_utilities.py tests/test_utility_rates.py && git commit -m "feat(utilities): override client rate from config + recompute costs server-side"
```

---

## Task 3: `GET /utilities/{utility}/prefill` — opening from previous closing

**Files:**
- Modify: `app/schemas.py` (add `UtilityPrefillDto`)
- Modify: `app/api/utilities.py` (prefill map + endpoint)
- Test: `tests/test_utility_rates.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_utility_rates.py`)**

```python
def test_prefill_uses_last_actual_closing_across_skipped_day(login_as):
    login_as(role="SUPERVISOR", location="A-185").put(
        "/utilities/rates", json={"plant": "A-185", "water_rate": 24})
    tech = login_as(role="TECHNICIAN", location="A-185")
    tech.post("/utilities/water", json={"plant": "A-185", "reading_date": "2026-06-01",
                                        "water_meter_opening": 10, "water_meter_closing": 20})
    # 2026-06-02 skipped; open the 2026-06-03 form
    out = tech.get("/utilities/water/prefill?plant=A-185&date=2026-06-03").json()
    assert out["openings"]["water_meter_opening"] == 20   # previous closing
    assert out["source_date"] == "2026-06-01"
    assert out["rate"] == 24


def test_prefill_diesel_maps_both_opening_fields(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    tech.post("/utilities/diesel", json={"plant": "A-185", "reading_date": "2026-06-01",
                                         "initial_kwh_reading": 100, "final_kwh_reading": 150,
                                         "start_dg_run_hour": 5, "stop_dg_run_hour": 9})
    out = tech.get("/utilities/diesel/prefill?plant=A-185&date=2026-06-02").json()
    assert out["openings"]["initial_kwh_reading"] == 150   # <- final
    assert out["openings"]["start_dg_run_hour"] == 9       # <- stop


def test_prefill_null_when_no_earlier_row(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    out = tech.get("/utilities/water/prefill?plant=A-185&date=2026-06-01").json()
    assert out["openings"]["water_meter_opening"] is None
    assert out["source_date"] is None


def test_prefill_unknown_utility_404(login_as):
    tech = login_as(role="TECHNICIAN", location="A-185")
    assert tech.get("/utilities/plutonium/prefill?plant=A-185").status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utility_rates.py -q -k prefill`
Expected: FAIL (404 on the prefill path / no route).

- [ ] **Step 3: Add the `UtilityPrefillDto` schema**

In `app/schemas.py`, after `UtilityRatesUpdateRequest` (from Task 1), add:

```python
class UtilityPrefillDto(BaseModel):
    """Form pre-fill: opening meter fields copied from the previous reading's
    closing values, plus the current supervisor rate for the utility. The
    `openings` keys are the opening fields the target form needs."""
    plant: str
    utility: str
    reading_date: str
    source_date: Optional[str] = None            # the previous row's date; None if none
    rate: Optional[float] = None
    openings: dict
```

- [ ] **Step 4: Add the prefill map + endpoint in `utilities.py`**

First extend the schema import (add `UtilityPrefillDto` to the `from ..schemas import (...)` block). Then, at the end of `app/api/utilities.py`, add:

```python
# --- Prefill (opening <- previous closing) ----------------------------------
# For each utility: (Model, rate field, {opening_field: previous_closing_field}).
_PREFILL_MAP = {
    "diesel":      (MtUtilityDiesel, "diesel_rate",
                    {"initial_kwh_reading": "final_kwh_reading",
                     "start_dg_run_hour": "stop_dg_run_hour"}),
    "gas":         (MtUtilityGas, "gas_rate",
                    {"gas_meter_opening": "gas_meter_closing"}),
    "electricity": (MtUtilityElectricity, "electricity_rate",
                    {"energy_meter_opening_kwh": "energy_meter_closing_kwh",
                     "energy_meter_opening_kvah": "energy_meter_closing_kvah"}),
    "water":       (MtUtilityWater, "water_rate",
                    {"water_meter_opening": "water_meter_closing"}),
}


@router.get("/{utility}/prefill", response_model=UtilityPrefillDto)
def prefill(
    utility: str,
    plant: str = Query(...),
    date_q: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_rds), user: MtUser = Depends(get_current_user),
):
    """Opening values for a new reading form, copied from the most recent EARLIER
    row's closing (survives skipped days), plus the current rate. `date` defaults
    to today."""
    cfg = _PREFILL_MAP.get(utility)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"unknown utility {utility!r}")
    Model, rate_field, mapping = cfg
    cplant = _canon_plant(plant)
    rdate = _parse_reading_date(date_q) if date_q else date.today()
    prev = (
        db.query(Model)
        .filter(Model.plant == cplant, Model.reading_date < rdate)
        .order_by(Model.reading_date.desc(), Model.id.desc())
        .first()
    )
    openings = {
        open_field: (_f(getattr(prev, close_field, None)) if prev else None)
        for open_field, close_field in mapping.items()
    }
    return UtilityPrefillDto(
        plant=cplant, utility=utility, reading_date=rdate.isoformat(),
        source_date=prev.reading_date.isoformat() if prev else None,
        rate=_f(_current_rate(db, cplant, rate_field)),
        openings=openings,
    )
```

Note: `date` (the class) is already imported at the top (`from datetime import date, datetime`); the query param is named `date_q` (alias `date`) precisely so it does not shadow the class used by `date.today()`.

- [ ] **Step 5: Run the prefill tests to verify they pass**

Run: `cd "d:/Maintenance module/backend" && python -m pytest tests/test_utility_rates.py -q -k prefill`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "d:/Maintenance module/backend" && git add app/schemas.py app/api/utilities.py tests/test_utility_rates.py && git commit -m "feat(utilities): GET /utilities/{utility}/prefill — opening from previous closing + current rate"
```

---

## Task 4: Migration SQL (manual pgAdmin) + full-suite verification

**Files:**
- Create: `migrations/2026-07-22_utility_rates.sql`

- [ ] **Step 1: Write the migration**

Create `migrations/2026-07-22_utility_rates.sql`:

```sql
-- ============================================================================
-- 2026-07-22  mt_utility_rates — supervisor-managed current utility prices.
--
-- One row per plant. The rate stamped onto each mt_utility_* reading is copied
-- from here at submit time (app/api/utilities.py); a technician submit cannot
-- change it. Only SUPERVISOR/HEAD/ADMIN edit via PUT /utilities/rates.
--
-- Run once against RDS Postgres (pgAdmin), BEFORE deploying the code. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mt_utility_rates (
    plant            VARCHAR(16) PRIMARY KEY,   -- 'A-185' | 'W-202'
    diesel_rate      NUMERIC(10,2),
    gas_rate         NUMERIC(10,4),
    water_rate       NUMERIC(10,4),
    electricity_rate NUMERIC(10,4),
    set_by           VARCHAR(64),
    set_at           TIMESTAMP DEFAULT now()
);

-- Seed both plants from each plant's most recent existing reading row, so the
-- authoritative rate matches what was already in use. Diesel falls back to 95
-- (its column default) when a plant has no diesel row yet. Re-runnable: existing
-- rows are left untouched (ON CONFLICT DO NOTHING).
INSERT INTO mt_utility_rates (plant, diesel_rate, gas_rate, water_rate, electricity_rate, set_by)
SELECT p.plant,
       COALESCE((SELECT d.diesel_rate       FROM mt_utility_diesel      d WHERE d.plant = p.plant ORDER BY d.reading_date DESC, d.id DESC LIMIT 1), 95),
                (SELECT g.gas_rate           FROM mt_utility_gas         g WHERE g.plant = p.plant ORDER BY g.reading_date DESC, g.id DESC LIMIT 1),
                (SELECT w.water_rate         FROM mt_utility_water       w WHERE w.plant = p.plant ORDER BY w.reading_date DESC, w.id DESC LIMIT 1),
                (SELECT e.electricity_rate   FROM mt_utility_electricity e WHERE e.plant = p.plant ORDER BY e.reading_date DESC, e.id DESC LIMIT 1),
       'seed'
FROM (VALUES ('A-185'), ('W-202')) AS p(plant)
ON CONFLICT (plant) DO NOTHING;
```

- [ ] **Step 2: Run the whole test suite**

Run: `cd "d:/Maintenance module/backend" && python -m pytest -q`
Expected: PASS (no regressions across the suite).

- [ ] **Step 3: Commit**

```bash
cd "d:/Maintenance module/backend" && git add migrations/2026-07-22_utility_rates.sql && git commit -m "chore(migrations): mt_utility_rates create + seed (manual pgAdmin)"
```

---

## Task 5: Frontend handoff doc + memory note

**Files:**
- Create: `docs/handoff/2026-07-22-utility-rates-frontend.md`
- Update memory (`MEMORY.md` + a new project memory file)

- [ ] **Step 1: Write the Kotlin handoff**

Create `docs/handoff/2026-07-22-utility-rates-frontend.md`:

```markdown
# Frontend handoff — Utility rates read-only + prefill (2026-07-22)

App: `D:\Maintenance module\FactoryOps\app`. Backend-only change; this is written
guidance for the Kotlin team.

## Technician daily-reading forms (Diesel / Gas / Electricity / Water)
1. On opening a form, call `GET /utilities/{utility}/prefill?plant=<P>&date=<YYYY-MM-DD>`
   (`utility` = diesel|gas|electricity|water). Response:
   `{ plant, utility, reading_date, source_date, rate, openings: {field: value} }`.
   - Populate the opening meter field(s) from `openings` (keys match the field
     names, e.g. `water_meter_opening`, `initial_kwh_reading`+`start_dg_run_hour`).
   - Show `rate` as a **read-only** price (label, not an input). Technician cannot
     edit it. `rate` may be null until the supervisor sets it.
2. The app may still compute cost locally for a live preview, but the stored value
   is the backend's — any rate/cost POSTed is overwritten server-side.

## Supervisor "Utility Rates" screen (new)
- Load current prices: `GET /utilities/rates?plant=<P>` -> list, take [0].
- Save: `PUT /utilities/rates` with `{ plant, diesel_rate?, gas_rate?, water_rate?,
  electricity_rate? }` (send only the ones being changed). 403 for non
  SUPERVISOR/HEAD/ADMIN roles — show the entry point only to those roles.

## Backward compatibility
Old builds keep working: any rate/cost they POST is silently overridden and
recomputed server-side.
```

- [ ] **Step 2: Commit the handoff**

```bash
cd "d:/Maintenance module/backend" && git add docs/handoff/2026-07-22-utility-rates-frontend.md && git commit -m "docs: Kotlin handoff for utility rates read-only + prefill"
```

- [ ] **Step 3: Update memory**

Create `C:\Users\lohar\.claude\projects\d--Maintenance-module-backend\memory\project_utility_rates.md`:

```markdown
---
name: project-utility-rates
description: Utility prices are supervisor-set (mt_utility_rates); technician rate is read-only + server-recomputed; prefill endpoint
metadata:
  type: project
---

2026-07-22: Utility rates (diesel/gas/water/electricity) are now supervisor-managed.
New table `mt_utility_rates` (one row per plant) is the source of truth. `PUT
/utilities/rates` (SUPERVISOR/HEAD/ADMIN) sets them; `GET /utilities/rates` reads.
Every technician submit to /utilities/{diesel,gas,electricity,water} has its rate
overwritten from this table and its cost columns recomputed server-side (these 4
tables are no longer client-trusted pass-through). `GET /utilities/{utility}/prefill?
plant=&date=` returns opening fields from the previous reading's closing (last
actual earlier row, survives skipped days) + current rate. Migration:
migrations/2026-07-22_utility_rates.sql (manual pgAdmin). Frontend handoff:
docs/handoff/2026-07-22-utility-rates-frontend.md. Relates to [[reference-schema-migrations]].
```

Then add one line to `C:\Users\lohar\.claude\projects\d--Maintenance-module-backend\memory\MEMORY.md`:

```markdown
- [Utility rates](project_utility_rates.md) — supervisor-set prices (mt_utility_rates); technician rate read-only + server-recomputed; /utilities/rates + /prefill
```

(No git commit for memory files — they live outside the repo.)

---

## Self-Review

**Spec coverage:**
- Rate lock (supervisor sets, technician read-only) → Task 1 (endpoints + guard) + Task 2 (override on submit). ✓
- Backend overrides + recomputes → Task 2. ✓
- `mt_utility_rates` table + per-plant + seed → Task 1 (model) + Task 4 (migration seed). ✓
- Rate endpoints GET/PUT with role guard → Task 1. ✓
- Previous-closing auto-fill, last-actual-earlier-row semantics, field mapping → Task 3. ✓
- SUPERVISOR+HEAD+ADMIN edit roles → Task 1 (`_RATE_EDITOR_ROLES`). ✓
- Error handling (403 / 400 / 404 / 400 bad date) → Tasks 1 & 3 tests. ✓
- Frontend handoff → Task 5. ✓
- Testing list from spec → covered across Tasks 1-3 test files. ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `_f`, `_current_rate`, `_recompute_*(values, rate)`, `_upsert(..., recompute, rate_field)`, `_PREFILL_MAP`, `UtilityRatesDto`, `UtilityRatesUpdateRequest`, `UtilityPrefillDto` are used consistently across tasks. Prefill query param `date_q` (alias `date`) deliberately avoids shadowing the imported `date` class. Rate is normalized to float via `_f` before recompute so Decimal (PG) and float (SQLite) never mix.
