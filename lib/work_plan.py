"""Work Plan vs Actual — read plan sheet and fill reported changes from progress data."""

from __future__ import annotations

import re

import pandas as pd

from config import ACTIVITIES, WORK_PLAN_COLUMNS
from lib.data_parser import (
    _normalize_date_label,
    _parse_date_key,
    available_dates,
    location_changes_by_building,
)


def _plan_location_code(location: str) -> str:
    """Extract building code from plan label, e.g. 'K05 - DS Aman Damai' → K05."""
    text = str(location or "").strip().upper()
    match = re.search(r"\b([A-Z]\d{2})\b", text)
    if match:
        return match.group(1)
    match = re.match(r"^([A-Z]\d{1,2})\b", text)
    return match.group(1) if match else text[:12]


def work_type_to_activities(work_type: str) -> list[str]:
    """Map free-text plan work type to progress activity columns."""
    key = str(work_type or "").strip().lower()
    if not key:
        return list(ACTIVITIES)
    if "cabling" in key and "trunking" in key:
        return ["Trunking", "Lay Cable", "Termination"]
    if "trunking" in key:
        return ["Trunking"]
    if "cabling" in key or "lay cable" in key:
        return ["Lay Cable", "Termination"]
    if "termination" in key:
        return ["Termination"]
    if "utp" in key:
        return ["UTP Point"]
    if "ap" in key and "mount" in key:
        return ["AP Mounting"]
    if "fiber" in key:
        return ["Fiber Optic"]
    if "slab" in key or "coring" in key:
        return ["Slab Coring (hole)"]
    if "rack" in key:
        return ["Rack Installation (nos)"]
    return list(ACTIVITIES)


def parse_work_plan(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse Work Plan VS Actual tab into normalized columns."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=WORK_PLAN_COLUMNS)

    header_row_idx = None
    for i in range(min(5, len(raw))):
        row = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "date" in row and "location" in row:
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=WORK_PLAN_COLUMNS)

    header = [str(v).strip() for v in raw.iloc[header_row_idx].tolist()]
    col_map: dict[str, int] = {}
    for idx, name in enumerate(header):
        low = name.lower()
        if low == "date":
            col_map["Date"] = idx
        elif low == "duration":
            col_map["Duration"] = idx
        elif low == "location":
            col_map["Location"] = idx
        elif "type" in low and "work" in low:
            col_map["Type_of_work"] = idx
        elif "reported" in low and "change" in low:
            col_map["Reported_changes"] = idx

    rows: list[dict[str, str]] = []
    for r in range(header_row_idx + 1, len(raw)):
        row = raw.iloc[r]
        date_val = str(row.iloc[col_map["Date"]]).strip() if "Date" in col_map else ""
        loc_val = str(row.iloc[col_map["Location"]]).strip() if "Location" in col_map else ""
        if not date_val or not loc_val:
            continue
        rows.append(
            {
                "Date": _normalize_date_label(date_val),
                "Duration": (
                    str(row.iloc[col_map["Duration"]]).strip()
                    if "Duration" in col_map
                    else ""
                ),
                "Location": loc_val,
                "Type_of_work": (
                    str(row.iloc[col_map["Type_of_work"]]).strip()
                    if "Type_of_work" in col_map
                    else ""
                ),
                "Reported_changes": (
                    str(row.iloc[col_map["Reported_changes"]]).strip()
                    if "Reported_changes" in col_map
                    else ""
                ),
            }
        )

    return pd.DataFrame(rows, columns=WORK_PLAN_COLUMNS)


def work_plan_dates(plan: pd.DataFrame, *, newest_first: bool = True) -> list[str]:
    if plan is None or plan.empty:
        return []
    unique = list(dict.fromkeys(str(d).strip() for d in plan["Date"] if str(d).strip()))
    ordered = sorted(unique, key=_parse_date_key)
    return list(reversed(ordered)) if newest_first else ordered


def _previous_progress_date(induk_df: pd.DataFrame, selected: str) -> str | None:
    dates = available_dates(induk_df, newest_first=False)
    if not dates or not selected:
        return None
    selected_norm = _normalize_date_label(selected)
    idx = next(
        (
            i
            for i, d in enumerate(dates)
            if d == selected or _normalize_date_label(d) == selected_norm
        ),
        None,
    )
    if idx is None or idx == 0:
        return None
    return dates[idx - 1]


def _change_lookup_by_building(
    induk_df: pd.DataFrame, prev_date: str, latest_date: str
) -> dict[str, dict[str, str]]:
    return location_changes_by_building(induk_df, prev_date, latest_date)


def build_work_plan_view(
    plan: pd.DataFrame,
    induk_df: pd.DataFrame,
    selected_date: str,
) -> tuple[pd.DataFrame, str | None]:
    """
    Filter plan rows for selected_date and fill Reported changes from INDUK progress.

    Returns (display_table, previous_date_used).
    """
    empty = pd.DataFrame(
        columns=["#", "Duration", "Location", "Type of work", "Reported changes"]
    )
    if plan is None or plan.empty or not selected_date:
        return empty, None

    selected_norm = _normalize_date_label(selected_date)
    day_rows = plan[
        plan["Date"].apply(
            lambda d: d == selected_date or _normalize_date_label(d) == selected_norm
        )
    ].copy()
    if day_rows.empty:
        return empty, None

    prev_date = _previous_progress_date(induk_df, selected_date)
    changes_by_code: dict[str, dict[str, str]] = {}
    if induk_df is not None and not induk_df.empty and prev_date:
        progress_dates = {
            _normalize_date_label(d) for d in available_dates(induk_df, newest_first=False)
        }
        if selected_norm in progress_dates:
            changes_by_code = _change_lookup_by_building(
                induk_df, prev_date, selected_date
            )

    out_rows: list[dict[str, str]] = []
    for _, row in day_rows.iterrows():
        code = _plan_location_code(row["Location"]).upper()
        planned_acts = work_type_to_activities(row["Type_of_work"])
        reported = str(row.get("Reported_changes", "") or "").strip()

        if not reported:
            loc_changes = changes_by_code.get(code, {})
            if not prev_date:
                reported = "No earlier progress date to compare"
            elif not loc_changes:
                reported = "No change"
            else:
                matched = [
                    loc_changes[act]
                    for act in planned_acts
                    if act in loc_changes
                ]
                if matched:
                    reported = "; ".join(matched)
                elif loc_changes:
                    # Other work moved at this location — still show it.
                    reported = "; ".join(loc_changes[a] for a in sorted(loc_changes))
                else:
                    reported = "No change"

        out_rows.append(
            {
                "Duration": str(row.get("Duration", "") or "").strip() or "—",
                "Location": str(row.get("Location", "") or "").strip(),
                "Type of work": str(row.get("Type_of_work", "") or "").strip(),
                "Reported changes": reported,
            }
        )

    result = pd.DataFrame(out_rows)
    if not result.empty:
        result.insert(0, "#", range(1, len(result) + 1))

    return result, prev_date
