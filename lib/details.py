"""Location DETAILS — critical flag, remarks, and progress status from daily data."""

from __future__ import annotations

import pandas as pd

from config import ACTIVITIES, DETAILS_COLUMNS, campus_sheet_names
from lib.data_parser import (
    _detect_header_row_index,
    _detect_location_progress_cols,
    _extract_dates_for_blocks,
    _find_date_blocks,
    _iter_location_blocks,
    _location_block_values,
    _normalize_date_label,
    available_dates,
)


def parse_details(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse DETAILS tab into Campus / Location / Critical / Remarks / Progress."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=DETAILS_COLUMNS)

    header_row_idx = None
    for i in range(min(5, len(raw))):
        row = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "campus" in row and "location" in row:
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=DETAILS_COLUMNS)

    header = [str(v).strip() for v in raw.iloc[header_row_idx].tolist()]
    col_map: dict[str, int] = {}
    for idx, name in enumerate(header):
        low = name.lower()
        if low == "campus":
            col_map["Campus"] = idx
        elif low == "location":
            col_map["Location"] = idx
        elif "critical" in low:
            col_map["Critical"] = idx
        elif "remark" in low:
            col_map["Remarks"] = idx
        elif low == "progress":
            col_map["Progress"] = idx

    rows: list[dict[str, str]] = []
    for r in range(header_row_idx + 1, len(raw)):
        row = raw.iloc[r]
        campus = str(row.iloc[col_map["Campus"]]).strip() if "Campus" in col_map else ""
        location = (
            str(row.iloc[col_map["Location"]]).strip() if "Location" in col_map else ""
        )
        if not campus and not location:
            continue
        critical_raw = (
            str(row.iloc[col_map["Critical"]]).strip() if "Critical" in col_map else ""
        )
        rows.append(
            {
                "Campus": campus,
                "Location": location,
                "Critical": _normalize_critical(critical_raw),
                "Remarks": (
                    str(row.iloc[col_map["Remarks"]]).strip()
                    if "Remarks" in col_map
                    else ""
                ),
                "Progress": (
                    str(row.iloc[col_map["Progress"]]).strip()
                    if "Progress" in col_map
                    else ""
                ),
            }
        )
    return pd.DataFrame(rows, columns=DETAILS_COLUMNS)


def _normalize_critical(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"critical", "yes", "y", "true", "1", "c"}:
        return "Critical"
    return "Not Critical"


def list_campus_locations(parsed: dict[str, dict]) -> list[tuple[str, str]]:
    """All (campus, location) pairs from progress sheets, stable order."""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for campus in campus_sheet_names():
        raw_df = parsed.get(campus, {}).get("raw_df")
        if raw_df is None or getattr(raw_df, "empty", True):
            continue
        header_idx = _detect_header_row_index(raw_df)
        header_row = raw_df.iloc[header_idx]
        location_col, progress_col = _detect_location_progress_cols(header_row)
        for location, *_ in _iter_location_blocks(
            raw_df, header_idx, location_col, progress_col
        ):
            key = (campus, location)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
    return pairs


def location_progress_status(
    raw_df: pd.DataFrame, location: str, date_str: str | None = None
) -> str:
    """
    Completed / In Progress / Not Started from latest (or given) date PERCENTAGE.
    Completed = every activity % ≈ 100.
    Not Started = every available % is 0 (or no %).
    Otherwise In Progress.
    """
    if raw_df is None or getattr(raw_df, "empty", True):
        return "Not Started"

    dates = available_dates(raw_df, newest_first=True)
    if not dates:
        return "Not Started"
    target = date_str or dates[0]
    target_norm = _normalize_date_label(target)

    header_idx = _detect_header_row_index(raw_df)
    header_row = raw_df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(raw_df, blocks)
    location_blocks = _iter_location_blocks(
        raw_df, header_idx, location_col, progress_col
    )

    act_cols = None
    for date_label, (_, cols) in zip(block_dates, blocks):
        if date_label == target or _normalize_date_label(date_label) == target_norm:
            act_cols = cols
            break
    if act_cols is None:
        return "Not Started"

    loc_norm = str(location).strip().upper()
    match = next(
        (
            block
            for block in location_blocks
            if str(block[0]).strip().upper() == loc_norm
        ),
        None,
    )
    if match is None:
        return "Not Started"

    _loc, done_row, total_row, percent_row = match
    _done, _total, pct_vals = _location_block_values(
        raw_df, done_row, total_row, percent_row, act_cols
    )

    values = [pct_vals.get(act) for act in ACTIVITIES]
    present = [v for v in values if v is not None]
    if not present:
        return "Not Started"
    if all(abs(float(v) - 100.0) <= 0.05 for v in present) and len(present) == len(
        ACTIVITIES
    ):
        return "Completed"
    if all(abs(float(v)) <= 0.05 for v in present):
        return "Not Started"
    return "In Progress"


def merge_details_with_progress(
    details: pd.DataFrame,
    parsed: dict[str, dict],
    *,
    include_missing_locations: bool = True,
) -> pd.DataFrame:
    """
    Combine DETAILS sheet with live progress status.
    Optionally add locations that exist in progress sheets but not yet in DETAILS.
    """
    stored: dict[tuple[str, str], dict[str, str]] = {}
    if details is not None and not details.empty:
        for _, row in details.iterrows():
            campus = str(row.get("Campus", "") or "").strip()
            location = str(row.get("Location", "") or "").strip()
            if not campus or not location:
                continue
            stored[(campus, location)] = {
                "Critical": _normalize_critical(str(row.get("Critical", "") or "")),
                "Remarks": str(row.get("Remarks", "") or "").strip(),
            }

    pairs = list_campus_locations(parsed)
    if not include_missing_locations:
        pairs = [p for p in pairs if p in stored]
        # Keep any DETAILS-only rows too
        for key in stored:
            if key not in pairs:
                pairs.append(key)
    else:
        for key in stored:
            if key not in pairs:
                pairs.append(key)

    rows: list[dict[str, str]] = []
    for i, (campus, location) in enumerate(pairs, start=1):
        meta = stored.get((campus, location), {"Critical": "Not Critical", "Remarks": ""})
        raw_df = parsed.get(campus, {}).get("raw_df")
        status = location_progress_status(raw_df, location)
        rows.append(
            {
                "#": i,
                "Campus": campus,
                "Location": location,
                "Critical": meta["Critical"],
                "Remarks": meta["Remarks"],
                "Progress": status,
            }
        )
    return pd.DataFrame(rows)


def details_rows_for_sheet(view: pd.DataFrame) -> list[list[str]]:
    """Rows to write to DETAILS (header + data), sheet header names as user defined."""
    header = [
        "Campus",
        "Location",
        "Critical / Not Critical",
        "Remarks",
        "Progress",
    ]
    out = [header]
    if view is None or view.empty:
        return out
    for _, row in view.iterrows():
        out.append(
            [
                str(row.get("Campus", "") or ""),
                str(row.get("Location", "") or ""),
                str(row.get("Critical", "") or "Not Critical"),
                str(row.get("Remarks", "") or ""),
                str(row.get("Progress", "") or ""),
            ]
        )
    return out
