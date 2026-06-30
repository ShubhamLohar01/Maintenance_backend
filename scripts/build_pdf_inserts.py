"""Generate INSERT statements for mt_machine_list from the floor-machinery PDF.

The PDF (floor machinery equipment.pdf) is the maintenance team's most-detailed
machine register: it carries actual nameplate kW / amps and company / model /
serial numbers for many rows that are blank in machine-list.xlsx.

Output: mt_machine_list_from_pdf.sql (PostgreSQL).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils import parse_kw, parse_qty, infer_machine_type  # noqa: E402


# (area, name, company, model_no, serial_no, rated_kw_raw, rated_amps, quantity_raw)
#
# area names below are normalised to match mt_floor_utility_readings.floor where
# possible. NPD / Printing / LAB are sub-sections of Service floor (they share
# the same sub-meter) — kept distinct so the maintenance team doesn't lose that
# breakdown.
ROWS: list[tuple] = [
    # ---------------- LOWER BASEMENT ----------------
    ("Lower basement", "shrink wrap packaging machine", "shanti packaging", "550616", None, None, None, None),
    ("Lower basement", "shrink wrap packaging machine", "shanti packaging", None, None, "0.1 kw", None, None),
    ("Lower basement", "L sealer machine", "advance packaging", "400", None, "3 kw", None, None),
    ("Lower basement", "induction heat sealer", "R- TECHNIC", "46/22-23", None, "5 kw", None, None),
    ("Lower basement", "pet sealer machine", "gang shing", "1793", None, "0.98 kw", None, None),
    ("Lower basement", "stripping mchine", "shanti packaging", "16/20/36", None, None, "5 A", None),
    ("Lower basement", "band sealer", "shanti packaging", "1111121115368", None, "6.96 kw", None, None),
    ("Lower basement", "air conditioner indoor unit", None, "pety-p63vma -e4", None, "3.1 kw", "5.52 A", None),
    ("Lower basement", "vaccum machine", None, None, None, "45 w", None, None),
    ("Lower basement", "fly catcher", None, None, None, "1 kw", None, None),
    ("Lower basement", "tube light", None, None, None, "1 kw", "4.0 A", None),
    ("Lower basement", "drain pump", None, None, None, None, "3 A", None),
    ("Lower basement", "led flood light", None, None, None, None, None, None),

    # ---------------- UPPER BASEMENT ----------------
    ("Upper basement", "stripping mchine", "shanti pckaging", None, None, "0.98 kw", "5 A", None),
    ("Upper basement", "packaging machine", "multivac", "437123.2038", None, "5 kw", "19 A", None),
    ("Upper basement", "werner finley", "werner finley", "384095", None, "1.6 kw", "9.5 A", None),
    ("Upper basement", "stablzer", "golden", "3025070632", None, "0.65", None, None),
    ("Upper basement", "band sealing", "shanti packaging", "T1906-0241", None, None, None, None),
    ("Upper basement", "LED flood light", None, "1111121115368", None, None, None, None),
    ("Upper basement", "AC indoor", None, None, None, "7.83 kw", "6.21 A", None),
    ("Upper basement", "fresh air unit", None, "pety-p63vma -e4", None, None, None, None),
    ("Upper basement", "tube light", None, None, None, "1440 watt", None, None),
    ("Upper basement", "fly catcher", None, None, None, None, None, None),

    # ---------------- SERVICE FLOOR ----------------
    ("Service floor", "D.G.", "powerica", "CP 160DSP", "PLIC/08/2016/160/0236", "128 KW", None, None),
    ("Service floor", "compressor", "ingersoll rand", "2545", "NAR10100226", None, None, None),
    ("Service floor", "compressor", "ingersoll rand", "2545", "NAR10081963", None, None, None),
    ("Service floor", "compressor", "ingersoll rand", "2545", "NAR10494391", None, None, None),

    # NPD (sub-section of Service floor)
    ("NPD", "pan coating machine", None, None, None, None, None, None),
    ("NPD", "roasting oven", "safire industrise", None, None, None, None, None),
    ("NPD", "envirometal test chamber", None, "ETC-1", None, None, None, None),
    ("NPD", "blast freezer", None, None, None, None, None, None),

    # Printing (sub-section of Service floor)
    ("Printing", "inkjet codeding machine", "docod", "5200", "DSC1406", None, "1.9 A", None),
    ("Printing", "printing conveyor", None, None, None, "0.18 KW", None, None),
    ("Printing", "inkjet codeding machine", "videojet", "1220", "17194016C21ZH", "120 W", "3 A", None),
    ("Printing", "printing conveyor", None, None, None, "0.18 KW", None, None),
    ("Printing", "markem imaje", "markem imaje", "smart date x45", "IN19080032", None, None, None),
    ("Printing", "conveyor", None, None, None, "0.18 KW", None, None),
    ("Printing", "markem imaje", "markem imaje", "smart date x45", "IN22270064", None, None, None),
    ("Printing", "conveyor", None, None, None, "0.18 KW", None, None),
    ("Printing", "markem imaje", "markem imaje", "smart date x45", "IN23170073", None, None, None),
    ("Printing", "conveyor", None, None, None, "0.18 KW", None, None),
    ("Printing", "laser marking machine", None, "SJ-SW", "20250427882820", None, None, None),
    ("Printing", "cooling devices", None, "HCOO3X3C", "11702-09-2025", "0.6 KW", "3.5 A", None),

    # LAB (sub-section of Service floor)
    ("LAB", "weigh balance", "analytical weighing", None, "1700777", None, None, None),
    ("LAB", "moisture analyser", None, None, "D209412040", None, None, None),
    ("LAB", "moisture analyser", None, None, "D209411580", None, None, None),
    ("LAB", "analylical weighing balance", None, None, "2008062", None, None, None),
    ("LAB", "galaxy dcientific equipments", None, None, None, None, None, None),
    ("LAB", "radhika scientific", None, None, "101", None, None, None),
    ("LAB", "hot air oven", None, None, None, None, None, None),
    ("LAB", "tube light", None, None, None, "820 W", None, "24 nos"),
    ("LAB", "hand sealer", None, None, None, None, None, None),
    ("LAB", "exhuast fan", None, None, None, None, None, None),

    # ---------------- 1ST FLOOR ----------------
    ("1st floor", "straooing machine", None, None, "19050016", "0.88KW", "5 A", None),
    ("1st floor", "band sealing machine", "shanti packeging", "FR-900", None, "0.65 KW", None, None),
    ("1st floor", "band sealing machine", "shanti packeging", "FR-900", None, "0.65 KW", None, None),
    ("1st floor", "foot stamping sealing machine", "shanti packeging", "PSF-350", None, "500 W", None, None),
    ("1st floor", "metal detector", "das electronic", "MD-011", "20211121140", None, None, None),
    ("1st floor", "greeding machine", "sepro gyroscreen", "SG-900-250", None, "4 KW", "2.1 A", None),
    ("1st floor", "vibrator", "magnetics vibro equipments", "G3J2348610466", None, "0.37 KW", "1.10 A", None),
    ("1st floor", "f.f.s. machine", "wraptech", "MB25MSD", "1716", None, None, None),
    ("1st floor", "markem imaje", None, "smart date x40 equipments", "IN 23350025", None, None, None),
    ("1st floor", "markem imaje", "magnetics vibro equipments", None, "IN 23350026", None, None, None),
    ("1st floor", "metal detector", "technofor", "ADM-769-17", None, None, None, None),
    ("1st floor", "conveyor", None, None, None, None, None, None),
    ("1st floor", "stabilizer machine", "golden 615", "T1908-0554", None, "15 KVA", "21 A", None),
    ("1st floor", "tube light", None, None, None, "840 W", None, "36 nos"),
    ("1st floor", "fly catcher", None, None, None, None, None, "2 nos"),

    # ---------------- 1ST FLOOR MEZZANINE ----------------
    ("1st floor mezzanine", "vaccum machine", "winner electronics", "DCS35511-63", None, "3.5 KW", None, None),
    ("1st floor mezzanine", "hopper weighing system", "hdm", "14-2B-01", "88170900", None, None, None),
    ("1st floor mezzanine", "shrink machine", "clearpack", "EF19028A", None, None, None, None),
    ("1st floor mezzanine", "band sealing machine", "shanti packeging", "FR-900", None, "0.65 KW", None, None),
    ("1st floor mezzanine", "band sealing machine", "shanti packeging", "FR-900", None, "0.65 KW", None, None),
    ("1st floor mezzanine", "metal detector", "technofour", None, "ARM-21534/20", None, None, None),
    ("1st floor mezzanine", "shrink machine heater tunnel", "advance packaging", "93T310VL", "1900", "9 KW", None, None),
    ("1st floor mezzanine", "tube light", None, None, None, "840 W", None, "36 nos"),
    ("1st floor mezzanine", "fly catcher", None, None, None, None, None, "3 nos"),

    # ---------------- 2ND FLOOR ----------------
    ("2nd floor", "x-ray mchine", "mekitec", None, "61154479393", "100 W", "3 A", None),
    ("2nd floor", "shrink wrap machine", None, "DQL55455", None, "2.2 KW", None, None),
    ("2nd floor", "heater tunnel", None, "SRD-45D-4520", None, "12.81 KW", None, None),
    ("2nd floor", "packing machine", None, "AP-350", None, "2.4 KW", None, None),
    ("2nd floor", "packing machine", "wraptech", "WH-350", "1301", "2.4 KW", None, None),
    ("2nd floor", "markem imaje", None, None, "IN17390019", None, None, None),
    ("2nd floor", "packing machine", None, None, None, None, None, None),
    ("2nd floor", "chocolate topex", "selmi", "TOPEX", "TPX00003788", "3.5 KW", None, None),
    ("2nd floor", "chocolate tank -200", "selmi", "TANK -200", "TANK 200001194", "4.5 KW", None, None),
    ("2nd floor", "chocolate tunnel", "selmi", "TUN-800", "TUN8000000919", "0.62 KW", None, None),
    ("2nd floor", "water heater", None, "KF-55", None, "5.5 KW", None, None),
    ("2nd floor", "band sealing machine", "shanti packaging", "FR-900", None, "0.65 KW", None, None),
    ("2nd floor", "sruger salecker machine", None, "1420", "MFT-300.062.600.00", "1.5 KW", None, None),
    ("2nd floor", "conveyor", "hindustan", None, None, "0.35 KW", None, None),
    ("2nd floor", "conveyor", "hindustan", None, None, "0.35 KW", None, None),
    ("2nd floor", "tree rostor /baking oven", "neel industries", None, None, None, None, None),
    ("2nd floor", "packing machine", "TLM", "FUTURA", None, "2.76 KW", None, None),
    ("2nd floor", "pan coating machine", "selmi", "COMFIT", "COM00001945", "1.8 KW", None, None),
    ("2nd floor", "chocolate panning machine", "wecan", "15INCH-55316/55304", "27622", None, None, None),
    ("2nd floor", "food sealing machine", None, None, None, None, None, None),
    ("2nd floor", "eshuast fan", None, None, None, None, None, "2 nos"),
    ("2nd floor", "pannel light", None, None, None, None, None, "9 nos"),
    ("2nd floor", "fly catcher", None, None, None, None, None, "3 nos"),
    ("2nd floor", "tube light", None, None, None, None, None, "18 nos"),
    ("2nd floor", "sheet and cut machine", None, None, None, None, None, None),

    # ---------------- 2ND FLOOR MEZZANINE ----------------
    ("2nd floor mezzanine", "padal mixer -1", "dierks sohne", "2840-0921", None, None, None, None),
    ("2nd floor mezzanine", "padal mixer -2", None, None, "IT/1", None, None, None),
    ("2nd floor mezzanine", "mixer", "kr engineering work", None, None, None, None, None),
    ("2nd floor mezzanine", "baking oven", "safire industrirs", None, None, None, None, None),
    ("2nd floor mezzanine", "freezer", None, None, None, None, None, None),

    # ---------------- TERRACE ----------------
    ("Terrace", "water bath", None, None, None, None, None, None),
    ("Terrace", "try roastor -1", None, None, None, None, None, None),
    ("Terrace", "try roastor -2", None, None, None, None, None, None),
    ("Terrace", "food sealing machine", None, "PSF-350", None, "500 W", None, None),
    ("Terrace", "vaccume machine", "winner electronics", None, None, None, None, None),
    ("Terrace", "coating pan", None, None, None, None, None, None),
    ("Terrace", "band seling machine", "shanti packaging", "FR-900", None, "0.65 KW", None, None),
    ("Terrace", "slicer /slivered machine", None, None, None, None, None, None),
    ("Terrace", "dicer machine", "hari om indudtries", None, None, None, None, None),
    ("Terrace", "aro plant -1000 L", None, None, None, None, None, None),
    ("Terrace", "aro plant -4000 L", None, "1465", "154", None, None, None),
]


def esc(v) -> str:
    if v is None:
        return "NULL"
    s = str(v).strip()
    if s == "":
        return "NULL"
    return "'" + s.replace("'", "''") + "'"


def main():
    lines = [
        "-- ===========================================================",
        "-- mt_machine_list — INSERTS from 'floor machinery equipment.pdf'",
        "-- ===========================================================",
        "-- NPD, Printing and LAB are sub-sections of Service floor",
        "-- (they share the Service-floor electrical sub-meter).",
        "-- Run AFTER the table has been created (and is empty).",
        "-- If the table already has rows, run TRUNCATE first:",
        "--     TRUNCATE TABLE mt_machine_list;",
        "",
    ]

    for i, (area, name, company, model, serial, rkw, ramps, qty) in enumerate(ROWS, start=1):
        mid = f"MCH-{i:04d}"
        kw_parsed = parse_kw(rkw)
        qty_parsed = parse_qty(qty)
        mtype = infer_machine_type(name or "")
        kw_sql = f"{kw_parsed:.3f}" if kw_parsed > 0 else "NULL"
        lines.append(
            "INSERT INTO mt_machine_list "
            "(machine_id, floor, machine_name, company, model_no, serial_no, "
            "rated_kw_raw, rated_kw, rated_amps, quantity_raw, quantity, machine_type) VALUES "
            f"({esc(mid)}, {esc(area)}, {esc(name)}, {esc(company)}, {esc(model)}, {esc(serial)}, "
            f"{esc(rkw)}, {kw_sql}, {esc(ramps)}, "
            f"{esc(qty)}, {qty_parsed}, {esc(mtype)});"
        )

    lines.append("")
    lines.append(f"-- Inserted {len(ROWS)} machines from PDF")

    out = ROOT / "mt_machine_list_from_pdf.sql"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(ROWS)} INSERT rows to {out}")


if __name__ == "__main__":
    main()
