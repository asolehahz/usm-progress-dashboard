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

CAMPUS_ICONS = {
    "INDUK": "🏛️",
    "NIBONG TEBAL": "🏫",
    "BERTAM": "🌿",
    "BUKIT JAMBUL": "⛰️",
    "KUBANG KERIAN": "🏥",
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

HISTORY_TAB_NAME = "Daily History"
HISTORY_GID = ""
HISTORY_COLUMNS = ["Date", "Campus", "Type", "Title", "Description", "Image_URLs"]

CACHE_TTL_SECONDS = 300

# INDUK-only: locations rolled up into these display groups.
INDUK_LOCATION_GROUPS: list[tuple[str, str]] = [
    ("Desasiswa Aman Damai (K01-K08)", r"aman\s*damai"),
    ("K18 & K19", r"^k1[89]$"),
    ("Bakti Permai", r"bakti\s*permai"),
    ("Indah Kembara", r"indah\s*kembara"),
    ("Saujana", r"saujana"),
    ("Tekun", r"tekun"),
    ("Cahaya Harapan", r"cahaya\s*harapan"),
]
