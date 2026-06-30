# FactoryOps — Python Backend

FastAPI + SQLAlchemy + SQLite backend for the FactoryOps Phase-1 mobile app
(operator power-consumption logging, breakdown flags, technician inbox) and
the floor-wise utility dashboard.

Pairs with the React Native app at `..\Flutterproj`.

---

## 1. Quick start (Windows / PowerShell)

```powershell
cd "d:\Maintenance module\backend"

# install deps (one-time)
pip install -r requirements.txt

# seed the database from the two Excel files
python -m scripts.seed

# run the server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs` for interactive Swagger.

The first run creates `factoryops.db` (SQLite) in the backend folder.
Re-running `python -m scripts.seed` is safe — it upserts machines/floors/users
and re-imports the entire floor-utility table.

---

## 2. Project layout

```
backend/
├── app/
│   ├── main.py          # FastAPI app factory
│   ├── config.py        # env-driven settings (Pydantic v2)
│   ├── database.py      # SQLAlchemy engine + session
│   ├── auth.py          # JWT login + dependency for protected routes
│   ├── models.py        # ORM models: Plant, Floor, Machine, User, ProductionRun, BreakdownFlag, FloorUtilityReading
│   ├── schemas.py       # Pydantic DTOs (mirror the mobile app contract 1:1)
│   ├── utils.py         # kW/qty parsers, machine-type inference, epoch-ms helpers
│   └── api/
│       ├── auth.py        # POST /auth/login
│       ├── machines.py    # GET  /machines/assigned
│       ├── energy.py      # POST /energy/runs/start | /energy/runs/{id}/stop, GET history
│       ├── breakdowns.py  # POST /breakdowns/flag, GET /breakdowns, ack + resolve
│       └── floors.py      # GET  /floors/, GET /floors/{id}/utility (admin/dashboard)
├── scripts/
│   └── seed.py          # one-shot importer: machine-list.xlsx + Floorwise utility dada.xlsx
├── requirements.txt
├── .env.example
└── factoryops.db        # SQLite, created on first seed
```

---

## 3. Data sources

| Source file                                                       | Table seeded                                  |
|-------------------------------------------------------------------|-----------------------------------------------|
| `..\FactoryOps\machine-list.xlsx`                                 | `plants`, `floors`, `machines`                |
| `..\Floorwise utility dada.xlsx`                                  | `floor_utility_readings` (daily KWH per floor) |

Floor names from the two files are merged into a single canonical set (`Lower
basement`, `Upper basement`, `Service floor`, `Ground floor`, `1st floor`,
`1st floor mezzanine`, `2nd floor`, `2nd floor mezzanine`, `Office`,
`Terrace`, `AC` (sub-meter), `Old lift` (sub-meter)).

Machine fields not present in the Excel are defaulted on seed:

| Field                | Default     |
|----------------------|-------------|
| `load_factor`        | `0.7`       |
| `load_factor_source` | `ASSUMED`   |
| `criticality`        | `C`         |
| `expected_run_hours` | `8.0`       |
| `current_status`     | `IDLE`      |
| `machine_type`       | inferred from name keywords (`compressor`, `pump`, `vrv/ac`, `seal`, …) — else `OTHER` |
| `rated_kw`           | parsed from mixed units: `508watt` → `0.508`, `1.5kw` → `1.5`, `150W` → `0.150`; blank → `0.0` |

Rows where `quantity` is e.g. `34nos` are kept as **one** machine row with a
stored `quantity` column (they are not expanded into 34 separate rows). The
quantity is not surfaced on the mobile DTO.

---

## 4. Seed users

| Username     | Password  | Role       |
|--------------|-----------|------------|
| `operator1`  | `pass123` | OPERATOR   |
| `operator2`  | `pass123` | OPERATOR   |
| `technician1`| `pass123` | TECHNICIAN |

There are no per-user machine assignments seeded, so `GET /machines/assigned`
falls back to **all machines in the plant** for any operator.

---

## 5. Endpoints

All protected routes need `Authorization: Bearer <jwt>` (returned by login).
There is also a `DEV_BYPASS_TOKEN` for quick curl tests — see `.env.example`.

### Mobile-app contract (matches `Flutterproj/src/data/remote/dtos.ts` exactly)

| Method | Path                                       | Notes                                       |
|--------|--------------------------------------------|---------------------------------------------|
| POST   | `/auth/login`                              | username + password → JWT                   |
| GET    | `/machines/assigned`                       | List of `MachineDto`                        |
| POST   | `/energy/runs/start`                       | Idempotent on `client_run_id`               |
| POST   | `/energy/runs/{run_id}/stop`               | Computes `kwh = rated_kw × hours × load_factor` |
| GET    | `/energy/machines/{id}/history?from&to`    | Daily rollup                                |
| POST   | `/breakdowns/flag`                         | Idempotent on `client_flag_id`              |
| GET    | `/breakdowns?plant_id=…&since=…`           | Technician inbox                            |
| POST   | `/breakdowns/{flag_id}/acknowledge`        |                                             |
| POST   | `/breakdowns/{flag_id}/resolve`            |                                             |

### Extra (admin / dashboard — not used by the mobile app yet)

| Method | Path                                      | Notes                                                                |
|--------|-------------------------------------------|----------------------------------------------------------------------|
| GET    | `/floors/`                                | Per-floor summary — machine count, total rated kW, last-30d kWh      |
| GET    | `/floors/{floor_id}/utility?from_date&to_date` | Daily meter reading + daily kWh per floor                       |
| GET    | `/health`                                 | Liveness check                                                       |

---

## 6. Configuration

Copy `.env.example` to `.env` and edit if needed:

```
DATABASE_URL=sqlite:///./factoryops.db
JWT_SECRET=change-me-in-production-please
JWT_ALGORITHM=HS256
JWT_EXPIRES_HOURS=8
DEV_BYPASS_TOKEN=dev-bypass-token
COST_PER_KWH=8.5
```

To switch to PostgreSQL later, set
`DATABASE_URL=postgresql+psycopg://user:pass@host:5432/factoryops` and
`pip install psycopg[binary]`. The SQLAlchemy models are dialect-agnostic.

---

## 7. Mobile-app handoff

See [`CONNECT_MOBILE_APP.md`](./CONNECT_MOBILE_APP.md) for the step-by-step
guide to point the React-Native app at this backend.
