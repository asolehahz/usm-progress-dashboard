"""Gantt schedule tab + current progress from daily location data."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app_config import (
    ACTIVITIES,
    FRACTION_METRIC_ACTIVITIES,
    GANTT_META_COLUMNS,
)
from lib.data_parser import (
    _location_block_values,
    _detect_header_row_index,
    _detect_location_progress_cols,
    _extract_dates_for_blocks,
    _find_date_blocks,
    _iter_location_blocks,
    _normalize_date_label,
    _parse_date_parts,
    available_dates,
    location_recalculated_percentages,
)
from lib.work_plan import _location_match_keys


def parse_gantt(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse gantt tab into metadata rows + timeline date column labels.

    Sheet layout: header row with Location / Blackout / Remarks / stop / start / dates…
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=GANTT_META_COLUMNS), []

    header_row_idx = None
    for i in range(min(8, len(raw))):
        row = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "location" in row:
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=GANTT_META_COLUMNS), []

    header = [str(v).strip() for v in raw.iloc[header_row_idx].tolist()]
    col_map: dict[str, int] = {}
    date_cols: list[str] = []
    for idx, name in enumerate(header):
        low = name.lower()
        if low == "location":
            col_map["Location"] = idx
        elif low == "blackout":
            col_map["Blackout"] = idx
        elif low == "remarks":
            col_map["Remarks"] = idx
        elif low == "stop":
            col_map["Blackout Start"] = idx
        elif low == "start":
            col_map["Blackout End"] = idx

    meta_end = max(col_map.values(), default=-1) + 1
    for idx in range(meta_end, len(header)):
        name = str(header[idx]).strip()
        if name:
            date_cols.append(name)

    rows: list[dict[str, str]] = []
    for r in range(header_row_idx + 1, len(raw)):
        row = raw.iloc[r]
        location = (
            str(row.iloc[col_map["Location"]]).strip() if "Location" in col_map else ""
        )
        if not location:
            continue
        meta = {
            "Location": location,
            "Blackout": (
                str(row.iloc[col_map["Blackout"]]).strip()
                if "Blackout" in col_map
                else ""
            ),
            "Remarks": (
                str(row.iloc[col_map["Remarks"]]).strip() if "Remarks" in col_map else ""
            ),
            "Blackout Start": (
                str(row.iloc[col_map["Blackout Start"]]).strip()
                if "Blackout Start" in col_map
                else ""
            ),
            "Blackout End": (
                str(row.iloc[col_map["Blackout End"]]).strip()
                if "Blackout End" in col_map
                else ""
            ),
        }
        for date_label in date_cols:
            col_idx = header.index(date_label) if date_label in header else None
            if col_idx is None or col_idx >= len(row):
                meta[date_label] = ""
            else:
                meta[date_label] = str(row.iloc[col_idx]).strip()
        rows.append(meta)

    if not rows:
        return pd.DataFrame(columns=GANTT_META_COLUMNS), date_cols
    return pd.DataFrame(rows), date_cols


def _parse_sheet_date(value: str) -> datetime | None:
    parts = _parse_date_parts(value)
    if not parts:
        return None
    y, m, d = parts
    try:
        return datetime(y, m, d)
    except ValueError:
        return None


def resolve_progress_location(
    gantt_location: str, progress_locations: list[str]
) -> str | None:
    """Match a gantt row label to a progress-sheet location name."""
    gantt_keys = set(_location_match_keys(gantt_location))
    if not gantt_keys:
        return None
    for ploc in progress_locations:
        if gantt_keys & set(_location_match_keys(ploc)):
            return ploc
    return None


def _progress_location_names(raw_df: pd.DataFrame) -> list[str]:
    header_idx = _detect_header_row_index(raw_df)
    header_row = raw_df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _iter_location_blocks(raw_df, header_idx, location_col, progress_col)
    return [loc for loc, *_ in blocks]


def _location_done_total(
    raw_df: pd.DataFrame, date_str: str, location: str
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    header_idx = _detect_header_row_index(raw_df)
    header_row = raw_df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(raw_df, blocks)
    date_norm = _normalize_date_label(date_str)
    block_i = next(
        (
            i
            for i, d in enumerate(block_dates)
            if d == date_str or _normalize_date_label(d) == date_norm
        ),
        None,
    )
    if block_i is None:
        return {}, {}
    _, act_cols = blocks[block_i]
    location_blocks = _iter_location_blocks(
        raw_df, header_idx, location_col, progress_col
    )
    loc_norm = str(location).strip().upper()
    match = next(
        (b for b in location_blocks if str(b[0]).strip().upper() == loc_norm),
        None,
    )
    if match is None:
        return {}, {}
    _, done_row, total_row, percent_row = match
    done, total, _pct = _location_block_values(
        raw_df, done_row, total_row, percent_row, act_cols
    )
    return done, total


def _format_progress_cell(
    act: str,
    pct: float | None,
    done: float | None,
    total: float | None,
) -> str:
    if act in FRACTION_METRIC_ACTIVITIES:
        if done is not None and total is not None:
            return f"{int(round(done))}/{int(round(total))}"
        return "N/A"
    if pct is not None:
        return f"{pct:.1f}%"
    return "N/A"


def build_current_progress_table(
    raw_df: pd.DataFrame,
    schedule: pd.DataFrame,
    *,
    latest_date: str,
) -> pd.DataFrame:
    """Per-location current progress for gantt buildings (recalculated daily values)."""
    progress_names = _progress_location_names(raw_df)
    rows: list[dict[str, str]] = []
    for _, gantt_row in schedule.iterrows():
        gantt_loc = str(gantt_row.get("Location", "") or "").strip()
        if not gantt_loc:
            continue
        matched = resolve_progress_location(gantt_loc, progress_names)
        row: dict[str, str] = {
            "Location": gantt_loc,
            "Blackout": str(gantt_row.get("Blackout", "") or ""),
            "Remarks": str(gantt_row.get("Remarks", "") or ""),
            "Progress location": matched or "—",
        }
        if matched:
            pct_map = location_recalculated_percentages(raw_df, latest_date, matched) or {}
            done_map, total_map = _location_done_total(raw_df, latest_date, matched)
            for act in ACTIVITIES:
                row[act] = _format_progress_cell(
                    act,
                    pct_map.get(act),
                    done_map.get(act),
                    total_map.get(act),
                )
        else:
            for act in ACTIVITIES:
                row[act] = "N/A"
        rows.append(row)
    return pd.DataFrame(rows)


def gantt_locations_overall(
    raw_df: pd.DataFrame,
    schedule: pd.DataFrame,
    *,
    latest_date: str,
) -> pd.DataFrame:
    """
    One-row overall summary for gantt locations (dashboard-style aggregation).

    % activities: mean of location percentages.
    UTP/AP: sum DONE / sum TOTAL across matched locations.
    """
    progress_names = _progress_location_names(raw_df)
    pct_sums: dict[str, list[float]] = {act: [] for act in ACTIVITIES}
    done_sums: dict[str, float] = {act: 0.0 for act in FRACTION_METRIC_ACTIVITIES}
    total_sums: dict[str, float] = {act: 0.0 for act in FRACTION_METRIC_ACTIVITIES}

    matched_count = 0
    for _, gantt_row in schedule.iterrows():
        gantt_loc = str(gantt_row.get("Location", "") or "").strip()
        matched = resolve_progress_location(gantt_loc, progress_names)
        if not matched:
            continue
        matched_count += 1
        pct_map = location_recalculated_percentages(raw_df, latest_date, matched) or {}
        done_map, total_map = _location_done_total(raw_df, latest_date, matched)
        for act in ACTIVITIES:
            if act in FRACTION_METRIC_ACTIVITIES:
                d, t = done_map.get(act), total_map.get(act)
                if d is not None and t is not None:
                    done_sums[act] += float(d)
                    total_sums[act] += float(t)
            else:
                pct = pct_map.get(act)
                if pct is not None:
                    pct_sums[act].append(float(pct))

    if matched_count == 0:
        return pd.DataFrame()

    record: dict[str, object] = {"Date": latest_date, "Locations": matched_count}
    for act in ACTIVITIES:
        if act in FRACTION_METRIC_ACTIVITIES:
            t = total_sums[act]
            record[f"{act}__done"] = done_sums[act]
            record[f"{act}__total"] = t
            record[act] = round(done_sums[act] / t * 100, 2) if t else None
        else:
            vals = pct_sums[act]
            record[act] = round(sum(vals) / len(vals), 2) if vals else None
    return pd.DataFrame([record])


def blackout_timeline_figure(schedule: pd.DataFrame) -> go.Figure | None:
    """Plotly timeline of blackout windows (stop → end dates)."""
    bars: list[dict[str, object]] = []
    for _, row in schedule.iterrows():
        loc = str(row.get("Location", "") or "").strip()
        if not loc or str(row.get("Blackout", "")).strip().lower() != "yes":
            continue
        start = _parse_sheet_date(str(row.get("Blackout Start", "") or ""))
        end = _parse_sheet_date(str(row.get("Blackout End", "") or ""))
        if not start or not end:
            continue
        if end < start:
            start, end = end, start
        bars.append({"Location": loc, "Start": start, "End": end, "Blackout": "Yes"})
    if not bars:
        return None

    timeline = pd.DataFrame(bars)
    fig = px.timeline(
        timeline,
        x_start="Start",
        x_end="End",
        y="Location",
        color="Blackout",
        color_discrete_map={"Yes": "#F7941D"},
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        title="Blackout periods",
        height=max(320, 28 * len(bars)),
        xaxis_title="Date",
        margin=dict(l=180, r=20, t=50, b=40),
        showlegend=False,
    )
    return fig


def schedule_timeline_table(schedule: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """Metadata + timeline columns for display."""
    cols = [c for c in GANTT_META_COLUMNS if c in schedule.columns]
    cols.extend([c for c in date_cols if c in schedule.columns])
    return schedule[cols].copy() if cols else schedule.copy()
