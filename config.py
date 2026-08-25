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
]

# Sheet DONE + TOTAL are trusted (fraction updates).
TRUSTED_DONE_TOTAL_ACTIVITIES = [
    "UTP Point",
    "AP Mounting",
]

# DONE recalculated as % × TOTAL, then rounded to nearest 10.
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

# Alias used by older call sites / UTP-AP helpers.
DONE_TOTAL_PCT_ACTIVITIES = TRUSTED_DONE_TOTAL_ACTIVITIES

# DONE / TOTAL counts (whole numbers, not decimals).
COUNTABLE_ACTIVITIES = [
    "Trunking",
    "Lay Cable",
    "Termination",
    "UTP Point",
    "AP Mounting",
]

ACTIVE_EQUIPMENT = [
    "Controller",
    "Access Switch",
    "Dist. Switch",
]

# All numeric columns shown in Excel-style daily tables.
TABLE_COLUMNS = ACTIVITIES + ACTIVE_EQUIPMENT

HISTORY_TAB_NAME = "Daily History"
HISTORY_GID = ""
HISTORY_COLUMNS = ["Date", "Campus", "Type", "Title", "Description", "Image_URLs"]

ISSUES_TAB_NAME = "Issue & Risk"
ISSUES_GID = ""
ISSUES_COLUMNS = ["No", "Issue_Risk", "Picture_URLs", "Action", "Status"]

CACHE_TTL_SECONDS = 300

# INDUK-only: locations rolled up into these desa groups.
# (display_name, match_pattern)
INDUK_LOCATION_GROUPS: list[tuple[str, str]] = [
    ("DS AMAN DAMAI (K01-08)", r"aman\s*damai"),
    ("K18 & K19", r"^k\s*1[89]\b"),
    ("DS Bakti Permai (H06,07,09, 16,17, 51)", r"bakti\s*permai"),
    ("DS Indah Kembara (L06,07,11,12)", r"indah\s*kembara"),
    ("DS Saujana (M03, 04)", r"saujana"),
    ("DS Tekun (M05, 06)", r"tekun"),
    ("DS Cahaya Harapan (F25, 26)", r"cahaya\s*harapan"),
]


def induk_desa_dashboard_options() -> list[str]:
    """Dropdown labels for INDUK desa graphs."""
    return [f"INDUK - {name}" for name, _ in INDUK_LOCATION_GROUPS]


def dashboard_select_options() -> list[str]:
    """
    Dashboard dropdown: INDUK desa options only (no plain INDUK),
    then the other campuses.
    """
    options: list[str] = []
    options.extend(induk_desa_dashboard_options())
    for name in campus_sheet_names():
        if name == "INDUK":
            continue
        options.append(name)
    return options


def parse_dashboard_selection(selection: str) -> tuple[str, str | None]:
    """
    Return (campus_name, induk_desa_group_or_None).
    Desa selections look like: 'INDUK - DS AMAN DAMAI (K01-08)'
    """
    if selection.startswith("INDUK - "):
        return "INDUK", selection[len("INDUK - ") :]
    return selection, None

