from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, DateTime, Text, Date, Numeric, UniqueConstraint, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator, JSON
from .database import LocalBase, RdsBase


class PortableJSONB(TypeDecorator):
    """JSONB on Postgres (real RDS); plain JSON on any other dialect (the
    in-memory SQLite test harness — see tests/conftest.py). Postgres-native
    JSONB doesn't compile on SQLite at all, which is why other JSONB-backed
    tables in this file are excluded from that harness; new tables use this
    instead so they stay testable."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Plant(LocalBase):
    __tablename__ = "plants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class Floor(LocalBase):
    __tablename__ = "floors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(64), ForeignKey("plants.id"))
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Machine(LocalBase):
    __tablename__ = "machines"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255))
    plant_id: Mapped[str] = mapped_column(String(64), ForeignKey("plants.id"))
    floor_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("floors.id"), nullable=True)
    rated_kw: Mapped[float] = mapped_column(Float, default=0.0)
    load_factor: Mapped[float] = mapped_column(Float, default=0.7)
    load_factor_source: Mapped[str] = mapped_column(String(32), default="ASSUMED")
    criticality: Mapped[str] = mapped_column(String(8), default="C")
    expected_run_hours: Mapped[float] = mapped_column(Float, default=8.0)
    current_status: Mapped[str] = mapped_column(String(16), default="IDLE")
    machine_type: Mapped[str] = mapped_column(String(32), default="OTHER")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    building: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sub_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serial_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    rated_amps: Mapped[str | None] = mapped_column(String(64), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(LocalBase):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    plant_id: Mapped[str] = mapped_column(String(64), ForeignKey("plants.id"))


class UserMachineAssignment(LocalBase):
    __tablename__ = "user_machine_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"))
    machine_id: Mapped[str] = mapped_column(String(64), ForeignKey("machines.id"))


# NOTE: the old `mt_machine_runs` table / ProductionRun model was retired on
# 2026-06-25 — production runs now live directly in `mt_machine_daily_kwh`
# (one row per run; see MachineDailyKwh). The table can be dropped in RDS.

# NOTE: the old `breakdown_flags` table / BreakdownFlag model was retired on
# 2026-06-23 — operator breakdown flags now live in `mt_breakdown_records`
# (BreakdownRecord, source='OPERATOR_FLAG'). The table can be dropped in RDS.


class MtAsset(RdsBase):
    """Factory asset register for buildings W-202 and A-185.

    Loaded from 'Asset Full revised A185 & W202.xlsx' (both sheets, unioned).
    Replaces the old `mt_machine_list` table. Source of truth for the asset list.
    """
    __tablename__ = "mt_asset_list"

    id:                  Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id:            Mapped[str | None]     = mapped_column(String(32), unique=True, nullable=True)
    building:            Mapped[str]            = mapped_column(String(16), index=True)
    asset_name:          Mapped[str]            = mapped_column(String(255))
    category:            Mapped[str | None]     = mapped_column(String(64), index=True, nullable=True)
    sub_location:        Mapped[str | None]     = mapped_column(String(255), nullable=True)
    quantity:            Mapped[int | None]     = mapped_column(Integer, nullable=True)
    revised_count_2026:  Mapped[int | None]     = mapped_column(Integer, nullable=True)
    model_no:            Mapped[str | None]     = mapped_column(String(255), nullable=True)
    serial_no:           Mapped[str | None]     = mapped_column(String(255), nullable=True)
    power_load:          Mapped[str | None]     = mapped_column(String(128), nullable=True)
    purchase_date:       Mapped[date | None]    = mapped_column(Date, nullable=True)
    purchase_value:      Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    condition:           Mapped[str | None]     = mapped_column(String(32), nullable=True)
    assigned_to:         Mapped[str | None]     = mapped_column(String(128), nullable=True)
    warranty_amc_expiry: Mapped[str | None]     = mapped_column(String(64), nullable=True)
    remarks:             Mapped[str | None]     = mapped_column(Text, nullable=True)

    # --- Daily consumption schedule (only "Electric Asset" rows use these) ---
    # A recurring daily recording window in factory-local (IST) minutes-of-day.
    # These assets aren't operator-runnable, so a supervisor schedules them and the
    # backend generates one mt_machine_daily_kwh row per elapsed day (source='SCHEDULE').
    # SUPERVISOR writes (any plant); HEAD is read-only. See app/api/asset_schedules.py.
    schedule_start_min:      Mapped[int | None]      = mapped_column(Integer, nullable=True)   # 0..1439, e.g. 600 = 10:00
    schedule_end_min:        Mapped[int | None]      = mapped_column(Integer, nullable=True)   # must be > start (same-day window)
    schedule_active:         Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Comma-separated 3-letter weekday codes (SUN..SAT), e.g. "MON,WED,FRI"; NULL/empty = every
    # day (keeps old rows firing daily). Plain TEXT (not JSON/JSONB) so it stays portable to
    # the SQLite test harness — see app/api/asset_schedules.py _encode_days/_decode_days.
    schedule_days:           Mapped[str | None]      = mapped_column(String(32), nullable=True)
    schedule_is_24h:         Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    schedule_last_generated: Mapped[date | None]     = mapped_column(Date, nullable=True)      # backfill high-water mark
    schedule_updated_by:     Mapped[str | None]      = mapped_column(String(128), nullable=True)
    schedule_updated_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FloorUtilityReading(LocalBase):
    """Daily KWH meter reading per floor (from 'Floorwise utility dada.xlsx')."""
    __tablename__ = "floor_utility_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    floor_id: Mapped[str] = mapped_column(String(64), ForeignKey("floors.id"), index=True)
    reading_date: Mapped[datetime] = mapped_column(Date, index=True)
    meter_reading: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)


class MachineDailyKwh(RdsBase):
    """One row per (machine, calendar date) — the per-machine daily energy record.

    RUN rows (source='RUN') aggregate every start/stop/pause/resume that machine did
    that day: there is ONE row per (machine_id, reading_date), and `daily_kwh` is the
    SUM of that day's run segments (see MtMachineRunSegment). started_at is the day's
    earliest segment start, ended_at its latest segment end, and status is 'RUNNING'
    while any segment is open, else 'COMPLETE'. (Superseded the 2026-06-25 one-row-per-run
    layout, which duplicated a machine's daily row on every pause/resume.) SCHEDULE rows
    (source='SCHEDULE', from asset_schedules) are unchanged: one already-COMPLETE row per
    day for non-runnable electric assets, keyed by their own client_run_id.

    A partial unique index UNIQUE(machine_id, reading_date) WHERE source='RUN' (created in
    the migration, Postgres-only) enforces the one-RUN-row-per-day invariant. `daily_kwh`
    is computed backend-side from the asset's rated power (mt_asset_list.power_load × run
    hours × power_factor). building/floor are a denormalized snapshot from the asset
    register. Distinct from the floor meter readings (FloorUtilityReading /
    mt_floor_utility_readings), which are *real* per-floor meter readings."""
    __tablename__ = "mt_machine_daily_kwh"

    id:            Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:    Mapped[str]             = mapped_column(String(64), index=True)  # = mt_asset_list.asset_id
    reading_date:  Mapped[date]            = mapped_column(Date, index=True)        # = started_at calendar day
    building:      Mapped[str]             = mapped_column(String(16), default="W-202", server_default="W-202")
    floor:         Mapped[str | None]      = mapped_column(String(64), nullable=True)
    asset_name:    Mapped[str | None]      = mapped_column(String(255), nullable=True)  # denormalized snapshot from mt_asset_list
    # --- run / lifecycle (folded in from the retired mt_machine_runs) ---
    client_run_id: Mapped[str | None]      = mapped_column(String(64), unique=True, index=True, nullable=True)  # idempotency key (SCHEDULE rows: 'sched-{asset}-{date}'; RUN rows: NULL, see MtMachineRunSegment). UNIQUE so concurrent sweeps can never double-insert the same day.
    operator_id:   Mapped[str | None]      = mapped_column(String(64), index=True, nullable=True)  # = str(mt_users.id)
    operator_name: Mapped[str | None]      = mapped_column(String(128), nullable=True)             # denormalized snapshot
    started_at:    Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    ended_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # NULL while RUNNING
    status:        Mapped[str]             = mapped_column(String(16), default="RUNNING", server_default="RUNNING")  # RUNNING | COMPLETE
    daily_kwh:     Mapped[Decimal | None]  = mapped_column(Numeric(14, 4), nullable=True)           # NULL while RUNNING
    source:        Mapped[str]             = mapped_column(String(16), default="RUN", server_default="RUN")
    created_at:    Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
    updated_at:    Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


class MtMachineRunSegment(RdsBase):
    """One production run segment — a single START→STOP against a daily kWh row.

    A machine started/stopped/paused/resumed several times on the same calendar day
    produces ONE MachineDailyKwh row (keyed on machine + date) and MANY of these
    segments — one per START. The daily row's daily_kwh is the SUM of its segments'
    kwh, its started_at the earliest segment start, its ended_at the latest segment end.
    `id` is the run_id handed back to the app; POST /energy/runs/{run_id}/stop closes THIS
    segment and folds its kWh into the daily row. Idempotent on client_run_id — an
    offline re-sync replaying a start must not double-open, replaying a stop must not
    double-add. A machine is 'active' while any of its segments is still open (ended_at
    IS NULL). SCHEDULE daily rows have no segments."""
    __tablename__ = "mt_machine_run_segment"

    id:            Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    daily_id:      Mapped[int]             = mapped_column(Integer, ForeignKey("mt_machine_daily_kwh.id"), index=True)
    machine_id:    Mapped[str]             = mapped_column(String(64), index=True)  # = mt_asset_list.asset_id (denormalized for the active query)
    client_run_id: Mapped[str]             = mapped_column(String(64), unique=True, index=True)  # idempotency key from the app
    operator_id:   Mapped[str | None]      = mapped_column(String(64), index=True, nullable=True)  # = str(mt_users.id)
    operator_name: Mapped[str | None]      = mapped_column(String(128), nullable=True)             # denormalized snapshot
    started_at:    Mapped[datetime]        = mapped_column(DateTime, index=True)
    ended_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # NULL while open
    status:        Mapped[str]             = mapped_column(String(16), default="RUNNING", server_default="RUNNING")  # RUNNING | COMPLETE
    kwh:           Mapped[Decimal | None]  = mapped_column(Numeric(14, 4), nullable=True)           # this segment's kWh (NULL while open)
    source:        Mapped[str]             = mapped_column(String(16), default="RUN", server_default="RUN")
    created_at:    Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
    updated_at:    Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


class MtFloorUtilityReading(RdsBase):
    """Per-floor daily energy reading (RDS, pgAdmin-visible). Each row pairs the
    technician's ACTUAL physical meter reading (`meter_reading`) with the
    SYSTEM-generated reading (`daily_kwh` — the day's total run kWh on that floor,
    summed from mt_machine_daily_kwh). Filled via the technician's "Daily Reading"
    screen (GET /floor-readings/system + POST /floor-readings).

    NOT the same as the SQLite `FloorUtilityReading` (floor_utility_readings),
    which is the legacy dev table. `floor` here = mt_asset_list.sub_location (so it
    aligns with mt_machine_daily_kwh.floor for the system total)."""
    __tablename__ = "mt_floor_utility_readings"

    id:            Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    building:      Mapped[str]            = mapped_column(String(16), default="W-202", server_default="W-202")
    floor:         Mapped[str]            = mapped_column(String(64), index=True)
    reading_date:  Mapped[date]           = mapped_column(Date, index=True)
    meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)  # actual physical meter
    daily_kwh:     Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)  # system-generated reading

    __table_args__ = (
        UniqueConstraint("building", "floor", "reading_date", name="uq_mt_floor_utility"),
    )


class MtUser(RdsBase):
    """Maintenance-app users (operators / technicians / heads). Lives in RDS so
    they're managed in pgAdmin. No password column yet — all users share a fixed
    password for now (handled in auth)."""
    __tablename__ = "mt_users"

    id:         Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    emp_id:     Mapped[str | None]      = mapped_column(String(20), nullable=True)
    name:       Mapped[str]             = mapped_column(String(255))
    location:   Mapped[str | None]      = mapped_column(String(100), nullable=True)
    contact_no: Mapped[str | None]      = mapped_column(String(15), nullable=True)
    email_id:   Mapped[str | None]      = mapped_column(String(255), nullable=True)
    role:       Mapped[str | None]      = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    username:   Mapped[str]             = mapped_column(String, unique=True, index=True)

    @property
    def plant_id(self) -> str:
        return (self.location or "UNKNOWN").strip()

    @property
    def norm_role(self) -> str:
        """'operator ' -> 'OPERATOR', 'Technician' -> 'TECHNICIAN', 'Head' -> 'HEAD'."""
        return (self.role or "").strip().upper() or "OPERATOR"


class PreventiveMaintenanceDoc(RdsBase):
    """PM checklist submissions, stored in the user's existing
    `doc_preventive_maintenance` table — WITHOUT changing its schema. The full
    submission (header fields + items[]) goes into the existing `rows` JSONB
    column; the existing scalar columns (month/checked_by/verified_by/created_by)
    are populated for compatibility."""
    __tablename__ = "doc_preventive_maintenance"

    id:          Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    month:       Mapped[str | None]     = mapped_column(String(7), nullable=True)
    checked_by:  Mapped[str | None]     = mapped_column(String(128), nullable=True)
    verified_by: Mapped[str | None]     = mapped_column(String(128), nullable=True)
    rows:        Mapped[dict]           = mapped_column(JSONB, nullable=False)
    warehouse:   Mapped[str | None]     = mapped_column(String(16), nullable=True)
    created_by:  Mapped[str | None]     = mapped_column(String(128), nullable=True)
    created_at:  Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)


class MtPmChecklistLink(RdsBase):
    """Maps a PM asset to its row in a controlled checklist form (50a/50b), so a
    QC-closed PM work order can flip that row's cells in the month/quarter document.
    One row per (asset_id, form_type) — an asset can appear on both the monthly and
    quarterly form. Seeded best-effort from the asset<->checklist fuzzy match
    (high-confidence only); `sr_no` pins WHICH form row when equipment repeats."""
    __tablename__ = "pm_checklist_link"

    id:        Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id:  Mapped[str]        = mapped_column(String(32), index=True)          # = mt_asset_list.asset_id
    form_type: Mapped[str]        = mapped_column(String(16))                      # MONTHLY | QUARTERLY
    section:   Mapped[str]        = mapped_column(String(255))
    sr_no:     Mapped[int | None] = mapped_column(Integer, nullable=True)          # the form row this asset fills
    equipment: Mapped[str]        = mapped_column(String(255))                     # checklist equipment name

    __table_args__ = (
        UniqueConstraint("asset_id", "form_type", name="uq_pm_link_asset_form"),
    )


class MachineTransfer(RdsBase):
    """One machine-transfer record (between warehouses) with an optional proof
    photo stored in S3 (`proof_photo_url`)."""
    __tablename__ = "mt_machine_transfer"

    id:                Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    transfer_date:     Mapped[date | None]    = mapped_column(Date, nullable=True)
    from_warehouse:    Mapped[str]            = mapped_column(String(32), index=True)
    to_warehouse:      Mapped[str]            = mapped_column(String(32), index=True)
    machine_name:      Mapped[str]            = mapped_column(String(255))
    machine_code:      Mapped[str | None]     = mapped_column(String(128), nullable=True)
    machine_id:        Mapped[str | None]     = mapped_column(String(64), index=True, nullable=True)  # = mt_asset_list.asset_id when picked from the register
    condition:         Mapped[str | None]     = mapped_column(String(64), nullable=True)
    reason:            Mapped[str | None]     = mapped_column(Text, nullable=True)
    authorised_person: Mapped[str | None]     = mapped_column(String(255), nullable=True)
    remarks:           Mapped[str | None]     = mapped_column(Text, nullable=True)
    proof_photo_url:   Mapped[str | None]     = mapped_column(Text, nullable=True)
    # Receiving-warehouse acknowledgement: PENDING on create -> APPROVED once the
    # destination warehouse (technician of that plant, or any supervisor) confirms receipt.
    status:            Mapped[str]             = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    acknowledged_by:   Mapped[str | None]      = mapped_column(String(128), nullable=True)
    acknowledged_at:   Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by:        Mapped[str | None]     = mapped_column(String(128), nullable=True)
    created_at:        Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)


class BreakdownRecord(RdsBase):
    """One live breakdown event: operator raises -> technician acknowledges &
    repairs -> QC approves/rejects. People are stored as names (resolved from
    mt_users at write time); the acknowledging technician also gets `technician_id`
    (mt_users.id) so GET /breakdowns/open can match "my active tickets" by id across
    devices, not just by name. The machine is usable again only when status=CLOSED."""
    __tablename__ = "mt_breakdown_records"

    id:                     Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:             Mapped[str | None]      = mapped_column(String(64), index=True, nullable=True)   # = mt_asset_list.asset_id
    machine_name:           Mapped[str | None]      = mapped_column(String(255), nullable=True)
    operator_raise_person:  Mapped[str | None]      = mapped_column(String(128), nullable=True)
    start_time:             Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description:            Mapped[str | None]      = mapped_column(Text, nullable=True)
    severity:               Mapped[str | None]      = mapped_column(String(16), nullable=True)               # CRITICAL|MAJOR|MINOR
    before_photo_url:       Mapped[str | None]      = mapped_column(Text, nullable=True)
    # OPEN | ACKNOWLEDGED | PENDING_QC | CLOSED | REOPENED (machine usable only when CLOSED)
    status:                 Mapped[str | None]      = mapped_column(String(16), index=True, nullable=True)
    technician:             Mapped[str | None]      = mapped_column(String(128), nullable=True)
    technician_id:          Mapped[str | None]      = mapped_column(String(64), nullable=True)                 # = mt_users.id (acknowledger); added via manual ALTER TABLE — legacy rows NULL, name-only
    ackn_at:                Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    work_done_des:          Mapped[str | None]      = mapped_column(Text, nullable=True)
    photo_url:              Mapped[str | None]      = mapped_column(Text, nullable=True)
    qc_checked_by:          Mapped[str | None]      = mapped_column(String(128), nullable=True)
    qc_status:              Mapped[str | None]      = mapped_column(String(16), nullable=True)               # PENDING|APPROVED|REJECTED
    qc_reject_reason:       Mapped[str | None]      = mapped_column(Text, nullable=True)
    end_time:               Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # set when QC approves
    # Lifecycle transition timestamps surfaced (as epoch ms) on GET /breakdowns/open
    # so the app can time its reminder escalations. Nullable until each step happens.
    # (acknowledged_at is the existing `ackn_at`.) Added to RDS via manual ALTER TABLE.
    resolved_at:            Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # technician finished the repair (work-done)
    qc_acknowledged_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # QC picked up the awaiting-QC ticket
    qc_decided_at:          Mapped[datetime | None] = mapped_column(DateTime, nullable=True)                 # QC approved or disapproved
    created_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
    updated_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


class BreakdownDoc(RdsBase):
    """One row of a submitted CFPLA.C4.F.06 breakdown-maintenance sheet. Moved out
    of mt_breakdown_records (which is now the live-workflow table only)."""
    __tablename__ = "mt_doc_breakdown"

    id:                      Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_no:                  Mapped[str]          = mapped_column(String(32), nullable=False, default="CFPLA.C4.F.06")
    sr_no:                   Mapped[int | None]   = mapped_column(Integer, nullable=True)
    record_date:             Mapped[date | None]  = mapped_column(Date, nullable=True)
    location:                Mapped[str | None]   = mapped_column(String(128), nullable=True)
    machine_name:            Mapped[str | None]   = mapped_column(String(128), nullable=True)
    equipment_model_no:      Mapped[str | None]   = mapped_column(String(128), nullable=True)
    problem_in_brief:        Mapped[str | None]   = mapped_column(Text, nullable=True)
    type_of_maintenance:     Mapped[str | None]   = mapped_column(String(32), nullable=True)
    part_of_machine:         Mapped[str | None]   = mapped_column(String(128), nullable=True)
    temporary_reason:        Mapped[str | None]   = mapped_column(Text, nullable=True)
    duration_start:          Mapped[str | None]   = mapped_column(String(32), nullable=True)
    duration_end:            Mapped[str | None]   = mapped_column(String(32), nullable=True)
    machine_operator_sign:   Mapped[str | None]   = mapped_column(String(128), nullable=True)
    maintenance_person_sign: Mapped[str | None]   = mapped_column(String(128), nullable=True)
    qc_clearance_sign:       Mapped[str | None]   = mapped_column(String(128), nullable=True)
    verified_by:             Mapped[str | None]   = mapped_column(String(128), nullable=True)
    created_by:              Mapped[str | None]   = mapped_column(String(128), nullable=True)
    created_at:              Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)


class MtDeviceToken(RdsBase):
    """One registered device push token (FCM), used by the P2 push fan-out. Upserted
    on `token` (unique) so a device that re-registers updates in place; a single user
    may have several devices. `user_id` = str(mt_users.id). Nothing is sent while
    settings.fcm_enabled is false — this table just accumulates tokens meanwhile."""
    __tablename__ = "mt_device_tokens"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:    Mapped[str]      = mapped_column(String(64), index=True)                 # = str(mt_users.id)
    token:      Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    platform:   Mapped[str]      = mapped_column(String(16), default="android", server_default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Preventive Maintenance (PM) — server-backed plans + work orders (v1).
#
# A SUPERVISOR builds a PM PLAN (a checklist bound to ONE asset + a recurring
# schedule + an assigned technician). The generator turns a due plan into a WORK
# ORDER whose task logs are a snapshot of the plan's checklist; the technician
# executes it and QC signs off. Ids are generated OFFLINE by the app
# ('plan-…', 'wo-…') and upserted idempotently on their id, so a re-sync never
# duplicates.
#
# These two tables use readable TIMESTAMP columns (viewable in pgAdmin):
#   * Every wall-clock field is a naive-UTC DateTime (timestamp without time zone);
#     the API converts to/from epoch-ms at the boundary, so the app still speaks its
#     `Long` milliseconds while the DB stays human-readable. NOTE: stored times are
#     UTC (e.g. IST 16:00 shows as 10:30).
#   * The checklist steps (`task_logs`) and `spares` live as JSONB ON the work
#     order — there is NO separate mt_pm_wo_task_log table.
# See app/api/pm_plans.py + app/api/pm_work_orders.py.
# ---------------------------------------------------------------------------


class MtPmPlan(RdsBase):
    """A PM plan: checklist (`items` JSONB) + one machine + a TIME/USAGE schedule.
    `machine_name` is a snapshot of the asset name (assets can be renamed) and also
    serves as the plan's display name. Soft-deleted via is_active=false (a DELETE
    stops future work-order generation but keeps history). All *_at fields are
    naive-UTC DateTime, surfaced as epoch-ms on the wire."""
    __tablename__ = "mt_pm_plan"

    id:                     Mapped[str]             = mapped_column(String(64), primary_key=True)    # server-generated 'PLANAA001' (legacy rows: 'plan-<uuid>')
    client_ref:             Mapped[str | None]      = mapped_column(String(64), nullable=True, unique=True, index=True)  # app's local uuid; idempotency key for offline re-sync
    machine_id:             Mapped[str]             = mapped_column(String(64), index=True)          # = mt_asset_list.asset_id
    machine_name:           Mapped[str]             = mapped_column(String(255))                     # snapshot of asset_name / plan name
    description:            Mapped[str]             = mapped_column(Text, default="", server_default="")
    items:                  Mapped[list]            = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    trigger_type:           Mapped[str]             = mapped_column(String(8), default="TIME", server_default="TIME")
    trigger_interval:       Mapped[int]             = mapped_column(Integer, nullable=False)         # days (TIME) | running-hours (USAGE)
    next_due_at:            Mapped[datetime | None] = mapped_column(DateTime, nullable=True)          # UTC; recomputed by the generator
    last_completed_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)          # UTC; set when a WO is QC-closed
    assigned_technician_id: Mapped[str]             = mapped_column(String(64), index=True)          # = mt_users.id
    assigned_technician_name: Mapped[str | None]    = mapped_column(String(128), nullable=True)      # snapshot of mt_users.name
    is_active:              Mapped[bool]            = mapped_column(Boolean, default=True, server_default="true")
    created_by:             Mapped[str | None]      = mapped_column(String(128), nullable=True)
    created_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())   # UTC
    updated_at:             Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())   # UTC

    __table_args__ = (
        CheckConstraint("trigger_type IN ('TIME','USAGE')", name="ck_pm_plan_trigger"),
        Index("ix_pm_plan_due", "is_active", "next_due_at"),
    )


class MtPmWorkOrder(RdsBase):
    """One generated execution instance of a plan. Walks the status machine
    NOTIFIED → ACKNOWLEDGED → IN_PROGRESS → SUBMITTED → (supervisor approve) →
    PENDING_QC → (QC approve) → CLOSED (or bounced back on a reject/disapprove).
    The per-step results (`task_logs`), spare parts (`spares`), and QC sign-off blob
    (`qc_checklist`) are all JSONB on this row. All *_at fields are naive-UTC DateTime,
    surfaced as epoch-ms on the wire."""
    __tablename__ = "mt_pm_work_order"

    id:                          Mapped[str]             = mapped_column(String(64), primary_key=True)   # 'wo-<plan>-<ts>'
    plan_id:                     Mapped[str]             = mapped_column(String(64), index=True)
    machine_id:                  Mapped[str]             = mapped_column(String(64), index=True)          # = mt_asset_list.asset_id
    machine_name:                Mapped[str]             = mapped_column(String(255))                     # snapshot
    template_name:               Mapped[str]             = mapped_column(String(255))                     # plan/checklist name snapshot
    estimated_duration_minutes:  Mapped[int]             = mapped_column(Integer, default=0, server_default="0")
    scheduled_date:              Mapped[datetime | None] = mapped_column(DateTime, nullable=True)          # UTC
    generated_at:                Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())  # UTC
    status:                      Mapped[str]             = mapped_column(String(24), default="NOTIFIED", server_default="NOTIFIED", index=True)
    assigned_technician_id:      Mapped[str]             = mapped_column(String(64), index=True)
    assigned_technician_name:    Mapped[str | None]      = mapped_column(String(128), nullable=True)
    acknowledged_at:             Mapped[datetime | None] = mapped_column(DateTime, nullable=True)          # UTC
    started_at:                  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at:                Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    final_notes:                 Mapped[str | None]      = mapped_column(Text, nullable=True)
    overall_result:              Mapped[str | None]      = mapped_column(String(8), nullable=True)   # machine-level PASS/FAIL (set at submit)
    checklist_doc_id:            Mapped[int | None]      = mapped_column(Integer, nullable=True)      # doc_preventive_maintenance.id this PM fed (set at QC close)
    supervisor_approved_by:      Mapped[str | None]      = mapped_column(String(128), nullable=True)
    supervisor_approved_by_name: Mapped[str | None]      = mapped_column(String(128), nullable=True)
    supervisor_approved_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    supervisor_rejected_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    supervisor_rejection_notes:  Mapped[str | None]      = mapped_column(Text, nullable=True)
    qc_acknowledged_by:          Mapped[str | None]      = mapped_column(String(128), nullable=True)
    qc_acknowledged_by_name:     Mapped[str | None]      = mapped_column(String(128), nullable=True)
    qc_acknowledged_at:          Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qc_checklist:                Mapped[dict | None]     = mapped_column(JSONB, nullable=True)            # QC sign-off blob (incl. notes / after-photo url)
    closed_at:                   Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    task_logs:                   Mapped[list]            = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # per-step results
    spares:                      Mapped[list]            = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # spare parts used
    created_at:                  Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())  # UTC
    updated_at:                  Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())  # UTC

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','NOTIFIED','ACKNOWLEDGED','IN_PROGRESS','SUBMITTED',"
            "'SUPERVISOR_APPROVED','PENDING_QC','QC_APPROVED','CLOSED','OVERDUE','CANCELLED')",
            name="ck_pm_wo_status",
        ),
    )


# ============================================================================
# Utility Consumption (Diesel / Gas / Electricity / Water) — one row per
# (plant, reading_date). Sourced from the "Utility Consumption 2026-2027" sheet
# (A-185 + W-202 blocks folded into `plant`). The derived columns mirror the
# sheet's per-column formulas but are PLAIN (not GENERATED): the Android app
# computes them client-side and sends them; the backend stores what it receives
# (see app/api/utilities.py). All money columns are in rupees.
# ============================================================================

class MtUtilityDiesel(RdsBase):
    """DG-set daily diesel + energy log. Formulas (app-computed):
    total_consumption = final_kwh - initial_kwh; total_run_hour = stop - start;
    total_diesel_l = diesel_l_per_hour * total_run_hour;
    total_fuel_cost = total_diesel_l * diesel_rate."""
    __tablename__ = "mt_utility_diesel"

    id:                  Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant:               Mapped[str]              = mapped_column(String(16), index=True)   # 'A-185' | 'W-202'
    reading_date:        Mapped[date]             = mapped_column(Date, index=True)
    initial_kwh_reading: Mapped[Decimal | None]   = mapped_column(Numeric(14, 2), nullable=True)
    final_kwh_reading:   Mapped[Decimal | None]   = mapped_column(Numeric(14, 2), nullable=True)
    start_dg_run_hour:   Mapped[Decimal | None]   = mapped_column(Numeric(10, 2), nullable=True)
    stop_dg_run_hour:    Mapped[Decimal | None]   = mapped_column(Numeric(10, 2), nullable=True)
    diesel_l_per_hour:   Mapped[Decimal | None]   = mapped_column(Numeric(10, 3), nullable=True, server_default="37.5")
    diesel_rate:         Mapped[Decimal | None]   = mapped_column(Numeric(10, 2), nullable=True, server_default="95")
    diesel_received_l:   Mapped[Decimal | None]   = mapped_column(Numeric(12, 2), nullable=True)
    remark:              Mapped[str | None]       = mapped_column(Text, nullable=True)
    total_consumption:   Mapped[Decimal | None]   = mapped_column(Numeric(14, 2), nullable=True)   # app-computed
    total_run_hour:      Mapped[Decimal | None]   = mapped_column(Numeric(10, 2), nullable=True)   # app-computed
    total_diesel_l:      Mapped[Decimal | None]   = mapped_column(Numeric(14, 3), nullable=True)   # app-computed
    total_fuel_cost:     Mapped[Decimal | None]   = mapped_column(Numeric(16, 2), nullable=True)   # app-computed
    created_by:          Mapped[str | None]       = mapped_column(String(64), nullable=True)
    created_at:          Mapped[datetime]         = mapped_column(DateTime, server_default=func.now())
    updated_at:          Mapped[datetime]         = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("plant", "reading_date", name="uq_utility_diesel"),)


class MtUtilityGas(RdsBase):
    """Daily gas log. Formulas (app-computed):
    gas_consumed_m3 = (closing - opening) * gas_conversion_factor;
    daily_gas_cost = gas_consumed_m3 * gas_rate;
    cost_per_unit = daily_gas_cost / production_units (null when production 0/blank)."""
    __tablename__ = "mt_utility_gas"

    id:                    Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant:                 Mapped[str]            = mapped_column(String(16), index=True)
    reading_date:          Mapped[date]           = mapped_column(Date, index=True)
    gas_meter_opening:     Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    gas_meter_closing:     Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    gas_conversion_factor: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True, server_default="1.44")
    gas_rate:              Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    production_units:      Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    remark:                Mapped[str | None]     = mapped_column(Text, nullable=True)
    gas_consumed_m3:       Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)   # app-computed
    daily_gas_cost:        Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)   # app-computed
    cost_per_unit:         Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)   # app-computed
    created_by:            Mapped[str | None]     = mapped_column(String(64), nullable=True)
    created_at:            Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())
    updated_at:            Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("plant", "reading_date", name="uq_utility_gas"),)


class MtUtilityElectricity(RdsBase):
    """Daily electricity log (kWh + KVAH). Formulas (app-computed):
    electricity_consumed_kwh = (closing_kwh - opening_kwh) * ct_multiplier;
    electricity_consumed_kvah = closing_kvah - opening_kvah;
    daily_electricity_cost = electricity_consumed_kwh * electricity_rate;
    cost_per_unit = daily_electricity_cost / production_units (null when production 0/blank)."""
    __tablename__ = "mt_utility_electricity"

    id:                        Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant:                     Mapped[str]            = mapped_column(String(16), index=True)
    reading_date:              Mapped[date]           = mapped_column(Date, index=True)
    department:                Mapped[str | None]     = mapped_column(String(64), nullable=True)
    energy_meter_opening_kwh:  Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    energy_meter_closing_kwh:  Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    energy_meter_opening_kvah: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    energy_meter_closing_kvah: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    ct_multiplier:             Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True, server_default="4")
    electricity_rate:          Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    production_units:          Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    remark:                    Mapped[str | None]     = mapped_column(Text, nullable=True)
    electricity_consumed_kwh:  Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)   # app-computed
    electricity_consumed_kvah: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)   # app-computed
    daily_electricity_cost:    Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)   # app-computed
    cost_per_unit:             Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)   # app-computed
    created_by:                Mapped[str | None]     = mapped_column(String(64), nullable=True)
    created_at:                Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())
    updated_at:                Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("plant", "reading_date", name="uq_utility_electricity"),)


class MtUtilityWater(RdsBase):
    """Daily water log. Formulas (app-computed):
    water_consumed = closing - opening; daily_water_cost = water_consumed * water_rate;
    cost_per_unit = daily_water_cost / production_units (null when production 0/blank)."""
    __tablename__ = "mt_utility_water"

    id:                  Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant:               Mapped[str]              = mapped_column(String(16), index=True)
    reading_date:        Mapped[date]             = mapped_column(Date, index=True)
    water_meter_opening: Mapped[Decimal | None]   = mapped_column(Numeric(14, 3), nullable=True)
    water_meter_closing: Mapped[Decimal | None]   = mapped_column(Numeric(14, 3), nullable=True)
    water_rate:          Mapped[Decimal | None]   = mapped_column(Numeric(10, 4), nullable=True)
    production_units:    Mapped[Decimal | None]   = mapped_column(Numeric(14, 3), nullable=True)
    remark:              Mapped[str | None]       = mapped_column(Text, nullable=True)
    water_consumed:      Mapped[Decimal | None]   = mapped_column(Numeric(16, 3), nullable=True)   # app-computed
    daily_water_cost:    Mapped[Decimal | None]   = mapped_column(Numeric(16, 2), nullable=True)   # app-computed
    cost_per_unit:       Mapped[Decimal | None]   = mapped_column(Numeric(16, 4), nullable=True)   # app-computed
    created_by:          Mapped[str | None]       = mapped_column(String(64), nullable=True)
    created_at:          Mapped[datetime]         = mapped_column(DateTime, server_default=func.now())
    updated_at:          Mapped[datetime]         = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("plant", "reading_date", name="uq_utility_water"),)


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


# ============================================================================
# Spare Parts (W-202 only) — pre-existing stock table + a new usage/restock log.
# machine_name is free text, NOT a foreign key into mt_asset_list (see
# app/api/spare_parts.py for the best-effort name matching against the asset
# register). parts_name is a nested {"name", "unit"} blob, as already stored.
# ============================================================================

class MtSparePart(RdsBase):
    """Pre-existing spare-parts stock table (one row per machine + part)."""
    __tablename__ = "mt_202_spareparts"

    id:           Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parts_name:   Mapped[dict]       = mapped_column(PortableJSONB, nullable=False)   # {"name": ..., "unit": ...}
    quantity:     Mapped[int]        = mapped_column(Integer, nullable=False)


class MtSparePartLog(RdsBase):
    """Audit trail for every use/restock action — no dedicated UI screen yet,
    but every quantity change is traceable to a person/time from day one."""
    __tablename__ = "mt_202_spareparts_log"

    id:                Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    spare_part_id:     Mapped[int]             = mapped_column(ForeignKey("mt_202_spareparts.id"), nullable=False)
    machine_name:      Mapped[str | None]      = mapped_column(String(255), nullable=True)   # snapshot
    part_name:         Mapped[str | None]      = mapped_column(String(255), nullable=True)   # snapshot
    action:            Mapped[str]             = mapped_column(String(16), nullable=False)   # USE | RESTOCK
    quantity:          Mapped[int]             = mapped_column(Integer, nullable=False)       # always positive
    note:              Mapped[str | None]      = mapped_column(Text, nullable=True)
    performed_by:      Mapped[str | None]      = mapped_column(String(64), nullable=True)
    performed_by_name: Mapped[str | None]      = mapped_column(String(128), nullable=True)
    performed_at:      Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())
