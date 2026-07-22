# Frontend handoff — Utility rates read-only + prefill (2026-07-22)

App: `D:\Maintenance module\FactoryOps\app`. Backend-only change; this is written
guidance for the Kotlin team — no app code was edited from the backend repo.

## What changed on the backend
Utility **prices** (diesel / gas / water / electricity rates) are now
**supervisor-managed** and server-authoritative. A technician can *see* the price
but cannot set it, and the backend recomputes all cost columns itself — any
rate/cost the app POSTs is ignored and overwritten.

## Technician daily-reading forms (Diesel / Gas / Electricity / Water)
1. On opening a form, call
   `GET /utilities/{utility}/prefill?plant=<P>&date=<YYYY-MM-DD>`
   where `utility` = `diesel` | `gas` | `electricity` | `water`. `date` is
   optional (defaults to today). Response:
   ```json
   {
     "plant": "W-202",
     "utility": "water",
     "reading_date": "2026-07-22",
     "source_date": "2026-07-20",        // date of the row the openings came from; null if none
     "rate": 24.0,                        // current supervisor price; may be null until set
     "openings": { "water_meter_opening": 426.86 }
   }
   ```
   - Pre-fill the **opening** meter field(s) from `openings`. The keys are the
     exact field names the POST body uses:
     - diesel → `initial_kwh_reading`, `start_dg_run_hour`
     - gas → `gas_meter_opening`
     - electricity → `energy_meter_opening_kwh`, `energy_meter_opening_kvah`
     - water → `water_meter_opening`
   - Show `rate` as a **read-only** price (a label, not an input). The technician
     must not be able to edit or insert it. `rate` may be `null` until the
     supervisor sets it — show a placeholder / "not set" in that case.
2. The app may still compute cost locally for a live on-screen preview, but the
   stored value is the backend's — do not rely on the app's cost being kept.

## Supervisor "Utility Rates" screen (new)
- Load current prices: `GET /utilities/rates?plant=<P>` → a JSON **array**; take
  the first element (`[0]`). It may be empty `[]` for a plant that has never had
  a rate set — treat as "no prices yet".
  ```json
  [{ "plant":"W-202", "diesel_rate":95.0, "gas_rate":30.0, "water_rate":24.0,
     "electricity_rate":8.5, "set_by":"supervisor1", "set_at":"2026-07-22T09:00:00Z" }]
  ```
- Save: `PUT /utilities/rates` with body
  `{ "plant":"<P>", "diesel_rate":?, "gas_rate":?, "water_rate":?, "electricity_rate":? }`.
  **Partial** — send only the rate(s) being changed; the rest keep their current
  value. Returns the full updated rate row.
- **Authorization:** `PUT` returns **403** for any role other than
  `SUPERVISOR` / `HEAD` / `ADMIN`. Show this screen's entry point only to those
  roles. `GET /utilities/rates` is open to any authenticated user (so the
  technician app can display the read-only price).

## Backward compatibility
Old app builds keep working: any rate/cost they POST is silently overridden and
recomputed server-side. No forced app update is required, but until the app is
updated the rate field will still *look* editable to technicians even though the
value is discarded.
