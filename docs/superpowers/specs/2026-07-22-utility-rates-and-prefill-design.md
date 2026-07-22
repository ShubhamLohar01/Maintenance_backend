# Utility Rates (supervisor-managed) + previous-closing auto-fill — Design

**Date:** 2026-07-22
**Area:** Backend (`app/api/utilities.py` + models/schemas/migrations) and a Kotlin frontend handoff
**Status:** Approved for planning

## Problem

In the technician's **Daily Reading** section, each utility form (Diesel / Gas /
Electricity / Water) exposes a **price/rate** field (`diesel_rate`, `gas_rate`,
`water_rate`, `electricity_rate`). Today these are technician-editable and the
Android app computes cost client-side and POSTs it, with the backend
([app/api/utilities.py](../../../app/api/utilities.py)) acting as a pure
pass-through upsert on `(plant, reading_date)`.

Two changes are wanted:

1. **Rate lock.** A technician should *see* the rate but not edit or insert it.
   The **supervisor** sets the rate. Once set, that value **follows every
   technician submit until the supervisor changes it**.
2. **Previous-closing auto-fill.** When a technician opens a form to log a
   reading, the **opening** meter fields should auto-fill from the **previous
   date's closing** (read from the existing `mt_utility_*` tables).

## Decisions (locked during brainstorming)

- **Locked fields = rates only.** `diesel_rate`, `gas_rate`, `water_rate`,
  `electricity_rate`. Meter readings, `production_units`, and the *factor*
  fields (`diesel_l_per_hour`, `gas_conversion_factor`, `ct_multiplier`) stay
  technician-entered.
- **Enforcement = backend overrides + recomputes.** The backend ignores any
  rate the client sends, stamps the current supervisor rate onto the row, and
  **recomputes the cost columns server-side** so numbers cannot be faked.
- **"Previous date" = last actual earlier reading** (`reading_date < date`,
  latest first), not strictly `date - 1` — survives skipped days because meters
  are cumulative.
- **Who may set rates = SUPERVISOR + HEAD + ADMIN** (consistent with the asset
  register edit roles in `app/api/mt_machines.py`).

## Architecture

### New table `mt_utility_rates` — the "current prices"

One row **per plant**, the single source of truth for the four rates:

```
mt_utility_rates(
  plant             VARCHAR(16) PRIMARY KEY,   -- 'A-185' | 'W-202'
  diesel_rate       NUMERIC(10,2),
  gas_rate          NUMERIC(10,4),
  water_rate        NUMERIC(10,4),
  electricity_rate  NUMERIC(10,4),
  set_by            VARCHAR(64),
  set_at            TIMESTAMP DEFAULT now()
)
```

Numeric precisions mirror the corresponding columns on the reading tables.
Migration: `migrations/2026-07-22_utility_rates.sql` — idempotent
`CREATE TABLE IF NOT EXISTS` + seed (run manually in pgAdmin, per the project's
no-Alembic workflow). **Seed** both plants: `diesel_rate` defaults to `95`;
`gas_rate` / `water_rate` / `electricity_rate` are seeded from each plant's most
recent existing reading row (via `SELECT ... ORDER BY reading_date DESC LIMIT 1`)
so current behavior does not regress, falling back to `NULL` when a plant has no
rows yet.

### Endpoints (all in `app/api/utilities.py`)

| Method + path | Auth | Purpose |
|---|---|---|
| `GET /utilities/rates?plant=` | any authenticated | Read current rates + `set_by`/`set_at` for a plant (so the technician app can *display* the read-only price). `plant` optional → both plants. |
| `PUT /utilities/rates` | SUPERVISOR / HEAD / ADMIN | Set one or more rates for a plant. **Partial**: only the rates present in the body change; the rest keep their current value. Stamps `set_by`/`set_at`. Technician → **403**. |
| `GET /utilities/{utility}/prefill?plant=&date=` | any authenticated | `utility ∈ {diesel, gas, electricity, water}`. Returns the previous closing(s) mapped to this form's opening fields + the current rate for that utility. |

### Rate lock in `_upsert` (the enforcement)

`_upsert` (shared by all four POST handlers) is extended so that, before
persisting a row:

1. Look up the plant's row in `mt_utility_rates`.
2. **Overwrite** the incoming rate field with the config value (ignore whatever
   the client sent). A submit for a plant/utility whose rate is unset (`NULL`)
   stores `NULL` and yields `NULL` cost — the supervisor must set it first.
3. **Recompute** the derived cost columns server-side from the client's meter
   readings + factors and the config rate, using the formulas already documented
   on each model. This flips these four tables from client-trusted pass-through
   to **server-authoritative** for rate + derived costs.

Recompute is **null-safe**: any missing input leaves its derived column `NULL`
(partial saves stay allowed); `cost_per_unit` is `NULL` when `production_units`
is `0`/blank. Formulas (authoritative, server-side):

- **diesel:** `total_consumption = final_kwh - initial_kwh`;
  `total_run_hour = stop - start`;
  `total_diesel_l = diesel_l_per_hour * total_run_hour`;
  `total_fuel_cost = total_diesel_l * diesel_rate`
- **gas:** `gas_consumed_m3 = (closing - opening) * gas_conversion_factor`;
  `daily_gas_cost = gas_consumed_m3 * gas_rate`;
  `cost_per_unit = daily_gas_cost / production_units`
- **electricity:** `consumed_kwh = (close_kwh - open_kwh) * ct_multiplier`;
  `consumed_kvah = close_kvah - open_kvah`;
  `daily_electricity_cost = consumed_kwh * electricity_rate`;
  `cost_per_unit = daily_electricity_cost / production_units`
- **water:** `water_consumed = closing - opening`;
  `daily_water_cost = water_consumed * water_rate`;
  `cost_per_unit = daily_water_cost / production_units`

### Previous-closing auto-fill

`GET /utilities/{utility}/prefill?plant=&date=` finds the most recent row with
`reading_date < date` for that plant and returns the closing(s) mapped to the
opening field name(s) the form needs, plus the current rate. Field mapping:

| Utility | Opening field(s) ← previous closing |
|---|---|
| diesel | `initial_kwh_reading` ← `final_kwh_reading`; `start_dg_run_hour` ← `stop_dg_run_hour` |
| gas | `gas_meter_opening` ← `gas_meter_closing` |
| electricity | `energy_meter_opening_kwh` ← `energy_meter_closing_kwh`; `energy_meter_opening_kvah` ← `energy_meter_closing_kvah` |
| water | `water_meter_opening` ← `water_meter_closing` |

When no earlier row exists, the opening fields come back `NULL` (technician types
them for the first-ever reading). `date` defaults to today when omitted.

## Data flow

**Technician logs a reading:**
1. App opens the form → `GET /utilities/diesel/prefill?plant=W-202&date=…` →
   opening fields pre-filled, rate shown read-only.
2. Technician fills closings/factors → POST `/utilities/diesel` (may include a
   rate; it is ignored).
3. Backend overwrites rate from `mt_utility_rates`, recomputes costs, upserts.

**Supervisor changes a price:**
1. Supervisor screen → `PUT /utilities/rates {plant, diesel_rate: 98}`.
2. Every subsequent technician submit for that plant uses `98`. Already-saved
   rows are **not** retroactively changed (each row keeps the rate in effect
   when it was submitted).

## Components (touch-points)

- `app/models.py` — add `MtUtilityRate`.
- `app/schemas.py` — `UtilityRatesDto`, `UtilityRatesUpdateRequest`, and four
  `*PrefillDto` (or one generic prefill DTO per utility).
- `app/api/utilities.py` — 3 new endpoints, recompute helpers, rate-override in
  `_upsert`, a `_require_rate_editor(user)` guard.
- `migrations/2026-07-22_utility_rates.sql` — create + seed.
- `tests/test_utilities.py` — see Testing.

## Error handling

- `PUT /utilities/rates` by a non-editor role → **403** (message names the
  allowed roles), mirroring `asset_schedules._require_supervisor`.
- Unknown `plant` → **400** (existing `_canon_plant`).
- Unknown `utility` path segment on prefill → **404**.
- Bad/missing `date` on prefill → **400** (reuse `_parse_reading_date`; default
  to today when omitted rather than erroring).

## Testing

Extend `tests/test_utilities.py`:

- Technician POST with a bogus `diesel_rate` → stored row has the **config**
  rate, and `total_fuel_cost` matches the server recompute (not the client's).
- Supervisor `PUT /utilities/rates` changes the value; a later submit uses it;
  an earlier row is unchanged.
- `PUT /utilities/rates` as TECHNICIAN/OPERATOR → 403.
- Partial `PUT` changes only the sent rate, leaves others intact.
- `prefill` returns the last actual closing across a **skipped day**; returns
  `NULL` opening when no earlier row; correct closing→opening mapping per
  utility.
- Recompute null-safety: partial inputs → `NULL` derived columns; zero
  `production_units` → `NULL cost_per_unit`.

## Frontend handoff (Kotlin — `D:\Maintenance module\FactoryOps\app`)

Backend-only workflow: the following is written guidance for the Kotlin team; no
edits are made to `FactoryOps\` from this repo.

- **Technician daily-reading forms:** make each rate field **read-only**
  (display, not input). On opening a form, call
  `GET /utilities/{utility}/prefill?plant=&date=` and populate the opening
  meter field(s) **and** the read-only rate from the response. The app may still
  compute cost locally for a live preview, but the stored value is the
  backend's.
- **New supervisor "Utility Rates" screen:** shows current rates
  (`GET /utilities/rates?plant=`) and saves changes with
  `PUT /utilities/rates`. Show this entry point only to SUPERVISOR/HEAD/ADMIN.
- **Backward compatibility:** old app builds keep working — any rate/cost they
  POST is silently overridden and recomputed server-side.

## Out of scope (YAGNI)

- Rate **history** / effective-dating (only the current value is stored; the
  per-row rate on each reading is the historical record).
- Locking the factor fields (`diesel_l_per_hour`, `gas_conversion_factor`,
  `ct_multiplier`).
- Retroactive recompute of already-saved rows when a rate changes.
