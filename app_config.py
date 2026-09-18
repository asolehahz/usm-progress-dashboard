"""App configuration — Google Sheet IDs, campus mapping, activity columns."""

SHEET_ID = "1-0DFZT-jrzdUkEfjS1v0S2Z13qSEjRcEGp5b6DbFp1o"

# Each tab = one campus. Name must match the Google Sheet tab title exactly.
# GID from the URL when you click the tab: .../edit#gid=XXXXXXXX
SHEET_TABS = {
    "INDUK": "1128960310",
    "NIBONG TEBAL": "1224245491",
    "BERTAM": "129329596",
    "BUKIT JAMBUL": "1957109182",
    "KUBANG KERIAN": "602849075",
}

# Optional reference tab (current desa snapshot). Historical graphs still use INDUK date blocks.
INDUK_DESA_TAB = "INDUK(DESA)"
INDUK_DESA_GID = "1770942368"

CAMPUS_ICONS = {
    "INDUK": "🏫",
    "NIBONG TEBAL": "🏢",
    "BERTAM": "🏛️",
    "BUKIT JAMBUL": "🏬",
    "KUBANG KERIAN": "🏟️",
}


def campus_sheet_names() -> list[str]:
    return list(SHEET_TABS.keys())


ACTIVITIES = [
    "Trunking",
    "Lay Cable",
    "Termination",
    "UTP Point",
    "AP Mounting",
    "Slab Coring (hole)",
    "Rack Installation (nos)",
    "Fiber Optic",
]

# Dashboard line chart — only these activities.
DASHBOARD_CHART_ACTIVITIES = [
    "UTP Point",
    "AP Mounting",
    "Fiber Optic",
]

# Dashboard metrics — show Done/Total instead of %.
FRACTION_METRIC_ACTIVITIES = [
    "UTP Point",
    "AP Mounting",
    "MultiGE Switch",
    "Controller",
    "RFS",
]

# Sheet DONE + TOTAL are trusted (fraction updates); % = DONE÷TOTAL.
TRUSTED_DONE_TOTAL_ACTIVITIES = [
    "UTP Point",
    "AP Mounting",
    "Slab Coring (hole)",
    "Rack Installation (nos)",
    "MultiGE Switch",
]

# Sheet has % + TOTAL only (no reliable DONE). Dashboard uses location-mean %.
# Daily DONE row shows N/A for these.
PCT_DERIVED_DONE_ROUND10 = [
    "Trunking",
    "Lay Cable",
    "Termination",
]

# DONE recalculated as % × TOTAL (no round-to-10).
PCT_DERIVED_DONE_EXACT = [
    "Fiber Optic",
]

PCT_DERIVED_DONE_ACTIVITIES = PCT_DERIVED_DONE_ROUND10 + PCT_DERIVED_DONE_EXACT

# Dashboard % = mean of location PERCENTAGE rows (not DONE÷TOTAL).
# INDUK: mean within the selected desa group (or all grouped locations).
# Other campuses: mean across all locations on that sheet.
LOCATION_MEAN_PCT_ACTIVITIES = [
    "Trunking",
    "Lay Cable",
    "Termination",
]

# Alias used by older call sites / UTP-AP helpers.
DONE_TOTAL_PCT_ACTIVITIES = TRUSTED_DONE_TOTAL_ACTIVITIES

# DONE / TOTAL counts (whole numbers, not decimals).
COUNTABLE_ACTIVITIES = [
    "Trunking",
    "Lay Cable",
    "Termination",
    "UTP Point",
    "AP Mounting",
    "Slab Coring (hole)",
    "Rack Installation (nos)",
    "MultiGE Switch",
    "Controller",
    "RFS",
]

# Equipment columns after Fiber Optic (Access Switch renamed → MultiGE Switch from Sep 15).
ACTIVE_EQUIPMENT = [
    "Controller",
    "MultiGE Switch",
    "Dist. Switch",
    "RFS",
]

# Campus average for these: read sheet TOTAL DONE / OVERALL TOTAL only (not location sums).
SUMMARY_ONLY_EQUIPMENT = [
    "Controller",
    "RFS",
]

# Map sheet header aliases → canonical ACTIVE_EQUIPMENT name.
EQUIPMENT_HEADER_ALIASES = {
    "controller": "Controller",
    "access switch": "MultiGE Switch",
    "multige switch": "MultiGE Switch",
    "multi ge switch": "MultiGE Switch",
    "multige": "MultiGE Switch",
    "dist. switch": "Dist. Switch",
    "dist switch": "Dist. Switch",
    "rfs": "RFS",
}

# All numeric columns shown in Excel-style daily tables.
TABLE_COLUMNS = ACTIVITIES + ACTIVE_EQUIPMENT

HISTORY_TAB_NAME = "Daily History"
HISTORY_GID = ""
HISTORY_COLUMNS = ["Date", "Campus", "Type", "Title", "Description", "Image_URLs"]

ISSUES_TAB_NAME = "Issue & Risk"
ISSUES_GID = ""
ISSUES_COLUMNS = ["No", "Issue_Risk", "Picture_URLs", "Action", "Status"]

WORK_PLAN_TAB_NAME = "Work Plan VS Actual"
WORK_PLAN_GID = "1480410166"
WORK_PLAN_COLUMNS = [
    "Date",
    "Duration",
    "Location",
    "Type_of_work",
    "Reported_changes",
]

DETAILS_TAB_NAME = "DETAILS"
DETAILS_GID = "1679878618"
DETAILS_COLUMNS = [
    "Campus",
    "Location",
    "Critical",
    "Remarks",
    "Progress",
]
CRITICAL_LEVELS = ["Not Critical", "Medium", "Critical"]

GANTT_TAB_NAME = "gantt"
GANTT_GID = "1898933869"
GANTT_META_COLUMNS = [
    "Location",
    "Blackout",
    "Remarks",
    "BAKI AP",
    "BAKI UTP",
    "BAKI FIBER",
    "stop",
    "start",
]

# Overtime claim sheets + RM/hour rates (Hari bekerja = Biasa / hari biasa).
# Kept in app_config so Streamlit Cloud redeploys keep app.py + rates in sync.
OT_PTD_TAB_NAME = "OT STAFF PTD"
OT_PTD_GID = "2051099566"
OT_PIC_TAB_NAME = "OT STAFF PIC"
OT_PIC_GID = "116665282"
OT_COLUMNS = [
    "No",
    "Tarikh",
    "Nama Staf",
    "No Telefon",
    "No IC",
    "Gred/Jawatan",
    "Jabatan/Unit",
    "Jenis Hari",
    "Masa mula",
    "Masa Tamat",
    "Jumlah",
    "Lokasi",
    "Skop kerja",
]
OT_RATES_RM_PER_HOUR = {
    "PTD": {
        "Biasa": 25.43,
        "Hujung Minggu": 28.25,
        "Cuti Umum": 47.46,
    },
    "PIC": {
        "Biasa": 18.00,
        "Hujung Minggu": 20.00,
        "Cuti Umum": 28.00,
    },
}

CACHE_TTL_SECONDS = 300

# INDUK-only: locations rolled up into these desa groups.
# (display_name, match_pattern) — name keywords / short labels in the sheet.
INDUK_LOCATION_GROUPS: list[tuple[str, str]] = [
    ("DS AMAN DAMAI (K01-10)", r"aman\s*damai"),
    ("K18 & K19", r"^k\s*1[89]\b"),
    ("DS Bakti Permai (H06,07,09,10, 16,17, 51)", r"bakti\s*permai"),
    ("DS Indah Kembara (L06,07,10,11,12)", r"indah\s*kembara"),
    ("DS Saujana (M03, 04)", r"saujana"),
    ("DS Tekun (M05, 06)", r"tekun"),
    ("DS Cahaya Harapan (F25, 26)", r"cahaya\s*harapan"),
    ("DS Cahaya Gemilang (F27)", r"cahaya\s*gemilang"),
    ("D18", r"^d\s*0*18\b"),
]

# Building codes → group when the location label has no desa keyword
# (e.g. new MultiGE-only rows: K9, K10, H10, L10, F27, D18).
INDUK_BUILDING_CODE_GROUPS: dict[str, str] = {
    **{f"K{i:02d}": "DS AMAN DAMAI (K01-10)" for i in range(1, 11)},
    "K18": "K18 & K19",
    "K19": "K18 & K19",
    **{
        code: "DS Bakti Permai (H06,07,09,10, 16,17, 51)"
        for code in ("H06", "H07", "H09", "H10", "H16", "H17", "H51")
    },
    **{
        code: "DS Indah Kembara (L06,07,10,11,12)"
        for code in ("L06", "L07", "L10", "L11", "L12")
    },
    "M03": "DS Saujana (M03, 04)",
    "M04": "DS Saujana (M03, 04)",
    "M05": "DS Tekun (M05, 06)",
    "M06": "DS Tekun (M05, 06)",
    "F25": "DS Cahaya Harapan (F25, 26)",
    "F26": "DS Cahaya Harapan (F25, 26)",
    "F27": "DS Cahaya Gemilang (F27)",
    "D18": "D18",
}


def induk_desa_dashboard_options() -> list[str]:
    """Dropdown labels for INDUK desa graphs."""
    return [f"INDUK - {name}" for name, _ in INDUK_LOCATION_GROUPS]


OVERALL_DASHBOARD_OPTION = "Overall"

# Cross-campus Overall view: sum DONE/TOTAL for these (show as fraction).
OVERALL_FRACTION_ACTIVITIES = [
    "UTP Point",
    "AP Mounting",
]


def dashboard_select_options() -> list[str]:
    """
    Dashboard dropdown: Overall (all campuses), all INDUK, each INDUK desa,
    then the other campuses.
    """
    options: list[str] = [OVERALL_DASHBOARD_OPTION, "INDUK - All"]
    options.extend(induk_desa_dashboard_options())
    for name in campus_sheet_names():
        if name == "INDUK":
            continue
        options.append(name)
    return options


def parse_dashboard_selection(selection: str) -> tuple[str, str | None]:
    """
    Return (campus_name, induk_desa_group_or_None).
    'Overall' = all campuses combined.
    Desa selections look like: 'INDUK - DS AMAN DAMAI (K01-10)'
    'INDUK - All' / plain 'INDUK' = whole campus (no desa filter).
    """
    text = str(selection or "").strip()
    if text.lower() in {"overall", "all campuses"}:
        return OVERALL_DASHBOARD_OPTION, None
    if text in {"INDUK", "INDUK - All", "INDUK - ALL"}:
        return "INDUK", None
    if text.startswith("INDUK - "):
        return "INDUK", text[len("INDUK - ") :]
    return text, None

