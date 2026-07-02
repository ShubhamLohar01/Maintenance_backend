from datetime import date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


class _Trimmed(BaseModel):
    """Base model that strips leading/trailing whitespace from every string field
    BEFORE validation — so '  shubham ' -> 'shubham' and 'OK ' -> 'OK' (no 422)."""

    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, v):
        return v.strip() if isinstance(v, str) else v


# Known roles (normalized, uppercase). mt_users.role is free-text managed in
# pgAdmin (e.g. 'operator ', 'Head', 'qc') and normalized via MtUser.norm_role.
# LoginResponse.role is typed `str` (not this Literal) so a new/unexpected role
# value can never 500 the login endpoint.
Role = Literal["OPERATOR", "TECHNICIAN", "SUPERVISOR", "HEAD", "QC"]
Severity = Literal["CRITICAL", "MAJOR", "MINOR"]
Criticality = Literal["A", "B", "C"]
LoadFactorSource = Literal["ASSUMED", "SPOT_MEASURED", "IOT_METERED"]
RunStatus = Literal["IDLE", "RUNNING", "STOPPED", "FLAGGED"]
BreakdownStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    name: str
    role: str  # normalized uppercase; one of Role, but kept str so a stray mt_users.role never 500s login
    plant_id: str
    expires_at: int


class MachineDto(BaseModel):
    id: str
    code: str
    name: str
    location: str
    plant_id: str
    rated_kw: float
    load_factor: float
    load_factor_source: LoadFactorSource
    criticality: Criticality
    expected_run_hours: float
    current_status: RunStatus
    category: Optional[str] = None
    building: Optional[str] = None
    sub_location: Optional[str] = None
    updated_at: int


class RunStartRequest(BaseModel):
    machine_id: str
    started_at: int
    client_run_id: str
    scheduled_end_at: int


class RunStartResponse(BaseModel):
    run_id: str
    client_run_id: str
    started_at: int
    scheduled_end_at: int


class RunStopRequest(BaseModel):
    ended_at: int


class RunStopResponse(BaseModel):
    run_id: str
    ended_at: int
    computed_kwh: float


class FlagRaiseRequest(BaseModel):
    client_flag_id: str
    machine_id: str
    severity: Severity
    description: str
    photo_base64: Optional[str] = None
    raised_at: int


class FlagRaiseResponse(BaseModel):
    flag_id: str
    client_flag_id: str


class FlagDto(BaseModel):
    id: str
    machine_id: str
    plant_id: str
    operator_id: str
    operator_name: str
    severity: Severity
    description: str
    before_photo_url: Optional[str] = None
    after_photo_url: Optional[str] = None
    raised_at: int
    status: BreakdownStatus
    acknowledged_by_id: Optional[str] = None
    acknowledged_by_name: Optional[str] = None
    acknowledged_at: Optional[int] = None
    resolved_by_id: Optional[str] = None
    resolved_by_name: Optional[str] = None
    resolved_at: Optional[int] = None
    parts_used: Optional[str] = None


class FlagAcknowledgeRequest(BaseModel):
    user_id: str
    user_name: str
    acknowledged_at: int


class FlagResolveRequest(BaseModel):
    user_id: str
    user_name: str
    resolved_at: int
    parts_used: str
    after_photo_base64: Optional[str] = None


class FlagActionResponse(BaseModel):
    flag_id: str


class DailyRunDto(BaseModel):
    id: str
    started_at: int
    ended_at: Optional[int] = None
    duration_hours: float
    kwh: float


class DailyHistoryDto(BaseModel):
    date: str
    total_run_hours: float
    total_kwh: float
    estimated_cost: float
    runs: List[DailyRunDto]


class ActiveRunDto(BaseModel):
    """A run still in progress (ended_at IS NULL), for the Head's live overlay."""
    asset_id: str
    run_id: Optional[str] = None
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None
    started_at: int  # epoch ms (UTC) — same units as POST /energy/runs/start
    building: Optional[str] = None


# Extra (floor utility) — surfaced for an admin/dashboard view, not for the
# mobile-app contract.
class FloorUtilityReadingDto(BaseModel):
    floor_id: str
    floor_name: str
    reading_date: str
    meter_reading: Optional[float] = None
    daily_kwh: Optional[float] = None


class MtMachineDto(BaseModel):
    """A row from mt_asset_list — the real maintenance asset register."""
    asset_id: str
    asset_name: str
    building: Optional[str] = None
    sub_location: Optional[str] = None
    category: Optional[str] = None
    model_no: Optional[str] = None
    serial_no: Optional[str] = None
    power_load: Optional[str] = None
    rated_kw: Optional[float] = None
    quantity: Optional[int] = None
    condition: Optional[str] = None
    assigned_to: Optional[str] = None
    remarks: Optional[str] = None


class MtMachineUpdate(BaseModel):
    """Editable columns of an mt_asset_list row (PUT /mt-machines/{asset_id}).

    The app sends every editable field on each save (full update, not a patch).
    `asset_id` is the immutable path param, not part of the body. `rated_kw` is
    NOT accepted — it's recomputed server-side from `power_load`. Fields are
    Optional so a bad body (missing / blank building or asset_name) surfaces as a
    400 from the handler rather than a 422 from validation."""
    building: Optional[str] = None
    asset_name: Optional[str] = None
    category: Optional[str] = None
    sub_location: Optional[str] = None
    quantity: Optional[int] = None
    model_no: Optional[str] = None
    serial_no: Optional[str] = None
    power_load: Optional[str] = None
    condition: Optional[str] = None
    remarks: Optional[str] = None


class FloorSummaryDto(BaseModel):
    floor_id: str
    floor_name: str
    machine_count: int
    total_rated_kw: float
    latest_meter_reading: Optional[float] = None
    last_30d_kwh: Optional[float] = None


# NOTE: MachineDailyKwhUpsertRequest / MachineDailyKwhDto were retired on
# 2026-06-25 along with POST /mt-machines/{id}/daily-kwh — mt_machine_daily_kwh is
# now written only by the run Start/Stop flow (see RunStart*/RunStop* above).


# --- Technician "Daily Reading" (per-floor actual vs system) ---

class FloorSystemReadingDto(BaseModel):
    """One floor's system-generated reading (kWh total from runs that day) plus any
    actual meter reading already saved for the date. `system_reading` is stored in
    mt_floor_utility_readings.daily_kwh."""
    floor: str
    system_reading: float
    meter_reading: Optional[float] = None  # already-saved actual reading, else null


class FloorReadingsResponse(BaseModel):
    building: str
    reading_date: str  # ISO YYYY-MM-DD
    floors: List[FloorSystemReadingDto]


class FloorReadingRowIn(_Trimmed):
    floor: str
    meter_reading: float


class FloorReadingsSubmitRequest(_Trimmed):
    """Batch submit — all floors' actual meter readings for one date. `reading_date`
    defaults to today (server UTC) when omitted. `building` is required only for
    HEAD/SUPERVISOR (others always write their own plant). The server recomputes
    `system_reading` per floor; any client-sent system value is ignored."""
    reading_date: Optional[str] = None  # ISO YYYY-MM-DD
    building: Optional[str] = None       # A-185 / W-202; ignored for non-HEAD callers
    rows: List[FloorReadingRowIn]


class FloorReadingsSubmitResponse(BaseModel):
    building: str
    reading_date: str
    saved: int


PmFormType = Literal["MONTHLY", "QUARTERLY"]
PmRecordStatus = Literal["DRAFT", "SUBMITTED"]
PmItemStatus = Literal["OK", "NOT_OK", "UNSET"]  # UNSET = untouched (drafts only)


class PmChecklistItem(_Trimmed):
    section: str
    equipment: str
    sr_no: Optional[int] = None
    equipment_date: str = ""  # ISO yyyy-MM-dd; date this equipment was checked
    checkpoint: str = ""
    status: PmItemStatus = "UNSET"
    remarks: str = ""


class PmChecklistRequest(_Trimmed):
    form_type: PmFormType
    doc_no: str
    status: PmRecordStatus = "SUBMITTED"  # DRAFT (partial) | SUBMITTED (final)
    checklist_date: str  # ISO YYYY-MM-DD
    done_by: str = ""
    checked_by: str = ""
    verified_by: str = ""
    remarks: str = ""
    created_by: Optional[str] = None  # ignored — backend uses the logged-in user
    items: List[PmChecklistItem]


class PmChecklistCreatedResponse(BaseModel):
    id: int


# --- Read-back DTOs (status/form_type kept as plain str so reads never 500 on
#     unexpected stored values; the app only reads these snake_case keys). ---
class PmChecklistListItemDto(BaseModel):
    id: int
    form_type: str
    doc_no: str
    status: str = "SUBMITTED"  # DRAFT | SUBMITTED
    checklist_date: str
    done_by: str
    created_at: str  # ISO 8601 UTC, e.g. "2026-06-20T11:30:00Z"


class PmChecklistDetailItemDto(BaseModel):
    section: str
    equipment: str
    sr_no: Optional[int] = None
    equipment_date: str = ""
    checkpoint: str = ""
    status: str
    remarks: str = ""


class PmChecklistDetailDto(BaseModel):
    id: int
    form_type: str
    doc_no: str
    status: str = "SUBMITTED"  # DRAFT | SUBMITTED
    checklist_date: str
    done_by: str
    checked_by: str
    verified_by: str
    remarks: str
    created_at: str
    items: List[PmChecklistDetailItemDto]


class MachineTransferCreatedResponse(BaseModel):
    id: int
    proof_photo_url: Optional[str] = None  # null when no photo was attached


class MachineTransferListItemDto(BaseModel):
    id: int
    date: str  # ISO yyyy-MM-dd ("" if not recorded)
    from_warehouse: str
    to_warehouse: str
    machine_name: str
    condition: Optional[str] = None
    created_at: str  # ISO 8601 UTC


# --- Breakdown Maintenance Record (CFPLA.C4.F.06) ---

class BreakdownEntryIn(_Trimmed):
    """One breakdown row. Lenient — every field optional so a partially-filled
    row never 422s; an empty/blank `record_date` is coerced to NULL (see below)."""
    record_date:             Optional[date] = None   # ISO yyyy-MM-dd; "" / null -> NULL
    location:                str = ""
    machine_name:            str = ""
    equipment_model_no:      str = ""
    problem_in_brief:        str = ""
    type_of_maintenance:     str = ""
    part_of_machine:         str = ""
    temporary_reason:        str = ""
    duration_start:          str = ""
    duration_end:            str = ""
    machine_operator_sign:   str = ""
    maintenance_person_sign: str = ""
    qc_clearance_sign:       str = ""

    @field_validator("record_date", mode="before")
    @classmethod
    def _blank_date_to_none(cls, v):
        # Empty/whitespace string from a partially-filled form -> store NULL, no 422.
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return v


class BreakdownSheetIn(_Trimmed):
    doc_no:      str = "CFPLA.C4.F.06"
    verified_by: str = ""
    entries:     List[BreakdownEntryIn] = []


class BreakdownCreatedResponse(BaseModel):
    ids: List[int]


class BreakdownRecordDto(BaseModel):
    """One stored F.06 row — read-back for GET /preventive-maintenance/breakdowns.
    All string fields default to "" (empty, never null); only `id` is a real int."""
    id: int
    doc_no: str = ""
    record_date: str = ""          # YYYY-MM-DD ("" when not set)
    location: str = ""
    machine_name: str = ""
    equipment_model_no: str = ""
    problem_in_brief: str = ""
    type_of_maintenance: str = ""
    part_of_machine: str = ""
    temporary_reason: str = ""
    duration_start: str = ""
    duration_end: str = ""
    machine_operator_sign: str = ""
    maintenance_person_sign: str = ""
    qc_clearance_sign: str = ""
    verified_by: str = ""
    created_at: str = ""           # ISO-8601 UTC, e.g. 2026-06-27T11:35:00Z


# --- Head read views ---

class LiveMachineDto(BaseModel):
    """One machine's current run state for the Head's live machine list. `status`
    is RUNNING / FLAGGED / IDLE today (the app's enum also allows STOPPED/PENDING_QC,
    which this backend doesn't yet track). operator + start are null when idle."""
    machine_id: str
    name: str
    building: str
    plant_id: str
    status: str
    current_operator_id: Optional[str] = None
    current_operator_name: Optional[str] = None
    run_started_at: Optional[str] = None  # ISO 8601 Z, null when idle


class EscalationItemDto(BaseModel):
    """One overdue item for the Head escalations list. `tier_role` is descriptive
    (TECHNICIAN/SUPERVISOR/HEAD); SUPERVISOR has no backing users yet."""
    type: str            # "BREAKDOWN"
    flag_id: str
    machine_id: str
    machine_name: str
    plant_id: str
    severity: str
    status: str
    raised_at: Optional[str] = None  # ISO 8601 Z
    days_overdue: int
    tier: int            # 1 | 2 | 3
    tier_role: str       # TECHNICIAN | SUPERVISOR | HEAD
    proof_photo_url: Optional[str] = None


# --- QC clearance on a resolved breakdown flag ---
QcStatus = Literal["APPROVED", "REJECTED"]


class QcDecisionRequest(_Trimmed):
    qc_status: QcStatus
    qc_notes: str = ""


class QcDecisionResponse(BaseModel):
    flag_id: str
    qc_status: str


# --- Head read views (multi-warehouse, token-scoped) ---

class HeadBreakdownDto(BaseModel):
    """#2 — one breakdown across the Head's warehouses. `status` shows PENDING_QC
    for a RESOLVED flag still awaiting QC; `qc_status` is APPROVED/DISAPPROVED/null."""
    id: str
    machine_id: str
    machine_name: str = ""
    plant_id: str
    severity: str
    status: str  # OPEN | ACKNOWLEDGED | RESOLVED | PENDING_QC
    description: str = ""
    raised_at: Optional[str] = None
    acknowledged_by_name: Optional[str] = None
    resolved_by_name: Optional[str] = None
    qc_status: Optional[str] = None  # APPROVED | DISAPPROVED | null


class HeadQcAwaitingDto(BaseModel):
    flag_id: str
    machine_id: str
    machine_name: str = ""
    plant_id: str
    severity: str
    description: str = ""
    resolved_by_name: Optional[str] = None
    resolved_at: Optional[str] = None


class HeadQcDecidedDto(BaseModel):
    flag_id: str
    machine_id: str
    machine_name: str = ""
    plant_id: str
    qc_status: str  # APPROVED | DISAPPROVED
    qc_decided_by_name: Optional[str] = None
    qc_decided_at: Optional[str] = None
    qc_notes: Optional[str] = None
    resolved_by_name: Optional[str] = None


class HeadQcActivityDto(BaseModel):
    awaiting: List[HeadQcAwaitingDto]
    decided: List[HeadQcDecidedDto]


class HeadTransferDto(BaseModel):
    id: int
    date: str  # ISO yyyy-MM-dd ("" if not recorded)
    from_warehouse: str
    to_warehouse: str
    machine_name: str
    condition: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    proof_photo_url: Optional[str] = None


class PowerByDayDto(BaseModel):
    date: str
    kwh: float


class PowerByMachineDto(BaseModel):
    machine_id: str
    name: str = ""
    kwh: float


class WarehousePowerDto(BaseModel):
    plant_id: str
    total_kwh: float
    by_day: List[PowerByDayDto]
    by_machine: List[PowerByMachineDto]


class HeadPowerReportDto(BaseModel):
    from_: str = Field(serialization_alias="from")  # serialized as "from"
    to: str
    warehouses: List[WarehousePowerDto]

    model_config = {"populate_by_name": True}


# --- Operator breakdown flags (persisted to mt_breakdown_records) ---
# Mirrors the Android BreakdownApi.kt / BreakdownDtos.kt contract exactly.

class BreakdownFlagRequest(_Trimmed):
    machine_id: str                       # = mt_asset_list.asset_id
    operator_id: Optional[str] = None     # hint; backend resolves to a name
    severity: str = "MAJOR"
    description: str = ""
    before_photo_path: Optional[str] = None
    raised_at: int                        # epoch ms


class BreakdownFlagResponse(BaseModel):
    id: str
    sync_status: str = "SYNCED"


class QcAckRequest(_Trimmed):
    user_id: str = ""
    user_name: str = ""
    qc_checked_by: Optional[str] = None   # QC login username; only the QC path sends it (nullable)
    acknowledged_at: int                  # epoch ms
    override: bool = False


class QcDecideRequest(_Trimmed):
    user_id: str = ""
    user_name: str = ""
    decided_at: int                       # epoch ms
    checklist_json: str = ""
    after_photo_path: Optional[str] = None
    notes: Optional[str] = None
    reason: Optional[str] = None


class BreakdownWorkDoneRequest(_Trimmed):
    """Technician submits the completed repair -> status PENDING_QC, qc_status PENDING."""
    user_id: str = ""
    user_name: str = ""
    work_done: str = ""
    after_photo_path: Optional[str] = None
    done_at: int                          # epoch ms


class QcUpdateResponse(BaseModel):
    id: str
    ticket_status: str                    # OPEN | ACKNOWLEDGED | PENDING_QC | CLOSED | REOPENED
    machine_status: str                   # UNDER_BREAKDOWN | AVAILABLE
    qc_status: Optional[str] = None       # PENDING | APPROVED | DISAPPROVED | null
    sync_status: str = "SYNCED"


class OpenBreakdownDto(BaseModel):
    id: str
    asset_id: str
    asset_name: str = ""
    reported_by: Optional[str] = None
    reporter_name: Optional[str] = None
    severity: Optional[str] = None
    description: str = ""
    status: str
    reported_at: Optional[int] = None       # epoch ms
    # Lifecycle transition times (epoch ms, null until they happen) — the app times
    # its reminder escalations off these; same clock/units as reported_at.
    acknowledged_at: Optional[int] = None    # technician acknowledged
    resolved_at: Optional[int] = None        # technician finished the repair (work-done)
    qc_acknowledged_at: Optional[int] = None # QC picked up the awaiting-QC ticket
    qc_decided_at: Optional[int] = None      # QC approved or disapproved
    building: Optional[str] = None
    qc_reject_reason: Optional[str] = None  # why QC sent it back (null unless re-opened by a disapprove)


# --- Device push-token registration (P2 FCM push scaffolding) ---

class DeviceTokenRequest(_Trimmed):
    """Register/refresh this device's FCM token. `user_id` is an optional hint —
    it defaults to the authenticated caller. Upserted on `token`."""
    user_id: str = ""
    token: str
    platform: str = "android"


class DeviceTokenResponse(BaseModel):
    id: int
    user_id: str
    platform: str
