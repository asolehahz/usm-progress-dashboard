"""Gantt schedule tab + current progress from daily location data."""

from __future__ import annotations

import re
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


def parse_gantt(
    raw: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    """
    Parse gantt tab into metadata rows + timeline date column labels.

    Returns (schedule, date_cols, meta) where meta has header_row_idx,
    column_indices (display col → sheet col), sheet_row_indices.
    """
    empty_meta: dict[str, object] = {
        "header_row_idx": 0,
        "column_indices": {},
        "sheet_row_indices": [],
    }
    if raw is None or raw.empty:
        return pd.DataFrame(columns=GANTT_META_COLUMNS), [], empty_meta

    header_row_idx = None
    for i in range(min(8, len(raw))):
        row = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "location" in row:
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=GANTT_META_COLUMNS), [], empty_meta

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
        elif low in {"baki ap", "baki_ap"}:
            col_map["BAKI AP"] = idx
        elif low in {"baki utp", "baki_utp"}:
            col_map["BAKI UTP"] = idx
        elif low in {"baki fiber", "baki fibre", "baki_fiber"}:
            col_map["BAKI FIBER"] = idx
        elif low == "stop":
            col_map["stop"] = idx
        elif low == "start":
            col_map["start"] = idx

    meta_end = max(col_map.values(), default=-1) + 1
    for idx in range(meta_end, len(header)):
        name = str(header[idx]).strip()
        if name:
            date_cols.append(name)

    rows: list[dict[str, str]] = []
    sheet_row_indices: list[int] = []
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
            "BAKI AP": (
                str(row.iloc[col_map["BAKI AP"]]).strip() if "BAKI AP" in col_map else ""
            ),
            "BAKI UTP": (
                str(row.iloc[col_map["BAKI UTP"]]).strip()
                if "BAKI UTP" in col_map
                else ""
            ),
            "BAKI FIBER": (
                str(row.iloc[col_map["BAKI FIBER"]]).strip()
                if "BAKI FIBER" in col_map
                else ""
            ),
            "stop": (
                str(row.iloc[col_map["stop"]]).strip() if "stop" in col_map else ""
            ),
            "start": (
                str(row.iloc[col_map["start"]]).strip() if "start" in col_map else ""
            ),
        }
        for date_label in date_cols:
            col_idx = header.index(date_label) if date_label in header else None
            if col_idx is None or col_idx >= len(row):
                meta[date_label] = ""
            else:
                meta[date_label] = str(row.iloc[col_idx]).strip()
        rows.append(meta)
        sheet_row_indices.append(r)

    column_indices: dict[str, int] = {}
    for display_name, key in (
        ("Location", "Location"),
        ("Blackout", "Blackout"),
        ("Remarks", "Remarks"),
        ("BAKI AP", "BAKI AP"),
        ("BAKI UTP", "BAKI UTP"),
        ("BAKI FIBER", "BAKI FIBER"),
        ("stop", "stop"),
        ("start", "start"),
    ):
        if key in col_map:
            column_indices[display_name] = col_map[key]
    for date_label in date_cols:
        if date_label in header:
            column_indices[date_label] = header.index(date_label)

    meta_out: dict[str, object] = {
        "header_row_idx": header_row_idx,
        "column_indices": column_indices,
        "sheet_row_indices": sheet_row_indices,
    }

    if not rows:
        return pd.DataFrame(columns=GANTT_META_COLUMNS), date_cols, meta_out
    return pd.DataFrame(rows), date_cols, meta_out


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


def fill_gantt_baki_columns(
    schedule: pd.DataFrame,
    raw_df: pd.DataFrame | None,
    latest_date: str,
) -> pd.DataFrame:
    """
    Fill BAKI AP / BAKI UTP / BAKI FIBER from latest daily progress.

    BAKI AP    = AP Mounting TOTAL − DONE
    BAKI UTP   = UTP Point TOTAL − DONE
    BAKI FIBER = 100 − latest Fiber Optic %
    """
    out = schedule.copy()
    for col in ("BAKI AP", "BAKI UTP", "BAKI FIBER"):
        if col not in out.columns:
            out[col] = ""

    if raw_df is None or getattr(raw_df, "empty", True) or not str(latest_date).strip():
        return out

    progress_names = _progress_location_names(raw_df)
    ap_act = "AP Mounting"
    utp_act = "UTP Point"
    fiber_act = "Fiber Optic"

    for idx, row in out.iterrows():
        gantt_loc = str(row.get("Location", "") or "").strip()
        matched = resolve_progress_location(gantt_loc, progress_names)
        if not matched:
            out.at[idx, "BAKI AP"] = "N/A"
            out.at[idx, "BAKI UTP"] = "N/A"
            out.at[idx, "BAKI FIBER"] = "N/A"
            continue

        done_map, total_map = _location_done_total(raw_df, latest_date, matched)
        pct_map = location_recalculated_percentages(raw_df, latest_date, matched) or {}

        ap_done, ap_total = done_map.get(ap_act), total_map.get(ap_act)
        if ap_done is not None and ap_total is not None:
            out.at[idx, "BAKI AP"] = str(max(0, int(round(float(ap_total) - float(ap_done)))))
        else:
            out.at[idx, "BAKI AP"] = "N/A"

        utp_done, utp_total = done_map.get(utp_act), total_map.get(utp_act)
        if utp_done is not None and utp_total is not None:
            out.at[idx, "BAKI UTP"] = str(max(0, int(round(float(utp_total) - float(utp_done)))))
        else:
            out.at[idx, "BAKI UTP"] = "N/A"

        fiber_pct = pct_map.get(fiber_act)
        if fiber_pct is not None:
            remaining = max(0.0, min(100.0, 100.0 - float(fiber_pct)))
            out.at[idx, "BAKI FIBER"] = f"{remaining:.1f}%"
        else:
            out.at[idx, "BAKI FIBER"] = "N/A"

    return out


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
        start = _parse_sheet_date(str(row.get("stop", "") or row.get("Blackout Start", "") or ""))
        end = _parse_sheet_date(str(row.get("start", "") or row.get("Blackout End", "") or ""))
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
        color_discrete_map={"Yes": "#EA9999"},
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


def _parse_gantt_column_date(label: str, *, year: int = 2026) -> datetime | None:
    """Parse timeline header labels like 01-Sep or 2-Oct."""
    text = str(label or "").strip()
    m = re.match(r"^(\d{1,2})[- ](\w{3,})$", text, re.IGNORECASE)
    if not m:
        return None
    day = int(m.group(1))
    month_str = m.group(2).lower()[:3]
    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    month = months.get(month_str)
    if not month:
        return None
    col_year = year if month >= 9 else year + 1
    try:
        return datetime(col_year, month, day)
    except ValueError:
        return None


def synthetic_blackout_colors(
    schedule: pd.DataFrame,
    date_cols: list[str],
    *,
    sheet_row_indices: list[int],
    column_indices: dict[str, int],
    fill: str = "#EA9999",
) -> dict[tuple[int, int], str]:
    """Fallback red shading for blackout windows when sheet colours are unavailable."""
    colors: dict[tuple[int, int], str] = {}
    for df_i, sheet_row in enumerate(sheet_row_indices):
        if df_i >= len(schedule):
            break
        row = schedule.iloc[df_i]
        if str(row.get("Blackout", "")).strip().lower() != "yes":
            continue
        start = _parse_sheet_date(str(row.get("stop", "") or row.get("Blackout Start", "") or ""))
        end = _parse_sheet_date(str(row.get("start", "") or row.get("Blackout End", "") or ""))
        if not start or not end:
            continue
        if end < start:
            start, end = end, start
        for date_label in date_cols:
            col_date = _parse_gantt_column_date(date_label)
            sheet_col = column_indices.get(date_label)
            if col_date is None or sheet_col is None:
                continue
            if start.date() <= col_date.date() <= end.date():
                colors[(sheet_row, sheet_col)] = fill
    return colors


def _text_color_for_bg(hex_color: str) -> str:
    text = hex_color.lstrip("#")
    if len(text) != 6:
        return "#000000"
    r, g, b = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#FFFFFF" if luminance < 0.55 else "#000000"


def style_gantt_schedule(
    df: pd.DataFrame,
    colors: dict[tuple[int, int], str],
    *,
    sheet_row_indices: list[int],
    column_indices: dict[str, int],
):
    """Apply Google Sheet background colours to the schedule table."""
    if df is None or df.empty or not colors:
        return df

    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    index_list = list(df.index)
    for df_i, idx in enumerate(index_list):
        if df_i >= len(sheet_row_indices):
            break
        sheet_row = sheet_row_indices[df_i]
        for col in df.columns:
            sheet_col = column_indices.get(col)
            if sheet_col is None:
                continue
            hex_color = colors.get((sheet_row, sheet_col))
            if not hex_color:
                continue
            text = _text_color_for_bg(hex_color)
            styles.at[idx, col] = f"background-color: {hex_color}; color: {text}"

    return df.style.apply(lambda _: styles, axis=None)


def schedule_timeline_table(schedule: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """Metadata + timeline columns for display."""
    cols = [c for c in GANTT_META_COLUMNS if c in schedule.columns]
    cols.extend([c for c in date_cols if c in schedule.columns])
    return schedule[cols].copy() if cols else schedule.copy()
