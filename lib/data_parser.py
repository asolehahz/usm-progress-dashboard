"""Parse the USM progress Google Sheet layout into structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from config import ACTIVITIES, CAMPUS_ICONS, INDUK_LOCATION_GROUPS, campus_sheet_names


@dataclass
class LocationProgress:
    location: str
    sheet_name: str
    by_date: dict[str, dict[str, float | None]] = field(default_factory=dict)

    @property
    def latest_date(self) -> str | None:
        dates = sorted(self.by_date.keys(), key=_parse_date_key)
        return dates[-1] if dates else None

    @property
    def overall_percent(self) -> float:
        """Average of latest activity percentages (ignoring empty values)."""
        latest = self.latest_date
        if not latest:
            return 0.0
        values = [v for v in self.by_date[latest].values() if v is not None]
        return sum(values) / len(values) if values else 0.0


def _parse_percent(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("%", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date_key(date_str: str):
    """Sort key for d/m/yyyy dates."""
    parts = re.split(r"[/-]", date_str.strip())
    if len(parts) == 3:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        return (y, m, d)
    return (9999, 12, 31)


def _looks_like_date(value) -> bool:
    text = str(value).strip()
    return bool(re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", text))


def _detect_header_row_index(df: pd.DataFrame) -> int:
    """Find the header row that contains at least one Trunking column."""
    max_scan = min(len(df), 6)
    for i in range(max_scan):
        row = df.iloc[i]
        if any(str(v).strip().replace("\r", "") == "Trunking" for v in row):
            return i
    return 1 if len(df) > 1 else 0


def _detect_location_progress_cols(header_row: pd.Series) -> tuple[int, int]:
    """Return (location_col, progress_col), with a safe fallback."""
    location_col = -1
    progress_col = -1
    for i, val in enumerate(header_row):
        text = str(val).strip().upper().replace("\r", "")
        if text == "LOCATION":
            location_col = i
        elif text == "PROGRESS":
            progress_col = i
    if location_col < 0 or progress_col < 0:
        return 1, 2
    return location_col, progress_col


def _find_date_blocks(header_row: pd.Series) -> list[tuple[int, list[int]]]:
    """
    Each date block is a 'Trunking' header followed by the 8 activity columns.
    Dates sit in a column to the left of Trunking (header 'Date' or a cell in data rows).
    """
    blocks: list[tuple[int, list[int]]] = []
    n = len(header_row)

    trunking_indices = [
        i for i in range(n) if str(header_row.iloc[i]).strip() == "Trunking"
    ]

    for ti in trunking_indices:
        act_cols = [c for c in range(ti, ti + len(ACTIVITIES)) if c < n]
        if len(act_cols) != len(ACTIVITIES):
            continue
        prev = str(header_row.iloc[ti - 1]).strip().lower().replace("\r", "") if ti > 0 else ""
        date_col = ti - 1 if prev == "date" else max(0, ti - 1)
        blocks.append((date_col, act_cols))

    return blocks


def _extract_dates_for_blocks(df: pd.DataFrame, blocks: list[tuple[int, list[int]]]) -> list[str]:
    """Find the date label for each block by scanning columns just before Trunking."""
    dates: list[str] = []
    prev_end = 0
    for date_col, act_cols in blocks:
        trunking_col = act_cols[0]
        found = ""
        search_from = max(prev_end, 0)
        search_to = trunking_col
        for col in range(search_from, search_to + 1):
            if col >= len(df.columns):
                break
            for row_idx in range(len(df)):
                val = str(df.iloc[row_idx, col]).strip()
                if _looks_like_date(val):
                    found = val
                    break
            if found:
                break
        if not found and date_col < len(df.columns):
            for row_idx in range(len(df)):
                val = str(df.iloc[row_idx, date_col]).strip()
                if _looks_like_date(val):
                    found = val
                    break
        dates.append(found)
        prev_end = act_cols[-1] + 1
    return dates


def parse_progress_sheet(
    df: pd.DataFrame, sheet_name: str = ""
) -> tuple[list[LocationProgress], pd.DataFrame]:
    """
    Parse raw CSV into location progress records and overall-by-date summary.
    """
    if df.empty or len(df) < 3:
        return [], pd.DataFrame()

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)

    locations: list[LocationProgress] = []
    skip_labels = {"TOTAL", "PERCENT", "PERCENTAGE", "TOTAL DONE", "OVERALL TOTAL", ""}

    row_idx = header_idx + 1
    while row_idx < len(df):
        location = str(df.iloc[row_idx, location_col]).strip()
        if not location or location in skip_labels:
            row_idx += 1
            continue
        if location.upper() in ("DONE", "PROGRESS"):
            row_idx += 1
            continue

        percent_row_idx = None
        for look in range(row_idx + 1, min(row_idx + 5, len(df))):
            if str(df.iloc[look, progress_col]).strip().upper() in {"PERCENT", "PERCENTAGE"}:
                percent_row_idx = look
                break
        if percent_row_idx is None:
            row_idx += 1
            continue

        prog = LocationProgress(location=location, sheet_name=sheet_name)
        percent_row = df.iloc[percent_row_idx]

        for block_i, (_, act_cols) in enumerate(blocks):
            date_label = block_dates[block_i] if block_i < len(block_dates) else f"Block {block_i + 1}"
            if not date_label:
                continue
            activity_map: dict[str, float | None] = {}
            for act_name, col_idx in zip(ACTIVITIES, act_cols):
                if col_idx < len(percent_row):
                    activity_map[act_name] = _parse_percent(percent_row.iloc[col_idx])
            if any(v is not None for v in activity_map.values()):
                prog.by_date[date_label] = activity_map

        if prog.by_date:
            locations.append(prog)
        row_idx = percent_row_idx + 1

    overall = get_campus_overall(df, sheet_name) if sheet_name else _parse_overall_summary(df)
    return locations, overall


def available_dates(df: pd.DataFrame) -> list[str]:
    """Extract all detected date blocks from one campus sheet (public API)."""
    if df is None or df.empty:
        return []
    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    blocks = _find_date_blocks(header_row)
    dates = _extract_dates_for_blocks(df, blocks)
    clean = [d for d in dates if d]
    return sorted(list(dict.fromkeys(clean)), key=_parse_date_key)


def _parse_number(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _induk_group_name(location: str) -> str | None:
    """Map an INDUK location label to one of the seven grouped names."""
    loc = location.strip()
    if not loc:
        return None
    normalized = re.sub(r"\s+", " ", loc).strip()
    upper = normalized.upper()
    for group_name, pattern in INDUK_LOCATION_GROUPS:
        if pattern.startswith("^"):
            short = re.sub(r"^DS\s+", "", upper).strip()
            if re.search(pattern, short, re.IGNORECASE):
                return group_name
        elif re.search(pattern, upper, re.IGNORECASE):
            return group_name
    return None


def _iter_location_blocks(
    df: pd.DataFrame,
    header_idx: int,
    location_col: int,
    progress_col: int,
) -> list[tuple[str, int, int, int]]:
    """Return (location_name, done_row, total_row, percent_row) for each site block."""
    skip_labels = {
        "TOTAL",
        "PERCENT",
        "PERCENTAGE",
        "TOTAL DONE",
        "OVERALL TOTAL",
        "AVERAGE PERCENTAGE",
        "AVERAGE PERCENT",
        "DONE",
        "PROGRESS",
        "",
    }
    blocks: list[tuple[str, int, int, int]] = []
    row_idx = header_idx + 1
    while row_idx < len(df):
        location = str(df.iloc[row_idx, location_col]).strip()
        progress = str(df.iloc[row_idx, progress_col]).strip().upper()
        if not location or location.upper() in skip_labels:
            row_idx += 1
            continue
        if progress != "DONE":
            row_idx += 1
            continue

        total_row = percent_row = None
        for look in range(row_idx + 1, min(row_idx + 5, len(df))):
            label = str(df.iloc[look, progress_col]).strip().upper()
            if label == "TOTAL":
                total_row = look
            elif label in {"PERCENT", "PERCENTAGE"}:
                percent_row = look
                break
        if total_row is None or percent_row is None:
            row_idx += 1
            continue
        blocks.append((location, row_idx, total_row, percent_row))
        row_idx = percent_row + 1
    return blocks


def _activity_values_from_row(row: pd.Series, act_cols: list[int]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for act_name, col_idx in zip(ACTIVITIES, act_cols):
        values[act_name] = _parse_number(row.iloc[col_idx]) if col_idx < len(row) else None
    return values


def _average_percent_from_totals(
    total_done: dict[str, float | None],
    overall_total: dict[str, float | None],
    trunking_percentages: list[float],
) -> dict[str, float | None]:
    """Trunking = average of location %; other activities = total done / overall total."""
    result: dict[str, float | None] = {}
    if trunking_percentages:
        result["Trunking"] = round(sum(trunking_percentages) / len(trunking_percentages), 2)
    else:
        done = total_done.get("Trunking")
        total = overall_total.get("Trunking")
        result["Trunking"] = round(done / total * 100, 2) if done is not None and total else None

    for act in ACTIVITIES[1:]:
        done = total_done.get(act)
        total = overall_total.get(act)
        if done is None or total is None or total == 0:
            result[act] = None
        else:
            result[act] = round(done / total * 100, 2)
    return result


def _compute_induk_overall_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """INDUK summary per date block using grouped DONE/TOTAL rollups."""
    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    records: list[dict] = []
    for block_i, (date_label, (_, act_cols)) in enumerate(zip(block_dates, blocks)):
        if not date_label:
            continue

        grouped_done: dict[str, dict[str, float]] = {}
        grouped_total: dict[str, dict[str, float]] = {}
        trunking_pcts: list[float] = []

        for location, done_row, total_row, percent_row in location_blocks:
            group = _induk_group_name(location)
            if not group:
                continue
            done_vals = _activity_values_from_row(df.iloc[done_row], act_cols)
            total_vals = _activity_values_from_row(df.iloc[total_row], act_cols)
            pct_vals = _activity_values_from_row(df.iloc[percent_row], act_cols)

            trunk_pct = _parse_percent(df.iloc[percent_row, act_cols[0]])
            if trunk_pct is not None:
                trunking_pcts.append(trunk_pct)

            for act in ACTIVITIES:
                done_num = done_vals.get(act)
                total_num = total_vals.get(act)
                if done_num is not None:
                    grouped_done.setdefault(group, {}).setdefault(act, 0.0)
                    grouped_done[group][act] += done_num
                if total_num is not None:
                    grouped_total.setdefault(group, {}).setdefault(act, 0.0)
                    grouped_total[group][act] += total_num

        campus_done: dict[str, float | None] = {act: 0.0 for act in ACTIVITIES}
        campus_total: dict[str, float | None] = {act: 0.0 for act in ACTIVITIES}
        for act in ACTIVITIES:
            done_sum = sum(group_vals.get(act, 0.0) for group_vals in grouped_done.values())
            total_sum = sum(group_vals.get(act, 0.0) for group_vals in grouped_total.values())
            campus_done[act] = done_sum if done_sum else None
            campus_total[act] = total_sum if total_sum else None

        record = {"Date": date_label}
        averages = _average_percent_from_totals(campus_done, campus_total, trunking_pcts)
        record.update(averages)
        if any(record.get(a) is not None for a in ACTIVITIES):
            records.append(record)

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records).drop_duplicates(subset=["Date"], keep="last")
    result["_sort"] = result["Date"].map(_parse_date_key)
    return result.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)


def _induk_grouped_snapshot(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    """Excel-like INDUK table with grouped locations for one date block."""
    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    block_i = next((i for i, d in enumerate(block_dates) if d == date_str), None)
    if block_i is None:
        return pd.DataFrame()

    _, act_cols = blocks[block_i]
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    grouped_done: dict[str, dict[str, float]] = {}
    grouped_total: dict[str, dict[str, float]] = {}
    grouped_trunk_pcts: dict[str, list[float]] = {}

    for location, done_row, total_row, percent_row in location_blocks:
        group = _induk_group_name(location)
        if not group:
            continue
        done_vals = _activity_values_from_row(df.iloc[done_row], act_cols)
        total_vals = _activity_values_from_row(df.iloc[total_row], act_cols)
        trunk_pct = _parse_percent(df.iloc[percent_row, act_cols[0]])
        if trunk_pct is not None:
            grouped_trunk_pcts.setdefault(group, []).append(trunk_pct)

        for act in ACTIVITIES:
            done_num = done_vals.get(act)
            total_num = total_vals.get(act)
            if done_num is not None:
                grouped_done.setdefault(group, {}).setdefault(act, 0.0)
                grouped_done[group][act] += done_num
            if total_num is not None:
                grouped_total.setdefault(group, {}).setdefault(act, 0.0)
                grouped_total[group][act] += total_num

    rows: list[dict[str, str]] = []
    for group_name, _ in INDUK_LOCATION_GROUPS:
        done_map = grouped_done.get(group_name, {})
        total_map = grouped_total.get(group_name, {})
        if not done_map and not total_map:
            continue

        done_row = {"Location": group_name, "Progress": "DONE"}
        total_row = {"Location": "", "Progress": "TOTAL"}
        pct_row = {"Location": "", "Progress": "PERCENTAGE"}

        trunk_pcts = grouped_trunk_pcts.get(group_name, [])
        averages = _average_percent_from_totals(
            {act: done_map.get(act) for act in ACTIVITIES},
            {act: total_map.get(act) for act in ACTIVITIES},
            trunk_pcts,
        )

        for act in ACTIVITIES:
            done_row[act] = _cell_display(done_map.get(act))
            total_row[act] = _cell_display(total_map.get(act))
            pct_val = averages.get(act)
            pct_row[act] = f"{pct_val:.2f}%" if pct_val is not None else "N/A"

        rows.extend([done_row, total_row, pct_row])

    campus_done = {
        act: sum(group_vals.get(act, 0.0) for group_vals in grouped_done.values()) or None
        for act in ACTIVITIES
    }
    campus_total = {
        act: sum(group_vals.get(act, 0.0) for group_vals in grouped_total.values()) or None
        for act in ACTIVITIES
    }
    all_trunk = [p for values in grouped_trunk_pcts.values() for p in values]
    campus_avg = _average_percent_from_totals(campus_done, campus_total, all_trunk)

    for label, values in [
        ("TOTAL DONE", campus_done),
        ("OVERALL TOTAL", campus_total),
        ("AVERAGE PERCENTAGE", campus_avg),
    ]:
        row = {"Location": label, "Progress": ""}
        for act in ACTIVITIES:
            val = values.get(act)
            if label == "AVERAGE PERCENTAGE":
                row[act] = f"{val:.2f}%" if val is not None else "N/A"
            else:
                row[act] = _cell_display(val)
        rows.append(row)

    return pd.DataFrame(rows)


def get_campus_overall(df: pd.DataFrame, campus: str) -> pd.DataFrame:
    """Campus AVERAGE PERCENTAGE series; INDUK uses grouped DONE/TOTAL logic."""
    if campus == "INDUK":
        return _compute_induk_overall_by_date(df)
    return _parse_overall_summary(df)


def _cell_display(value) -> str:
    """Blank cells are treated as not available / not applicable."""
    text = "" if value is None else str(value).strip()
    return text if text else "N/A"


def _row_label(df: pd.DataFrame, row_idx: int, location_col: int, progress_col: int) -> str:
    loc = str(df.iloc[row_idx, location_col]).strip().upper() if location_col < len(df.columns) else ""
    prog = str(df.iloc[row_idx, progress_col]).strip().upper() if progress_col < len(df.columns) else ""
    return loc or prog


def campus_date_snapshot(df: pd.DataFrame, date_str: str, campus: str = "") -> pd.DataFrame:
    """
    Excel-like snapshot for one campus date block.

    INDUK uses grouped locations. Other campuses show raw sheet rows.
    """
    if campus == "INDUK":
        return _induk_grouped_snapshot(df, date_str)

    if df is None or df.empty:
        return pd.DataFrame()

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)

    block_i = next((i for i, d in enumerate(block_dates) if d == date_str), None)
    if block_i is None:
        return pd.DataFrame()

    _, act_cols = blocks[block_i]
    rows: list[dict[str, str]] = []
    current_location = ""

    summary_labels = {"TOTAL DONE", "OVERALL TOTAL", "AVERAGE PERCENTAGE", "AVERAGE PERCENT"}
    progress_labels = {"DONE", "TOTAL", "PERCENT", "PERCENTAGE"}

    for r in range(header_idx + 1, len(df)):
        loc_val = str(df.iloc[r, location_col]).strip()
        progress = str(df.iloc[r, progress_col]).strip().upper()
        loc_upper = loc_val.upper()

        is_summary = loc_upper in summary_labels
        is_progress = progress in progress_labels
        if not is_summary and not is_progress:
            continue

        if progress == "DONE" and loc_val and loc_upper not in summary_labels:
            current_location = loc_val

        if is_summary:
            location_out = loc_val
            progress_out = ""
        else:
            location_out = current_location if progress == "DONE" else ""
            progress_out = "PERCENTAGE" if progress == "PERCENT" else progress

        row_data: dict[str, str] = {
            "Location": location_out,
            "Progress": progress_out,
        }
        for act_name, col_idx in zip(ACTIVITIES, act_cols):
            val = df.iloc[r, col_idx] if col_idx < len(df.columns) else ""
            row_data[act_name] = _cell_display(val)
        rows.append(row_data)

    return pd.DataFrame(rows)


__all__ = [
    "LocationProgress",
    "available_dates",
    "campus_date_snapshot",
    "get_campus_overall",
    "parse_progress_sheet",
    "sheet_overall_percent",
    "campus_sheets_summary",
    "aggregate_overall_by_date",
    "locations_activity_timeseries",
]


def _find_average_percentage_row(
    df: pd.DataFrame, location_col: int, progress_col: int
) -> int | None:
    """Locate the bottom AVERAGE PERCENTAGE summary row."""
    for row_idx in range(len(df) - 1, max(-1, len(df) - 40), -1):
        label = _row_label(df, row_idx, location_col, progress_col)
        if label in {"AVERAGE PERCENTAGE", "AVERAGE PERCENT"}:
            return row_idx
    return None


def _parse_overall_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Read campus AVERAGE PERCENTAGE values for each date block.

    Sheet rules (already computed in Excel):
    - Trunking average % = average of location Trunking percentages
    - Other activities = TOTAL DONE / OVERALL TOTAL
    Empty activity cells remain None (N/A).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    avg_row_idx = _find_average_percentage_row(df, location_col, progress_col)
    if avg_row_idx is None or not blocks:
        return pd.DataFrame()

    avg_row = df.iloc[avg_row_idx]
    records: list[dict] = []
    for date_label, (_, act_cols) in zip(block_dates, blocks):
        if not date_label:
            continue
        record: dict = {"Date": date_label}
        for act_name, col_idx in zip(ACTIVITIES, act_cols):
            record[act_name] = (
                _parse_percent(avg_row.iloc[col_idx]) if col_idx < len(avg_row) else None
            )
        if any(record.get(a) is not None for a in ACTIVITIES):
            records.append(record)

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records).drop_duplicates(subset=["Date"], keep="last")
    result["_sort"] = result["Date"].map(_parse_date_key)
    return result.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)


def sheet_overall_percent(locations: list[LocationProgress], overall: pd.DataFrame) -> float:
    """Overall % for one sheet tab — prefer summary row, else average locations."""
    if not overall.empty:
        latest = overall.iloc[-1]
        values = [latest.get(a) for a in ACTIVITIES if latest.get(a) is not None]
        if values:
            return round(sum(values) / len(values), 1)
    if not locations:
        return 0.0
    return round(sum(loc.overall_percent for loc in locations) / len(locations), 1)


def campus_sheets_summary(parsed: dict[str, dict]) -> dict[str, dict]:
    """Build dashboard summary for each campus sheet tab."""
    summary: dict[str, dict] = {}
    for name in campus_sheet_names():
        data = parsed.get(name, {})
        locations = data.get("locations", [])
        overall = data.get("overall", pd.DataFrame())
        summary[name] = {
            "icon": CAMPUS_ICONS.get(name, "🏫"),
            "overall": sheet_overall_percent(locations, overall),
            "count": len(INDUK_LOCATION_GROUPS) if name == "INDUK" else len(locations),
        }
    return summary


def aggregate_overall_by_date(parsed: dict[str, dict]) -> pd.DataFrame:
    """Average activity % across all campus sheets for each date."""
    buckets: dict[tuple[str, str], list[float]] = {}

    for name in campus_sheet_names():
        overall = parsed.get(name, {}).get("overall", pd.DataFrame())
        if overall is None or overall.empty:
            continue
        for _, row in overall.iterrows():
            date_str = row.get("Date")
            if not date_str:
                continue
            for act in ACTIVITIES:
                val = row.get(act)
                if val is not None:
                    buckets.setdefault((str(date_str), act), []).append(float(val))

    if not buckets:
        return pd.DataFrame()

    records = []
    dates = sorted({d for d, _ in buckets.keys()}, key=_parse_date_key)
    for date_str in dates:
        record: dict = {"Date": date_str}
        for act in ACTIVITIES:
            values = buckets.get((date_str, act), [])
            if values:
                record[act] = round(sum(values) / len(values), 2)
        if any(record.get(a) is not None for a in ACTIVITIES):
            records.append(record)

    return pd.DataFrame(records)


def locations_activity_timeseries(locations: list[LocationProgress]) -> pd.DataFrame:
    """Long-format DataFrame: Date, Activity, Percent (avg across locations in sheet)."""
    if not locations:
        return pd.DataFrame()

    date_activity_values: dict[tuple[str, str], list[float]] = {}

    for loc in locations:
        for date_str, activities in loc.by_date.items():
            for act, pct in activities.items():
                if pct is None:
                    continue
                key = (date_str, act)
                date_activity_values.setdefault(key, []).append(pct)

    rows = []
    for (date_str, act), values in date_activity_values.items():
        rows.append(
            {
                "Date": date_str,
                "Activity": act,
                "Percent": round(sum(values) / len(values), 2),
                "_sort": _parse_date_key(date_str),
            }
        )

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    return (
        result.sort_values(["_sort", "Activity"])
        .drop(columns=["_sort"])
        .reset_index(drop=True)
    )
