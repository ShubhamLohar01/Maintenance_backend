# Prompt — Build Phase 3 Backend (Machines module)

You are starting **Phase 3** of the FactoryOps project: the real **FastAPI + PostgreSQL** backend. The Android app (Kotlin, MVVM + Hilt + Room + Retrofit) is ~90% done and currently runs against an in-app mock (`BuildConfig.USE_MOCK_API=true`). This prompt covers the **Machines** module only. A separate prompt will cover Users / Auth.

> **Workflow rule (non-negotiable):** do NOT write code yet. First confirm your understanding, ask clarifying questions, and propose the dependency / project layout. Wait for explicit approval before scaffolding anything. Build incrementally and verify each step.

---

## 1. Inputs

- **Excel source of truth:** `D:\Maintenance module\FactoryOps\machine-list.xlsx`
  - Single sheet `Sheet1`, **215 rows × 9 columns**, header row 1.
  - Columns (verbatim):
    | # | Header | Notes |
    |---|--------|-------|
    | 1 | `machine_id` | Format `MCH-0001` … `MCH-0214` (zero-padded, contiguous so far) |
    | 2 | `floor` | E.g. `Lower basement`, `service floor`, … (more floors below row 24 — re-read the file) |
    | 3 | `machine_name` | Free text, sometimes misspelled (`Drian pump`, `tubes light`, `1nps`) |
    | 4 | `company` | Mostly empty |
    | 5 | `model_no` | Mostly empty |
    | 6 | `serial_no` | Mostly empty |
    | 7 | `rated_kw` | Sparse, **mixed units in free text**: `508watt`, `1.5kw`, `150W`, `120W`, `2.5kw` |
    | 8 | `rated_amps` | Mostly empty |
    | 9 | `quantity` | Text like `1nos`, `1 nos`, `3nos`, `34nos`, `1nps` (typo). Some rows represent **N identical units** (e.g. 34 tube lights on one row) |

- **Frontend contract (must keep working without app rebuild)** — read these files and treat their field names + JSON shape as the API contract:
  - `app/src/main/java/com/candorfoods/factoryops/domain/model/Machine.kt`
  - `app/src/main/java/com/candorfoods/factoryops/data/remote/dto/MachineDtos.kt` (snake_case JSON keys via `@SerialName`)
  - `app/src/main/java/com/candorfoods/factoryops/data/remote/api/MachineApi.kt` — currently exposes `GET machines/assigned` with `Authorization` header.
  - `app/src/main/java/com/candorfoods/factoryops/domain/model/Enums.kt` — preserve these exactly:
    - `MachineType { ROASTER, COMPRESSOR, PACKING_LINE, CONVEYOR, WEIGHING_SCALE, DG_SET, HVAC, BOILER, MIXER, WELDING, PUMP, OTHER }`
    - `MachineStatus { IDLE, RUNNING, STOPPED, FLAGGED, PENDING_QC }`
    - `Criticality { A, B, C }`
    - `LoadFactorSource { ASSUMED, SPOT_MEASURED, IOT_METERED }`

- **Existing mock seed for reference only:** `app/src/main/java/com/candorfoods/factoryops/data/remote/mock/` — shows the field values the UI already handles (7 machines, MachineType + Criticality + LoadFactor pre-assigned). Treat as illustrative, NOT authoritative.

---

## 2. Deliverable scope (Machines module only)

1. **PostgreSQL schema** for `machines` (and any lookup tables you propose, e.g. `plants`, `floors`).
2. **Alembic migration** to create that schema from empty DB.
3. **Excel → DB seed script** that ingests `machine-list.xlsx` into the schema, including unit normalization and quantity expansion (see open questions below — do not decide unilaterally).
4. **FastAPI app** with:
   - `GET /machines/assigned` returning `List[MachineDto]` matching the existing Kotlin DTO shape exactly (snake_case keys, all 13 fields populated).
   - JWT bearer-token auth stub (real auth comes in the User-list prompt — for now accept any signed token from a hardcoded dev secret, or a `DEV_BYPASS_TOKEN` env var).
   - Pydantic v2 schemas, SQLAlchemy 2.x ORM, async session.
5. **Unit tests** (pytest + httpx AsyncClient) for the endpoint and the importer.
6. **README** at the backend repo root: how to run locally (uvicorn + Postgres via docker-compose), how to apply migrations, how to seed.

Out of scope for this prompt: users/auth (separate prompt), breakdowns, PM, power consumption, sync queue ingestion. Do not pre-build those.

---

## 3. Known gaps the Excel does NOT cover — RESOLVE BEFORE CODING

The frontend DTO has 13 fields. The Excel only supplies a subset. For each gap, **ask the user how to fill it** (do not invent defaults silently):

| Frontend field | Excel source? | Question to ask |
|---|---|---|
| `id` (UUID or string PK) | partial — `machine_id` is `MCH-0001` | Use `machine_id` as PK directly, or generate UUID and keep `MCH-0001` as `code`? |
| `code` | yes (`machine_id`) | Confirm — note Android mock uses `MACH-XXX`-style; existing UI may need a code-format check. |
| `name` | yes (`machine_name`) | OK to import as-is including typos, or pre-clean (e.g. `Drian pump` → `Drain pump`)? |
| `location` | yes (`floor`) | Confirm `floor` text → `location` 1:1, or normalize casing (`Lower basement` vs `service floor`)? |
| `plantId` | NO | All 214 machines belong to one plant? If so, what's the plant id/name? Or split by floor? |
| `machineType` | NO | Inferred from `machine_name` keyword (e.g. "Compressor" → COMPRESSOR, "AC" → HVAC)? Provide mapping rules, or default everything to OTHER and let the user edit later? |
| `ratedKw` | partial, dirty | Parse units (`508watt` → 0.508, `1.5kw` → 1.5, `150W` → 0.150). When blank, default 0.0 or NULL? DTO is non-nullable Double — keep 0.0? |
| `loadFactor` | NO | Default 0.7? Some other number? |
| `loadFactorSource` | NO | Default `ASSUMED`? |
| `criticality` | NO | Default `C`? Or ask user to assign per machine later? |
| `expectedRunHours` | NO | Default 8.0 (one shift)? Different per floor? |
| `currentStatus` | NO | Default `IDLE` on seed? |
| `updatedAt` | NO | Set to seed timestamp (epoch ms — Kotlin uses `Long`). |

**Quantity > 1 question:** when a row says "Tube light, qty 34nos", do we create **34 separate machine rows** with codes `MCH-0009-01` … `MCH-0009-34`, **one row with a `quantity` column**, or skip these (lights/tubes aren't really "machines" in the maintenance sense)? **Ask the user.**

**`machine_id` uniqueness:** verify all 214 ids are unique in the source. Some rows in the file appear to repeat machine names (e.g. multiple `Band sealer`, `AC indoor unit`) but the `machine_id` should still be unique — confirm by full sheet scan, not just the first 24 rows.

---

## 4. Stack & conventions

- Python 3.11+, FastAPI ≥ 0.110, SQLAlchemy 2.x **async**, Alembic, Pydantic v2, asyncpg, uvicorn, pytest, pytest-asyncio, httpx, ruff + black, mypy strict.
- Repo layout to propose (do not create yet): `backend/` next to `FactoryOps/` (i.e. `D:\Maintenance module\backend\`), with `app/`, `app/api/`, `app/models/`, `app/schemas/`, `app/db/`, `alembic/`, `scripts/`, `tests/`.
- JSON keys snake_case to match `@SerialName` on the Kotlin DTOs. Enum values UPPER_SNAKE_CASE as strings (matches Kotlin enum `.name`).
- Times: epoch milliseconds in API responses (`updatedAt: Long` in Kotlin). Store as `TIMESTAMPTZ` in Postgres, convert at the Pydantic boundary.
- Indian context: no localization in JSON; UI handles formatting. Don't add currency or `dd MMM yyyy` formatting in the API.

---

## 5. Process you must follow

1. **Read** this prompt, the four Kotlin contract files listed in §1, and the Excel file end-to-end (all 215 rows — not just the first 24). Report back:
   - Total distinct `floor` values + count per floor.
   - Rows with `quantity` > 1 (count + list of machine names).
   - Rows with `rated_kw` populated, with raw values, so the user can sanity-check your unit-parsing plan.
   - Any duplicate `machine_id`s.
2. **Ask the §3 questions** as a numbered list. Do not proceed past this step without answers.
3. **Propose** the dependency list, repo layout, and migration strategy. Wait for approval.
4. **Implement** in this order, pausing for verification after each:
   - (a) Project scaffold + docker-compose Postgres + alembic init.
   - (b) `machines` table migration.
   - (c) Excel importer script + dry-run output.
   - (d) `GET /machines/assigned` endpoint + Pydantic schema.
   - (e) Auth stub.
   - (f) Tests + README.
5. After (d), run a curl against the local server and paste the JSON so the user can confirm the shape matches `MachineDto` before moving on.

---

## 6. Out of bounds

- Do not modify any Kotlin file. The Android contract is fixed.
- Do not start the Users module — separate prompt.
- Do not enable real Firebase / FCM / S3 — placeholders only.
- Do not flip `BuildConfig.USE_MOCK_API` in the Android app. The user will do that manually after backend is verified.
- Do not invent fields not in the DTO (no `description`, `manufacturer`, `installed_at` columns surfaced in the API). You may store extras in DB if useful for the importer (e.g. raw `company`, `model_no`, `serial_no`, `quantity`), but keep them out of the response payload until the frontend asks.

---

## 7. Acceptance check

The user will run:
```
curl -H "Authorization: Bearer <dev-token>" http://localhost:8000/machines/assigned | jq '.[0]'
```
and the output must contain exactly these keys with the right types:
```
id (str), code (str), name (str), location (str), plant_id (str),
machine_type (str enum), rated_kw (number), load_factor (number),
load_factor_source (str enum), criticality (str enum),
expected_run_hours (number), current_status (str enum),
updated_at (integer, epoch millis)
```
Any extra key, missing key, or type mismatch fails acceptance.
