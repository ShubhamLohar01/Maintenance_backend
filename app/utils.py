import re
from datetime import datetime, timezone


def to_epoch_ms(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def from_epoch_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def iso_z(dt: datetime | None) -> str | None:
    """Naive-UTC datetime -> ISO 8601 with a trailing Z (e.g. 2026-06-20T11:30:00Z).
    Returns None (JSON null) for None — used by read DTOs where 'not set' must be null."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None, microsecond=0).isoformat() + "Z"


# --- Plant / building codes -------------------------------------------------
# The DB stores the hyphenated building form ("A-185"); the mobile app uses the
# compact form ("A185"). These keep the two spellings interchangeable.
ALL_BUILDINGS = ["A-185", "W-202"]  # canonical DB form (mt_asset_list.building, etc.)


def norm_plant(s: str | None) -> str:
    """Compact, comparable plant code: 'A-185'/'a185'/' A185 ' -> 'A185'."""
    if not s:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(s)).upper()


def building_for(plant: str | None) -> str | None:
    """Resolve any plant spelling to the canonical DB building form, or None.

    mt_users.location is often descriptive — 'A-185-Koparkhairne',
    '185-Koparkhairnae', 'W202', 'W-202-Koparkhairne' — so match leniently: the
    building code ('A185'/'W202') OR just its number ('185'/'202') appearing in the
    normalized location is enough. 'both' / blank / unrelated -> None (HEAD and
    SUPERVISOR are all-plant and handled before this call)."""
    n = norm_plant(plant)
    if not n:
        return None
    for b in ALL_BUILDINGS:
        nb = norm_plant(b)                 # 'A185' / 'W202'
        digits = re.sub(r"\D", "", nb)     # '185' / '202'
        if nb in n or (digits and digits in n):
            return b
    return None


# Roles that see every plant (cross-plant oversight), vs. own-plant-only roles
# (OPERATOR, TECHNICIAN). Keep this in one place so every scoped view agrees.
_ALL_PLANT_ROLES = {"HEAD", "SUPERVISOR"}


def scoped_buildings(user, requested: str | None = None) -> list[str]:
    """Buildings (DB form) this caller may see.

    HEAD / SUPERVISOR -> all buildings, optionally narrowed by `requested`
    (comma-separated, any spelling). Everyone else (OPERATOR, TECHNICIAN) -> only
    their own building (from user.plant_id); `requested` is ignored so they can
    never read another plant."""
    if getattr(user, "norm_role", "") in _ALL_PLANT_ROLES:
        allowed = list(ALL_BUILDINGS)
        if requested:
            wanted = {norm_plant(p) for p in requested.split(",") if p.strip()}
            allowed = [b for b in allowed if norm_plant(b) in wanted]
        return allowed
    own = building_for(getattr(user, "plant_id", None))
    return [own] if own else []


_KW_RE = re.compile(r"([\d.]+)\s*(kw|watt|w)\b", re.IGNORECASE)


def parse_kw(raw: str | None) -> float:
    """Parse mixed units e.g. '508watt' -> 0.508, '1.5kw' -> 1.5, '150W' -> 0.150.
    Returns 0.0 on unparseable / blank input.
    """
    if not raw:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    m = _KW_RE.search(s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return 0.0
    value = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ("w", "watt"):
        return value / 1000.0
    return value


_QTY_RE = re.compile(r"(\d+)")


def parse_qty(raw: str | None) -> int:
    if not raw:
        return 1
    m = _QTY_RE.search(str(raw))
    return int(m.group(1)) if m else 1


_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("roaster", "ROASTER"),
    ("compressor", "COMPRESSOR"),
    ("pack", "PACKING_LINE"),
    ("seal", "PACKING_LINE"),
    ("conveyor", "CONVEYOR"),
    ("weigh", "WEIGHING_SCALE"),
    ("scale", "WEIGHING_SCALE"),
    ("dg", "DG_SET"),
    ("diesel", "DG_SET"),
    ("ac", "HVAC"),
    ("hvac", "HVAC"),
    ("vrv", "HVAC"),
    ("boiler", "BOILER"),
    ("mixer", "MIXER"),
    ("welding", "WELDING"),
    ("pump", "PUMP"),
]


def infer_machine_type(name: str) -> str:
    if not name:
        return "OTHER"
    low = name.lower()
    for kw, t in _TYPE_KEYWORDS:
        if kw in low:
            return t
    return "OTHER"


# Items that aren't proper "production machines" but appear in the master sheet:
# lighting, fans, ACs, fly catchers, drain pumps, water heaters, etc. The mobile
# app groups these under an "Others" section so they don't clutter the
# production-machine view.
_OTHERS_KEYWORDS: list[str] = [
    "tube light", "tubes light",
    "led flood light", "flood light",
    "pannel light", "panel light",
    "fly catcher",
    "exhuast fan", "eshuast fan", "exhaust fan",
    "ac indoor", "air conditioner", "fresh air",
    "drain pump", "drian pump",
    "water heater", "water bath",
]


def categorise(name: str) -> str:
    """Return 'OTHERS' for facility/utility items, 'PRODUCTION' otherwise."""
    low = (name or "").strip().lower()
    for kw in _OTHERS_KEYWORDS:
        if kw in low:
            return "OTHERS"
    return "PRODUCTION"
