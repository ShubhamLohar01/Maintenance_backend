# Spare Parts section — design

## Purpose

A new "Spare Parts" section on the Technician and Supervisor home screens: browse
W-202's spare-parts stock (machine → its parts → quantity on hand), and log
usage/restock against it.

## Scope decisions (from brainstorming)

- **W-202 only for now.** `mt_202_spareparts` (113 rows, pre-existing) has no
  A-185 equivalent. A-185 support is a separate future effort once that data exists.
- **Read + write.** Not just a viewer — technicians and supervisors can log usage
  (deduct) and restock (add). Both roles can do both actions.
- **Machine linkage: best-effort match + fallback.** `mt_202_spareparts.machine_name`
  is free text (e.g. "kruger machine"), not a foreign key to `mt_asset_list`. A
  case-insensitive `ILIKE` match against W-202 asset names resolves real
  `asset_id`/`asset_name` pairs where they exist (6 of 19 machines matched in testing:
  kruger machine, lift, nitrogen plant, packing machine, printing machine, vacuum
  machine). The other 13 (air compressor, band sealing machine, DC motor, FFS machine,
  humidity chamber machine, label applicator, old lift, oven machine, RO plant, selmi
  machine, shrink machine, tree roaster, TTO printer) have no match — the app just
  shows the plain `machine_name` for those, no error, no blocking.
- **Audit log: lean.** Every use/restock is logged (who/when/how much) for future
  traceability, but no dedicated history screen ships in this build.
- **Browse UX:** machine list → tap in → parts for that machine, with Use/Restock
  inline on the same detail screen (no separate action screen).

## Backend

### New table (the existing `mt_202_spareparts` is read-only from this app's POV — untouched)

```sql
CREATE TABLE IF NOT EXISTS mt_202_spareparts_log (
    id                SERIAL PRIMARY KEY,
    spare_part_id     INTEGER NOT NULL REFERENCES mt_202_spareparts(id),
    machine_name      VARCHAR(255),          -- snapshot at action time
    part_name         VARCHAR(255),          -- snapshot at action time
    action            VARCHAR(16) NOT NULL,  -- 'USE' | 'RESTOCK'
    quantity          INTEGER NOT NULL,      -- always positive; sign implied by action
    note              TEXT,
    performed_by       VARCHAR(64),
    performed_by_name VARCHAR(128),
    performed_at      TIMESTAMP DEFAULT now()
);
```

### Model

`MtSparePart` (RdsBase, maps existing `mt_202_spareparts`): `id`, `machine_name`
(nullable str), `parts_name` (JSONB `{name, unit}`), `quantity` (int).
`MtSparePartLog` (RdsBase, maps new `mt_202_spareparts_log`) per the schema above.

### Endpoints (`prefix="/spare-parts"`, Bearer-JWT auth, any authenticated user)

- `GET /spare-parts` → everything in one response (no pagination — 113 rows):
  ```json
  { "machines": [
      { "machine_name": "kruger machine",
        "matched_assets": [{"asset_id": "...", "asset_name": "Kruger Machine"}],
        "parts": [{"id": 3, "part_name": "pressure shaft", "unit": "nos", "quantity": 2}] },
      ...
  ]}
  ```
  `matched_assets` computed once per request (one `ILIKE` pass per distinct
  `machine_name`, cheap at this scale); `[]` when nothing matches.
- `POST /spare-parts/{id}/use` — body `{quantity: int, note?: str}`. Atomic
  conditional decrement (`quantity >= requested` or 400 "not enough stock: N on
  hand"). Logs a `USE` row. Returns the updated part.
- `POST /spare-parts/{id}/restock` — body `{quantity: int, note?: str}`.
  Increments; `quantity` in the body must be > 0 (400 otherwise). Logs a
  `RESTOCK` row. Returns the updated part.

### Validation

- `quantity` in both POST bodies must be a positive integer (400 otherwise).
- `use` additionally 400s if `quantity > current quantity on hand`.
- Unknown `{id}` → 404.

## Android app

Mirrors the existing Utilities/Daily-Reading feature layering:

- `data/remote/api/SparePartsApi.kt` — Retrofit: `GET spare-parts`,
  `POST spare-parts/{id}/use`, `POST spare-parts/{id}/restock`.
- `data/remote/dto/SparePartDtos.kt` — response/request DTOs.
- `domain/model/spareparts/` — `SparePartsMachine`, `SparePart` domain models.
- `domain/repository/SparePartsRepository.kt` +
  `data/repository/SparePartsRepositoryImpl.kt` — same `Result<T>` wrapper
  pattern used everywhere else in the app.
- `presentation/spareparts/`:
  - `SparePartsMachineListScreen.kt` + ViewModel — tile's landing screen: one
    card per machine (`machine_name`, part count, matched asset name(s) as a
    subtitle when present).
  - `SparePartsDetailScreen.kt` + ViewModel — parts + quantities for one
    machine; each part has inline "Use" / "Restock" buttons opening a small
    quantity dialog.
- `navigation/Screen.kt` + `navigation/NavGraph.kt` — two new routes.
- `presentation/dashboard/DashboardTile.kt` — new "Spare Parts" tile added to
  both the `TECHNICIAN` and `SUPERVISOR`/`HEAD` tile lists, same destination,
  full access for both.

## Testing

- Backend: pytest, TDD — matching table/quantity, ILIKE-matching against
  seeded `MtAsset` rows, positive-quantity validation, insufficient-stock 400,
  log rows written on both actions, full suite re-run for regressions.
- Android: ViewModel unit tests (mirroring `DailyReadingViewModelTest`) for
  load/use/restock success + error paths; Gradle unit test run to confirm green.
