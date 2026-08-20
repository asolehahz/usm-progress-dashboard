"""Parse the USM progress Google Sheet layout into structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from config import ACTIVITIES, CAMPUS_ICONS, campus_sheet_names


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


def _find_date_blocks(header_row: pd.Series) -> list[tuple[int, list[int]]]:
    """
    Return list of (date_col_index, [activity_col_indices]) for each date block.
    Each block starts at a 'Trunking' header column; the first block is preceded by 'Date'.
    """
    blocks: list[tuple[int, list[int]]] = []
    n = len(header_row)

    trunking_indices = [
        i for i in range(n) if str(header_row.iloc[i]).strip() == "Trunking"
    ]

    for ti in trunking_indices:
        prev = str(header_row.iloc[ti - 1]).strip().lower() if ti > 0 else ""
        if prev == "date":
            date_col = ti - 1
            # PERCENT row: first activity is on the Trunking column (ti), not ti+1
            act_cols = list(range(ti, ti + len(ACTIVITIES)))
        else:
            date_col = ti
            act_cols = list(range(ti + 2, ti + 2 + len(ACTIVITIES)))
        act_cols = [c for c in act_cols if c < n]
        if len(act_cols) == len(ACTIVITIES):
            blocks.append((date_col, act_cols))

    return blocks


def _extract_dates_for_blocks(df: pd.DataFrame, blocks: list[tuple[int, list[int]]]) -> list[str]:
    """Find date labels for each block from DONE rows."""
    dates: list[str] = []
    for date_col, _ in blocks:
        found = ""
        for row_idx in range(len(df)):
            if date_col >= len(df.columns):
                break
            val = str(df.iloc[row_idx, date_col]).strip()
            if _looks_like_date(val):
                found = val
                break
        dates.append(found)
    return dates


def parse_progress_sheet(
    df: pd.DataFrame, sheet_name: str = ""
) -> tuple[list[LocationProgress], pd.DataFrame]:
    """
    Parse raw CSV into location progress records and overall-by-date summary.
    """
    if df.empty or len(df) < 3:
        return [], pd.DataFrame()

    header_row = df.iloc[1]
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)

    locations: list[LocationProgress] = []
    skip_labels = {"TOTAL", "PERCENT", "PERCENTAGE", "TOTAL DONE", "OVERALL TOTAL", ""}

    row_idx = 2
    while row_idx < len(df):
        location = str(df.iloc[row_idx, 1]).strip()
        if not location or location in skip_labels:
            row_idx += 1
            continue
        if location.upper() in ("DONE", "PROGRESS"):
            row_idx += 1
            continue

        percent_row_idx = row_idx + 2
        if percent_row_idx >= len(df):
            break
        percent_label = str(df.iloc[percent_row_idx, 2]).strip().upper()
        if percent_label != "PERCENT":
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
        row_idx += 3

    overall = _parse_overall_summary(df)
    return locations, overall


def _parse_overall_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Parse bottom summary table: date in col 4, activity % in cols 5–12."""
    records: list[dict] = []
    for row_idx in range(len(df) - 1, max(0, len(df) - 30), -1):
        row = df.iloc[row_idx]
        date_val = str(row.iloc[4]).strip() if len(row) > 4 else ""
        if not _looks_like_date(date_val):
            continue
        record = {"Date": date_val}
        for i, act in enumerate(ACTIVITIES):
            col = 5 + i
            if col < len(row):
                record[act] = _parse_percent(row.iloc[col])
        if any(record.get(a) is not None for a in ACTIVITIES):
            records.append(record)

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records).drop_duplicates(subset=["Date"])
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
            "count": len(locations),
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
