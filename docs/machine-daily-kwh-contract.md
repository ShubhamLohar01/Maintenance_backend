# Contract: per-asset daily kWh upsert

Per-asset daily kWh reading, stored in `mt_machine_daily_kwh`, keyed by the
**`mt_asset_list` asset_id** (the IDs the app shows via `GET /mt-machines`).

## Endpoint

```
POST /mt-machines/{asset_id}/daily-kwh      (auth required)
```

Idempotent upsert — last-write-wins on `(machine_id, reading_date)`. The
`machine_id` column stores the asset_id.

### Request body (snake_case)

```json
{
  "machine_id": "A185-0001",
  "reading_date": "2026-06-19",
  "daily_kwh": 12.5,
  "source": "MANUAL"
}
```

- `machine_id` — the asset_id from `GET /mt-machines`. Must exist in
  `mt_asset_list` (else 404) and match the `{asset_id}` in the path (else 400).
- `reading_date` — ISO `YYYY-MM-DD`, device-local day.
- `daily_kwh` — the day's reading/total.
- `source` — `CALCULATED` | `MEASURED` | `MANUAL` (default `CALCULATED`).
- `building` / `floor` — **do not send**; the server fills them authoritatively
  from the asset register (`mt_asset_list.building` / `.sub_location`). If sent,
  they're ignored.

### Responses

- `200` → the saved row (`MachineDailyKwhDto`): `machine_id`, `reading_date`
  (ISO), `building`, `floor`, `daily_kwh`, `source`, `updated_at` (epoch ms).
- `400` — path/body id mismatch, or bad `reading_date`.
- `401` — missing/invalid token.
- `404` — `asset_id` not in `mt_asset_list`.

## Storage — `mt_machine_daily_kwh`

Unchanged table. The upsert is dialect-agnostic (get-or-create), so it works on
both SQLite (the app's local DB) and Postgres. `building`/`floor` are snapshotted
from the asset at write time.
