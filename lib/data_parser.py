"""Parse the USM progress Google Sheet layout into structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from app_config import (
    ACTIVITIES,
    ACTIVE_EQUIPMENT,
    CAMPUS_ICONS,
    COUNTABLE_ACTIVITIES,
    DONE_TOTAL_PCT_ACTIVITIES,
    EQUIPMENT_HEADER_ALIASES,
    FRACTION_METRIC_ACTIVITIES,
    INDUK_BUILDING_CODE_GROUPS,
    INDUK_LOCATION_GROUPS,
    LOCATION_MEAN_PCT_ACTIVITIES,
    OVERALL_FRACTION_ACTIVITIES,
    PCT_DERIVED_DONE_ACTIVITIES,
    PCT_DERIVED_DONE_EXACT,
    PCT_DERIVED_DONE_ROUND10,
    SUMMARY_ONLY_EQUIPMENT,
    TABLE_COLUMNS,
    TRUSTED_DONE_TOTAL_ACTIVITIES,
    campus_sheet_names,
)


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
    if not text or text.upper() in {"N/A", "NA", "-"}:
        return None
    text = text.replace("%", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date_parts(date_str: str) -> tuple[int, int, int] | None:
    """
    Parse mixed sheet date formats into (year, month, day).

    Sheet mixes M/D/YYYY (e.g. 8/12/2026 = 12 Aug) and D/M/YYYY (e.g. 18/8/2026).
    Heuristic:
      - first > 12  → D/M/Y
      - second > 12 → M/D/Y
      - both <= 12  → M/D/Y (matches 8/12…8/16 Aug series in this workbook)
    """
    parts = re.split(r"[/-]", str(date_str).strip())
    if len(parts) != 3:
        return None
    try:
        a, b, y = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if y < 100:
        y += 2000
    if a > 12:
        d, m = a, b
    elif b > 12:
        m, d = a, b
    else:
        m, d = a, b
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    return (y, m, d)


def _parse_date_key(date_str: str):
    """Chronological sort key for mixed-format sheet dates."""
    parts = _parse_date_parts(date_str)
    return parts if parts else (9999, 12, 31)


def _normalize_date_label(date_str: str) -> str:
    """Display all dates as mm/dd/yyyy for consistent chart and dropdown labels."""
    parts = _parse_date_parts(date_str)
    if not parts:
        return str(date_str).strip()
    y, m, d = parts
    return f"{m:02d}/{d:02d}/{y}"


def _looks_like_date(value) -> bool:
    text = str(value).strip()
    return bool(re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", text))


def _canonicalize_equipment_name(raw) -> str | None:
    text = str(raw or "").strip().lower().replace("\r", "")
    if not text:
        return None
    aliased = EQUIPMENT_HEADER_ALIASES.get(text)
    if aliased:
        return aliased
    for name in ACTIVE_EQUIPMENT:
        if name.lower() == text:
            return name
    return None


def _equipment_col_map(
    act_cols: list[int],
    n_cols: int,
    *,
    header_row: pd.Series | None = None,
    subheader_row: pd.Series | None = None,
) -> dict[str, int]:
    """
    Map canonical equipment names → column index after Fiber Optic.

    Prefers subheader labels (Controller / MultiGE switch / Dist. Switch)
    and header label RFS. Older sheets used Access Switch (aliased to MultiGE).
    """
    if not act_cols:
        return {}
    start = act_cols[-1] + 1
    mapping: dict[str, int] = {}
    for offset in range(0, 5):
        col = start + offset
        if col >= n_cols:
            break
        name = None
        if subheader_row is not None and col < len(subheader_row):
            name = _canonicalize_equipment_name(subheader_row.iloc[col])
        if not name and header_row is not None and col < len(header_row):
            name = _canonicalize_equipment_name(header_row.iloc[col])
        if name and name not in mapping:
            mapping[name] = col

    # Positional fallback for unlabeled older blocks (3 equipment cols only).
    if not mapping:
        for offset, name in enumerate(
            ["Controller", "MultiGE Switch", "Dist. Switch"]
        ):
            col = start + offset
            if col < n_cols:
                mapping[name] = col
    return mapping


def _equipment_cols(
    act_cols: list[int],
    n_cols: int,
    *,
    header_row: pd.Series | None = None,
    subheader_row: pd.Series | None = None,
) -> list[int]:
    """
    Column indices aligned to ACTIVE_EQUIPMENT order.
    Missing equipment uses -1 (skip when reading).
    """
    col_map = _equipment_col_map(
        act_cols,
        n_cols,
        header_row=header_row,
        subheader_row=subheader_row,
    )
    return [col_map.get(name, -1) for name in ACTIVE_EQUIPMENT]


def _header_subheader(
    df: pd.DataFrame, header_idx: int
) -> tuple[pd.Series, pd.Series | None]:
    header = df.iloc[header_idx]
    sub = df.iloc[header_idx + 1] if header_idx + 1 < len(df) else None
    return header, sub

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
        dates.append(_normalize_date_label(found) if found else found)
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


def available_dates(df: pd.DataFrame, *, newest_first: bool = True) -> list[str]:
    """Extract date blocks as mm/dd/yyyy, sorted chronologically (newest first by default)."""
    if df is None or df.empty:
        return []
    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    blocks = _find_date_blocks(header_row)
    dates = _extract_dates_for_blocks(df, blocks)
    clean = [d for d in dates if d]
    unique = list(dict.fromkeys(clean))
    ordered = sorted(unique, key=_parse_date_key)
    return list(reversed(ordered)) if newest_first else ordered


def _parse_number(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.upper() in {"N/A", "NA", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_building_code(location: str) -> str | None:
    """
    Extract a building code like K09 / H10 / F27 from a location label.
    Accepts single-digit forms (K9 → K09).
    """
    text = re.sub(r"\s+", " ", str(location or "").strip()).upper()
    if not text:
        return None
    matches = re.findall(r"\b([A-Z])\s*0*(\d{1,2})\b", text)
    if not matches:
        return None
    letter, num = matches[-1]
    return f"{letter}{int(num):02d}"


def _induk_group_name(location: str) -> str | None:
    """Map an INDUK location label to a grouped desa / building name."""
    loc = location.strip()
    if not loc:
        return None
    normalized = re.sub(r"\s+", " ", loc).strip()
    upper = normalized.upper()

    # Prefer desa-name keywords (and short-label anchors like K18 / D18).
    for group_name, pattern in INDUK_LOCATION_GROUPS:
        if pattern.startswith("^"):
            short = re.sub(r"^DS\s+", "", upper).strip()
            if re.search(pattern, short, re.IGNORECASE):
                return group_name
        elif re.search(pattern, upper, re.IGNORECASE):
            return group_name

    # Fallback: building code only (new MultiGE-only rows, etc.).
    code = _normalize_building_code(upper)
    if code and code in INDUK_BUILDING_CODE_GROUPS:
        return INDUK_BUILDING_CODE_GROUPS[code]
    return None


def _building_short_label(location: str) -> str:
    """Simple building code from a location label, e.g. K01, H06, L12."""
    code = _normalize_building_code(location)
    if code:
        return code
    text = re.sub(r"\s+", " ", str(location).strip()).upper()
    return text[:10]


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


def _activity_values_from_row(
    row: pd.Series,
    act_cols: list[int],
    include_equipment: bool = False,
    eq_cols: list[int] | None = None,
) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for act_name, col_idx in zip(ACTIVITIES, act_cols):
        values[act_name] = _parse_number(row.iloc[col_idx]) if col_idx < len(row) else None
    if include_equipment:
        cols = eq_cols if eq_cols is not None else _equipment_cols(act_cols, len(row))
        for eq_name, col_idx in zip(ACTIVE_EQUIPMENT, cols):
            if col_idx is None or col_idx < 0 or col_idx >= len(row):
                values[eq_name] = None
                continue
            raw = row.iloc[col_idx]
            text = "" if raw is None else str(raw).strip().upper()
            if text in {"", "N/A", "NA", "-"}:
                values[eq_name] = None
            else:
                values[eq_name] = _parse_number(raw)
    return values


def _derived_done_from_pct(
    total: float | None, pct: float | None, *, round_nearest_10: bool = False
) -> float | None:
    """DONE = (percentage / 100) × TOTAL. Optionally round to nearest 10."""
    if total is None or pct is None:
        return None
    raw = float(total) * float(pct) / 100.0
    if round_nearest_10:
        return float(round(raw / 10.0) * 10)
    return round(raw, 2)


def _location_block_values(
    df: pd.DataFrame,
    done_row: int,
    total_row: int,
    percent_row: int,
    act_cols: list[int],
    include_equipment: bool = False,
    eq_cols: list[int] | None = None,
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    """
    Read DONE / TOTAL / PERCENTAGE for one location block.

    Trusted from sheet DONE+TOTAL (recalc %): UTP, AP, Slab Coring, Rack,
      MultiGE Switch.
    Trunking / Lay Cable / Termination: DONE not collected → None (show N/A).
    Fiber Optic: DONE = % × TOTAL (no round-to-10).
    Controller / RFS: read location cells when present; campus averages use
      sheet TOTAL DONE / OVERALL TOTAL only.
    """
    if eq_cols is None and include_equipment:
        eq_cols = _equipment_cols(act_cols, len(df.columns))

    done_vals = _activity_values_from_row(
        df.iloc[done_row],
        act_cols,
        include_equipment=include_equipment,
        eq_cols=eq_cols,
    )
    total_vals = _activity_values_from_row(
        df.iloc[total_row],
        act_cols,
        include_equipment=include_equipment,
        eq_cols=eq_cols,
    )
    pct_vals: dict[str, float | None] = {}
    for act_name, col_idx in zip(ACTIVITIES, act_cols):
        pct_vals[act_name] = (
            _parse_percent(df.iloc[percent_row, col_idx]) if col_idx < len(df.columns) else None
        )
    if include_equipment and eq_cols is not None:
        for eq_name, col_idx in zip(ACTIVE_EQUIPMENT, eq_cols):
            if col_idx is None or col_idx < 0 or col_idx >= len(df.columns):
                pct_vals[eq_name] = None
            else:
                pct_vals[eq_name] = _parse_percent(df.iloc[percent_row, col_idx])

    # Only % + TOTAL are collected for these — never invent a DONE count.
    for act_name in PCT_DERIVED_DONE_ROUND10:
        done_vals[act_name] = None

    for act_name in PCT_DERIVED_DONE_EXACT:
        derived = _derived_done_from_pct(
            total_vals.get(act_name), pct_vals.get(act_name), round_nearest_10=False
        )
        if derived is not None:
            done_vals[act_name] = derived

    # Trusted DONE÷TOTAL columns (activities + MultiGE Switch, etc.).
    for act_name in TRUSTED_DONE_TOTAL_ACTIVITIES:
        done = done_vals.get(act_name)
        total = total_vals.get(act_name)
        if done is not None and total is not None and float(total) != 0:
            pct_vals[act_name] = round(float(done) / float(total) * 100, 2)
        elif act_name in done_vals or act_name in pct_vals:
            # Keep sheet % only when both done/total missing for non-required keys
            if done is None or total is None or float(total or 0) == 0:
                if act_name in {
                    "UTP Point",
                    "AP Mounting",
                    "Slab Coring (hole)",
                    "Rack Installation (nos)",
                    "MultiGE Switch",
                }:
                    pct_vals[act_name] = None

    return done_vals, total_vals, pct_vals


def _average_percent_from_totals(
    total_done: dict[str, float | None],
    overall_total: dict[str, float | None],
    location_percentages: dict[str, list[float]] | list[float] | None = None,
    columns: list[str] | None = None,
) -> dict[str, float | None]:
    """PERCENTAGE = DONE / TOTAL × 100 for all requested columns."""
    cols = columns or ACTIVITIES
    result: dict[str, float | None] = {}
    for act in cols:
        done = total_done.get(act)
        total = overall_total.get(act)
        if done is None or total is None or total == 0:
            result[act] = None
        else:
            result[act] = round(float(done) / float(total) * 100, 2)
    return result


def _mean_location_percent(
    location_blocks: list[tuple[str, int, int, int]],
    df: pd.DataFrame,
    act_cols: list[int],
    activity: str,
    *,
    group_filter: str | None = None,
    induk_grouped_only: bool = False,
) -> float | None:
    """
    Dashboard % = (sum of location PERCENTAGE) / (number of locations with a %).

    INDUK: pass group_filter for one desa, or induk_grouped_only=True for all
    locations that map to INDUK_LOCATION_GROUPS.
    Other campuses: leave both unset to include every location block.
    """
    try:
        col_idx = act_cols[ACTIVITIES.index(activity)]
    except (ValueError, IndexError):
        return None

    values: list[float] = []
    for location, _done_row, _total_row, percent_row in location_blocks:
        if group_filter or induk_grouped_only:
            group = _induk_group_name(location)
            if group_filter and group != group_filter:
                continue
            if induk_grouped_only and not group:
                continue
        if col_idx >= len(df.columns):
            continue
        pct = _parse_percent(df.iloc[percent_row, col_idx])
        if pct is not None:
            values.append(pct)

    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _sum_location_done_total(
    location_blocks: list[tuple[str, int, int, int]],
    df: pd.DataFrame,
    act_cols: list[int],
    activities: list[str] | None = None,
    *,
    eq_cols: list[int] | None = None,
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Sum DONE and TOTAL across all location rows."""
    acts = activities or list(DONE_TOTAL_PCT_ACTIVITIES)
    need_equipment = any(a in ACTIVE_EQUIPMENT for a in acts)
    sum_done: dict[str, float] = {a: 0.0 for a in acts}
    sum_total: dict[str, float] = {a: 0.0 for a in acts}
    has_done = {a: False for a in acts}
    has_total = {a: False for a in acts}

    for _loc, done_row, total_row, percent_row in location_blocks:
        done_vals, total_vals, _pct = _location_block_values(
            df,
            done_row,
            total_row,
            percent_row,
            act_cols,
            include_equipment=need_equipment,
            eq_cols=eq_cols,
        )
        for act in acts:
            d = done_vals.get(act)
            t = total_vals.get(act)
            if d is not None:
                sum_done[act] += d
                has_done[act] = True
            if t is not None:
                sum_total[act] += t
                has_total[act] = True

    return (
        {a: (sum_done[a] if has_done[a] else None) for a in acts},
        {a: (sum_total[a] if has_total[a] else None) for a in acts},
    )


def _read_summary_only_equipment(
    df: pd.DataFrame,
    act_cols: list[int],
    location_col: int,
    progress_col: int,
    eq_cols: list[int],
) -> dict[str, tuple[float | None, float | None]]:
    """
    Controller / RFS: read TOTAL DONE and OVERALL TOTAL from the sheet only,
    then callers recalculate average %.
    """
    done_row_idx = _find_summary_row(df, location_col, progress_col, {"TOTAL DONE"})
    total_row_idx = _find_summary_row(df, location_col, progress_col, {"OVERALL TOTAL"})
    out: dict[str, tuple[float | None, float | None]] = {}
    for eq_name, col_idx in zip(ACTIVE_EQUIPMENT, eq_cols):
        if eq_name not in SUMMARY_ONLY_EQUIPMENT:
            continue
        if col_idx is None or col_idx < 0:
            out[eq_name] = (None, None)
            continue
        d = (
            _parse_number(df.iloc[done_row_idx, col_idx])
            if done_row_idx is not None and col_idx < len(df.columns)
            else None
        )
        t = (
            _parse_number(df.iloc[total_row_idx, col_idx])
            if total_row_idx is not None and col_idx < len(df.columns)
            else None
        )
        out[eq_name] = (d, t)
    return out


def _attach_fraction_fields(
    record: dict,
    name: str,
    done: float | None,
    total: float | None,
) -> None:
    record[f"{name}__done"] = None if done is None else int(round(float(done)))
    record[f"{name}__total"] = None if total is None else int(round(float(total)))
    if done is not None and total is not None and float(total) != 0:
        record[name] = round(float(done) / float(total) * 100, 2)
    else:
        record[name] = None


def _accumulate_group_values(
    location_blocks: list[tuple[str, int, int, int]],
    df: pd.DataFrame,
    act_cols: list[int],
    *,
    eq_cols: list[int] | None = None,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """
    Roll up DONE/TOTAL (+ equipment) per INDUK desa group.

    DONE for Trunking/Lay/Term/Fiber is derived per location before summing.
    UTP/AP/Slab/Rack/MultiGE use sheet DONE/TOTAL as-is.
    """
    grouped_done: dict[str, dict[str, float]] = {}
    grouped_total: dict[str, dict[str, float]] = {}

    for location, done_row, total_row, percent_row in location_blocks:
        group = _induk_group_name(location)
        if not group:
            continue
        done_vals, total_vals, _pct_vals = _location_block_values(
            df,
            done_row,
            total_row,
            percent_row,
            act_cols,
            include_equipment=True,
            eq_cols=eq_cols,
        )

        for col in TABLE_COLUMNS:
            # Campus averages for Controller/RFS come from sheet summary rows.
            if col in SUMMARY_ONLY_EQUIPMENT:
                continue
            done_num = done_vals.get(col)
            total_num = total_vals.get(col)
            if done_num is not None:
                grouped_done.setdefault(group, {}).setdefault(col, 0.0)
                grouped_done[group][col] += done_num
            if total_num is not None:
                grouped_total.setdefault(group, {}).setdefault(col, 0.0)
                grouped_total[group][col] += total_num

    return grouped_done, grouped_total


def _compute_induk_overall_by_date(
    df: pd.DataFrame, group_filter: str | None = None
) -> pd.DataFrame:
    """
    INDUK summary per date block using grouped DONE/TOTAL rollups.
    Most activities: PERCENTAGE = accumulated DONE / accumulated TOTAL.
    Trunking: mean of location PERCENTAGE within the desa (or all groups).
    Controller/RFS: sheet TOTAL DONE / OVERALL TOTAL (recalc %).
    MultiGE: sum of location DONE/TOTAL (recalc %).
    If group_filter is set, only that desa group is included.
    """
    header_idx = _detect_header_row_index(df)
    header_row, subheader_row = _header_subheader(df, header_idx)
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    records: list[dict] = []
    for date_label, (_, act_cols) in zip(block_dates, blocks):
        if not date_label:
            continue

        eq_cols = _equipment_cols(
            act_cols,
            len(df.columns),
            header_row=header_row,
            subheader_row=subheader_row,
        )
        grouped_done, grouped_total = _accumulate_group_values(
            location_blocks, df, act_cols, eq_cols=eq_cols
        )

        if group_filter:
            if group_filter not in grouped_done and group_filter not in grouped_total:
                continue
            groups = [group_filter]
        else:
            groups = [name for name, _ in INDUK_LOCATION_GROUPS]

        campus_done: dict[str, float | None] = {col: 0.0 for col in ACTIVITIES}
        campus_total: dict[str, float | None] = {col: 0.0 for col in ACTIVITIES}
        for group in groups:
            for col in ACTIVITIES:
                campus_done[col] = (campus_done[col] or 0.0) + grouped_done.get(group, {}).get(col, 0.0)
                campus_total[col] = (campus_total[col] or 0.0) + grouped_total.get(group, {}).get(col, 0.0)

        for col in ACTIVITIES:
            if campus_done[col] == 0.0 and campus_total[col] == 0.0:
                has_total = any(col in grouped_total.get(group, {}) for group in groups)
                has_done = any(col in grouped_done.get(group, {}) for group in groups)
                if not has_total and not has_done:
                    campus_done[col] = None
                    campus_total[col] = None

        record = {"Date": _normalize_date_label(date_label)}
        averages = _average_percent_from_totals(campus_done, campus_total)
        record.update(averages)
        # Trunking (etc.): mean of location % within the desa / all groups.
        for act in LOCATION_MEAN_PCT_ACTIVITIES:
            record[act] = _mean_location_percent(
                location_blocks,
                df,
                act_cols,
                act,
                group_filter=group_filter,
                induk_grouped_only=group_filter is None,
            )
        for act in FRACTION_METRIC_ACTIVITIES:
            if act in ACTIVITIES:
                done = campus_done.get(act)
                total = campus_total.get(act)
                _attach_fraction_fields(record, act, done, total)

        # MultiGE: sum location DONE/TOTAL across selected groups.
        mg_done = 0.0
        mg_total = 0.0
        mg_has_d = mg_has_t = False
        for group in groups:
            if "MultiGE Switch" in grouped_done.get(group, {}):
                mg_done += grouped_done[group]["MultiGE Switch"]
                mg_has_d = True
            if "MultiGE Switch" in grouped_total.get(group, {}):
                mg_total += grouped_total[group]["MultiGE Switch"]
                mg_has_t = True
        if "MultiGE Switch" in FRACTION_METRIC_ACTIVITIES:
            _attach_fraction_fields(
                record,
                "MultiGE Switch",
                mg_done if mg_has_d else None,
                mg_total if mg_has_t else None,
            )

        # Controller / RFS: sheet TOTAL DONE / OVERALL TOTAL only.
        summary_eq = _read_summary_only_equipment(
            df, act_cols, location_col, progress_col, eq_cols
        )
        for eq_name in SUMMARY_ONLY_EQUIPMENT:
            d, t = summary_eq.get(eq_name, (None, None))
            if eq_name in FRACTION_METRIC_ACTIVITIES:
                _attach_fraction_fields(record, eq_name, d, t)

        if any(record.get(a) is not None for a in ACTIVITIES) or any(
            record.get(f"{a}__total") is not None for a in FRACTION_METRIC_ACTIVITIES
        ):
            records.append(record)

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records).drop_duplicates(subset=["Date"], keep="last")
    result["_sort"] = result["Date"].map(_parse_date_key)
    return result.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)


def get_induk_desa_overall(df: pd.DataFrame, desa_name: str) -> pd.DataFrame:
    """Average % time series for one INDUK desa group."""
    return _compute_induk_overall_by_date(df, group_filter=desa_name)


def _location_done_for_date_block(
    df: pd.DataFrame,
    location_blocks: list[tuple[str, int, int, int]],
    act_cols: list[int],
    group_filter: str | None,
) -> dict[str, dict[str, float]]:
    """Map short building label → activity DONE for one date's columns."""
    out: dict[str, dict[str, float]] = {}
    for location, done_row, total_row, percent_row in location_blocks:
        group = _induk_group_name(location)
        if group_filter and group != group_filter:
            continue
        if not group:
            continue
        done_vals, _total_vals, _pct = _location_block_values(
            df, done_row, total_row, percent_row, act_cols
        )
        short = _building_short_label(location)
        bucket = out.setdefault(short, {})
        for act in ACTIVITIES:
            val = done_vals.get(act)
            if val is None:
                continue
            bucket[act] = float(val)
    return out


def induk_desa_building_increases(
    df: pd.DataFrame, desa_name: str, prev_date: str, latest_date: str
) -> dict[str, list[str]]:
    """
    For each activity, short building names whose DONE rose between two dates
    within one INDUK desa group (e.g. {'UTP Point': ['K05', 'K07']}).
    """
    if df is None or df.empty or not desa_name:
        return {}

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    prev_norm = _normalize_date_label(prev_date)
    latest_norm = _normalize_date_label(latest_date)

    def _find_cols(target: str) -> list[int] | None:
        for date_label, (_, act_cols) in zip(block_dates, blocks):
            if date_label == target or _normalize_date_label(date_label) == target:
                return act_cols
        return None

    prev_cols = _find_cols(prev_norm) or _find_cols(prev_date)
    latest_cols = _find_cols(latest_norm) or _find_cols(latest_date)
    if not prev_cols or not latest_cols:
        return {}

    prev_map = _location_done_for_date_block(
        df, location_blocks, prev_cols, desa_name
    )
    latest_map = _location_done_for_date_block(
        df, location_blocks, latest_cols, desa_name
    )

    increases: dict[str, list[str]] = {act: [] for act in ACTIVITIES}
    for short in sorted(set(prev_map) | set(latest_map)):
        for act in ACTIVITIES:
            v0 = prev_map.get(short, {}).get(act)
            v1 = latest_map.get(short, {}).get(act)
            if v0 is None or v1 is None:
                continue
            if v1 > v0 + 1e-9:
                increases[act].append(short)

    return {act: names for act, names in increases.items() if names}


def _friendly_location_label(location: str) -> str:
    """Short display name, e.g. 'Aman Damai K08'."""
    text = re.sub(r"\s+", " ", str(location).strip())
    text = re.sub(r"^(Desasiswa|DS)\s+", "", text, flags=re.IGNORECASE)
    return text.strip() or str(location).strip()


def _short_day_month(date_str: str) -> str:
    """Format date as D/M for table headers, e.g. 23/08."""
    parts = _parse_date_parts(date_str)
    if not parts:
        return str(date_str).strip()
    _year, month, day = parts
    return f"{day:02d}/{month:02d}"


def _location_percent_for_date_block(
    df: pd.DataFrame,
    location_blocks: list[tuple[str, int, int, int]],
    act_cols: list[int],
    *,
    group_filter: str | None = None,
    induk_grouped_only: bool = False,
) -> dict[str, dict[str, float]]:
    """Map full location label → activity PERCENTAGE for one date block."""
    out: dict[str, dict[str, float]] = {}
    for location, done_row, total_row, percent_row in location_blocks:
        if group_filter or induk_grouped_only:
            group = _induk_group_name(location)
            if group_filter and group != group_filter:
                continue
            if induk_grouped_only and not group:
                continue
        _done, _total, pct_vals = _location_block_values(
            df, done_row, total_row, percent_row, act_cols
        )
        bucket: dict[str, float] = {}
        for act_name in ACTIVITIES:
            pct = pct_vals.get(act_name)
            if pct is not None:
                bucket[act_name] = pct
        if bucket:
            out[location] = bucket
    return out


def _location_done_counts_for_date_block(
    df: pd.DataFrame,
    location_blocks: list[tuple[str, int, int, int]],
    act_cols: list[int],
    activities: list[str],
    *,
    group_filter: str | None = None,
    induk_grouped_only: bool = False,
) -> dict[str, dict[str, float]]:
    """Map full location label → trusted DONE counts for selected activities."""
    out: dict[str, dict[str, float]] = {}
    for location, done_row, total_row, percent_row in location_blocks:
        if group_filter or induk_grouped_only:
            group = _induk_group_name(location)
            if group_filter and group != group_filter:
                continue
            if induk_grouped_only and not group:
                continue
        done_vals, _total_vals, _pct = _location_block_values(
            df, done_row, total_row, percent_row, act_cols
        )
        bucket: dict[str, float] = {}
        for act in activities:
            val = done_vals.get(act)
            if val is not None:
                bucket[act] = float(val)
        if bucket:
            out[location] = bucket
    return out


def _format_change_value(act: str, value: float | None) -> str:
    """Format a change-table value (count for UTP/AP, % for others)."""
    if value is None:
        return "—"
    if act in FRACTION_METRIC_ACTIVITIES:
        return str(int(round(value)))
    return f"{value:.0f}%"


def location_change_summary(
    df: pd.DataFrame,
    prev_date: str,
    latest_date: str,
    *,
    group_filter: str | None = None,
    induk_grouped_only: bool = False,
) -> pd.DataFrame:
    """
    Rows where a location's progress changed between two dates.

    - UTP Point / AP Mounting: compare DONE counts (same as dashboard metrics)
    - Other activities: compare PERCENTAGE

    Columns: Location, Item, <prev>, <latest>, Change (↑ / ↓).
    """
    empty = pd.DataFrame(columns=["Location", "Item", "Change"])
    if df is None or df.empty or not prev_date or not latest_date:
        return empty

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    prev_norm = _normalize_date_label(prev_date)
    latest_norm = _normalize_date_label(latest_date)

    def _find_cols(target: str) -> list[int] | None:
        for date_label, (_, act_cols) in zip(block_dates, blocks):
            if date_label == target or _normalize_date_label(date_label) == target:
                return act_cols
        return None

    prev_cols = _find_cols(prev_norm) or _find_cols(prev_date)
    latest_cols = _find_cols(latest_norm) or _find_cols(latest_date)
    if not prev_cols or not latest_cols:
        return empty

    filter_kw = dict(
        group_filter=group_filter,
        induk_grouped_only=induk_grouped_only,
    )
    prev_pct = _location_percent_for_date_block(
        df, location_blocks, prev_cols, **filter_kw
    )
    latest_pct = _location_percent_for_date_block(
        df, location_blocks, latest_cols, **filter_kw
    )
    fraction_acts = list(FRACTION_METRIC_ACTIVITIES)
    prev_done = _location_done_counts_for_date_block(
        df, location_blocks, prev_cols, fraction_acts, **filter_kw
    )
    latest_done = _location_done_counts_for_date_block(
        df, location_blocks, latest_cols, fraction_acts, **filter_kw
    )

    prev_col = _short_day_month(prev_date)
    latest_col = _short_day_month(latest_date)
    if prev_col == latest_col:
        prev_col = f"{prev_col} (prev)"
        latest_col = f"{latest_col} (latest)"

    locations = sorted(
        set(prev_pct) | set(latest_pct) | set(prev_done) | set(latest_done),
        key=lambda s: s.upper(),
    )
    rows: list[dict[str, str]] = []
    for location in locations:
        for act in ACTIVITIES:
            if act in FRACTION_METRIC_ACTIVITIES:
                v0 = prev_done.get(location, {}).get(act)
                v1 = latest_done.get(location, {}).get(act)
                if v0 is None and v1 is None:
                    continue
                if v0 is None and v1 is not None:
                    rows.append(
                        {
                            "Location": _friendly_location_label(location),
                            "Item": act,
                            prev_col: "—",
                            latest_col: _format_change_value(act, v1),
                            "Change": "★ New",
                        }
                    )
                    continue
                if v1 is None:
                    continue
                diff = float(v1) - float(v0)
                if abs(diff) < 1e-9:
                    continue
                arrow = "↑" if diff > 0 else "↓"
                rows.append(
                    {
                        "Location": _friendly_location_label(location),
                        "Item": act,
                        prev_col: str(int(round(v0))),
                        latest_col: str(int(round(v1))),
                        "Change": f"{arrow} {abs(int(round(diff)))}",
                    }
                )
            else:
                v0 = prev_pct.get(location, {}).get(act)
                v1 = latest_pct.get(location, {}).get(act)
                if v0 is None and v1 is None:
                    continue
                if v0 is None and v1 is not None:
                    rows.append(
                        {
                            "Location": _friendly_location_label(location),
                            "Item": act,
                            prev_col: "—",
                            latest_col: _format_change_value(act, v1),
                            "Change": "★ New",
                        }
                    )
                    continue
                if v1 is None:
                    continue
                diff = float(v1) - float(v0)
                if abs(diff) < 1e-9:
                    continue
                arrow = "↑" if diff > 0 else "↓"
                rows.append(
                    {
                        "Location": _friendly_location_label(location),
                        "Item": act,
                        prev_col: f"{v0:.0f}%",
                        latest_col: f"{v1:.0f}%",
                        "Change": f"{arrow} {abs(diff):.0f}%",
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=["Location", "Item", prev_col, latest_col, "Change"]
        )
    return pd.DataFrame(rows)


def location_changes_by_building(
    df: pd.DataFrame, prev_date: str, latest_date: str
) -> dict[str, dict[str, str]]:
    """
    Location key → {activity: 'prev→latest (↑N)'} for one campus sheet.

    Keys include the building code when present (K05, H06) and a stable
    short label otherwise, so Blok SH / Murni names stay unique.
    """
    if df is None or df.empty or not prev_date or not latest_date:
        return {}

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    prev_norm = _normalize_date_label(prev_date)
    latest_norm = _normalize_date_label(latest_date)

    def _find_cols(target: str) -> list[int] | None:
        for date_label, (_, act_cols) in zip(block_dates, blocks):
            if date_label == target or _normalize_date_label(date_label) == target:
                return act_cols
        return None

    prev_cols = _find_cols(prev_norm) or _find_cols(prev_date)
    latest_cols = _find_cols(latest_norm) or _find_cols(latest_date)
    if not prev_cols or not latest_cols:
        return {}

    prev_pct = _location_percent_for_date_block(df, location_blocks, prev_cols)
    latest_pct = _location_percent_for_date_block(df, location_blocks, latest_cols)
    prev_done = _location_done_counts_for_date_block(
        df, location_blocks, prev_cols, list(FRACTION_METRIC_ACTIVITIES)
    )
    latest_done = _location_done_counts_for_date_block(
        df, location_blocks, latest_cols, list(FRACTION_METRIC_ACTIVITIES)
    )

    locations = sorted(
        set(prev_pct) | set(latest_pct) | set(prev_done) | set(latest_done),
        key=lambda s: s.upper(),
    )
    lookup: dict[str, dict[str, str]] = {}

    def _unique_keys(location: str) -> list[str]:
        """Prefer building code; else compressed unique name."""
        keys: list[str] = []
        code = _building_short_label(location).upper()
        # Only treat as a real code if it looks like K01 / H06 / etc.
        if re.fullmatch(r"[A-Z]\d{2}", code or ""):
            keys.append(code)
        compact = re.sub(r"[^A-Z0-9]+", "", location.strip().upper())
        compact = re.sub(r"^(BLOK|BLOCK|DESASISWA|DS)+", "", compact)
        if compact and compact not in keys:
            keys.append(compact)
        # Always keep full compact as last resort
        full = re.sub(r"[^A-Z0-9]+", "", location.strip().upper())
        if full and full not in keys:
            keys.append(full)
        return keys

    for location in locations:
        bucket: dict[str, str] = {}
        for act in ACTIVITIES:
            if act in FRACTION_METRIC_ACTIVITIES:
                v0 = prev_done.get(location, {}).get(act)
                v1 = latest_done.get(location, {}).get(act)
                if v0 is None and v1 is None:
                    continue
                if v0 is None and v1 is not None:
                    latest_s = _format_change_value(act, v1)
                    bucket[act] = f"{act} —→{latest_s} (★ New)"
                    continue
                if v1 is None:
                    continue
                diff = float(v1) - float(v0)
                if abs(diff) < 1e-9:
                    continue
                arrow = "↑" if diff > 0 else "↓"
                prev_s, latest_s = str(int(round(v0))), str(int(round(v1)))
                change = f"{arrow} {abs(int(round(diff)))}"
            else:
                v0 = prev_pct.get(location, {}).get(act)
                v1 = latest_pct.get(location, {}).get(act)
                if v0 is None and v1 is None:
                    continue
                if v0 is None and v1 is not None:
                    latest_s = _format_change_value(act, v1)
                    bucket[act] = f"{act} —→{latest_s} (★ New)"
                    continue
                if v1 is None:
                    continue
                diff = float(v1) - float(v0)
                if abs(diff) < 1e-9:
                    continue
                arrow = "↑" if diff > 0 else "↓"
                prev_s, latest_s = f"{v0:.0f}%", f"{v1:.0f}%"
                change = f"{arrow} {abs(diff):.0f}%"
            bucket[act] = f"{act} {prev_s}→{latest_s} ({change})"
        if not bucket:
            continue
        for key in _unique_keys(location):
            lookup[key] = bucket

    return lookup


def _read_sheet_summary_for_block(
    df: pd.DataFrame,
    act_cols: list[int],
    location_col: int,
    progress_col: int,
    *,
    header_row: pd.Series | None = None,
    subheader_row: pd.Series | None = None,
) -> dict[str, dict[str, str]]:
    """
    Read TOTAL DONE / OVERALL TOTAL / AVERAGE PERCENTAGE directly from the sheet
    for one date block so daily data matches Google Sheets.
    """
    labels = {
        "TOTAL DONE": "TOTAL DONE",
        "OVERALL TOTAL": "OVERALL TOTAL",
        "AVERAGE PERCENTAGE": "AVERAGE PERCENTAGE",
        "AVERAGE PERCENT": "AVERAGE PERCENTAGE",
    }
    eq_cols = _equipment_cols(
        act_cols,
        len(df.columns),
        header_row=header_row,
        subheader_row=subheader_row,
    )
    out: dict[str, dict[str, str]] = {}

    for row_idx in range(len(df)):
        label = _row_label(df, row_idx, location_col, progress_col)
        canonical = labels.get(label)
        if not canonical:
            continue
        row_data: dict[str, str] = {}
        for act_name, col_idx in zip(ACTIVITIES, act_cols):
            raw = df.iloc[row_idx, col_idx] if col_idx < len(df.columns) else ""
            if canonical == "AVERAGE PERCENTAGE":
                pct = _parse_percent(raw)
                row_data[act_name] = f"{pct:.2f}%" if pct is not None else "N/A"
            else:
                # Keep sheet values as-is (blank → N/A); do not re-round.
                text = "" if raw is None else str(raw).strip()
                row_data[act_name] = text if text else "N/A"
        for eq_name, col_idx in zip(ACTIVE_EQUIPMENT, eq_cols):
            if col_idx is None or col_idx < 0:
                row_data[eq_name] = "N/A"
                continue
            raw = df.iloc[row_idx, col_idx] if col_idx < len(df.columns) else ""
            if canonical == "AVERAGE PERCENTAGE":
                pct = _parse_percent(raw)
                row_data[eq_name] = f"{pct:.2f}%" if pct is not None else "N/A"
            else:
                text = "" if raw is None else str(raw).strip()
                row_data[eq_name] = text if text else "N/A"
        out[canonical] = row_data

    return out


def _induk_grouped_snapshot(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    """
    Excel-like INDUK table with grouped desa locations for one date block.

    Per group: DONE/TOTAL accumulated from member locations; PERCENTAGE = DONE/TOTAL.
    Location DONE for Trunking/Lay/Term/Fiber is derived before summing.
    MultiGE / Slab / Rack summed from location DONE/TOTAL.
    Controller / RFS footer from sheet TOTAL DONE / OVERALL TOTAL (recalc %).
    """
    header_idx = _detect_header_row_index(df)
    header_row, subheader_row = _header_subheader(df, header_idx)
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    date_str_norm = _normalize_date_label(date_str)
    block_i = next(
        (i for i, d in enumerate(block_dates) if d == date_str or d == date_str_norm),
        None,
    )
    if block_i is None:
        return pd.DataFrame()

    _, act_cols = blocks[block_i]
    eq_cols = _equipment_cols(
        act_cols,
        len(df.columns),
        header_row=header_row,
        subheader_row=subheader_row,
    )
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)
    grouped_done, grouped_total = _accumulate_group_values(
        location_blocks, df, act_cols, eq_cols=eq_cols
    )

    rows: list[dict[str, str]] = []
    for group_name, _ in INDUK_LOCATION_GROUPS:
        done_map = grouped_done.get(group_name, {})
        total_map = grouped_total.get(group_name, {})
        if not done_map and not total_map:
            continue

        done_row = {"Location": group_name, "Progress": "DONE"}
        total_row = {"Location": "", "Progress": "TOTAL"}
        pct_row = {"Location": "", "Progress": "PERCENTAGE"}

        averages = _average_percent_from_totals(
            {col: done_map.get(col) for col in TABLE_COLUMNS},
            {col: total_map.get(col) for col in TABLE_COLUMNS},
            columns=TABLE_COLUMNS,
        )

        for col in TABLE_COLUMNS:
            if col in SUMMARY_ONLY_EQUIPMENT:
                done_row[col] = "N/A"
                total_row[col] = "N/A"
                pct_row[col] = "N/A"
                continue
            done_row[col] = _display_activity_cell(done_map.get(col), col, "DONE")
            total_row[col] = _display_activity_cell(total_map.get(col), col, "TOTAL")
            if col in LOCATION_MEAN_PCT_ACTIVITIES:
                pct_val = _mean_location_percent(
                    location_blocks,
                    df,
                    act_cols,
                    col,
                    group_filter=group_name,
                )
            else:
                pct_val = averages.get(col)
            pct_row[col] = f"{pct_val:.2f}%" if pct_val is not None else "N/A"

        rows.extend([done_row, total_row, pct_row])

    # Campus footer: accumulate from all location DONE/TOTAL (after derivation).
    # AVERAGE % = TOTAL DONE / OVERALL TOTAL for key activities.
    # Controller / RFS: sheet TOTAL DONE / OVERALL TOTAL (recalc %).
    sheet_summary = _read_sheet_summary_for_block(
        df,
        act_cols,
        location_col,
        progress_col,
        header_row=header_row,
        subheader_row=subheader_row,
    )
    key_acts = list(
        dict.fromkeys(
            PCT_DERIVED_DONE_ACTIVITIES + list(TRUSTED_DONE_TOTAL_ACTIVITIES)
        )
    )
    sum_done, sum_total = _sum_location_done_total(
        location_blocks, df, act_cols, key_acts, eq_cols=eq_cols
    )
    campus_avg = _average_percent_from_totals(sum_done, sum_total, columns=key_acts)

    summary_eq = _read_summary_only_equipment(
        df, act_cols, location_col, progress_col, eq_cols
    )
    summary_eq_avg = _average_percent_from_totals(
        {k: v[0] for k, v in summary_eq.items()},
        {k: v[1] for k, v in summary_eq.items()},
        columns=list(SUMMARY_ONLY_EQUIPMENT),
    )

    for label in ("TOTAL DONE", "OVERALL TOTAL", "AVERAGE PERCENTAGE"):
        values = sheet_summary.get(label)
        if not values and label != "AVERAGE PERCENTAGE":
            continue
        row = {"Location": label, "Progress": ""}
        base = values or {}
        for col in TABLE_COLUMNS:
            if col in SUMMARY_ONLY_EQUIPMENT:
                d, t = summary_eq.get(col, (None, None))
                if label == "TOTAL DONE":
                    row[col] = (
                        _display_activity_cell(d, col, "TOTAL DONE")
                        if d is not None
                        else "N/A"
                    )
                elif label == "OVERALL TOTAL":
                    row[col] = (
                        _display_activity_cell(t, col, "OVERALL TOTAL")
                        if t is not None
                        else "N/A"
                    )
                else:
                    pct = summary_eq_avg.get(col)
                    row[col] = f"{pct:.2f}%" if pct is not None else "N/A"
                continue
            if label == "AVERAGE PERCENTAGE":
                if col in LOCATION_MEAN_PCT_ACTIVITIES:
                    pct = _mean_location_percent(
                        location_blocks,
                        df,
                        act_cols,
                        col,
                        induk_grouped_only=True,
                    )
                    row[col] = f"{pct:.2f}%" if pct is not None else "N/A"
                elif col in key_acts:
                    pct = campus_avg.get(col)
                    row[col] = f"{pct:.2f}%" if pct is not None else "N/A"
                else:
                    row[col] = base.get(col, "N/A")
            elif label == "TOTAL DONE":
                if col in PCT_DERIVED_DONE_ROUND10:
                    row[col] = "N/A"
                elif col in key_acts and sum_done.get(col) is not None:
                    row[col] = _display_activity_cell(sum_done[col], col, "TOTAL DONE")
                else:
                    row[col] = base.get(col, "N/A")
            elif label == "OVERALL TOTAL":
                if col in key_acts and sum_total.get(col) is not None:
                    row[col] = _display_activity_cell(
                        sum_total[col], col, "OVERALL TOTAL"
                    )
                else:
                    row[col] = base.get(col, "N/A")
            else:
                row[col] = base.get(col, "N/A")
        rows.append(row)

    return pd.DataFrame(rows)


# Public alias for Check Daily Data (INDUK accumulated view).
induk_grouped_snapshot = _induk_grouped_snapshot


def get_campus_overall(df: pd.DataFrame, campus: str) -> pd.DataFrame:
    """Campus AVERAGE PERCENTAGE series; INDUK uses grouped DONE/TOTAL logic."""
    if campus == "INDUK":
        return _compute_induk_overall_by_date(df)
    return _parse_overall_summary(df)


def _cell_display(value, as_count: bool = False) -> str:
    """Blank cells are N/A. Countable DONE/TOTAL values show as whole numbers."""
    text = "" if value is None else str(value).strip()
    if not text:
        return "N/A"
    if as_count:
        num = _parse_number(value)
        if num is None:
            return text
        return str(int(round(num)))
    return text


def _display_activity_cell(value, column: str, progress_label: str) -> str:
    """Format DONE/TOTAL counts as integers for countable activities."""
    # Trunking / Lay Cable / Termination: only % + TOTAL are collected.
    if (
        column in PCT_DERIVED_DONE_ROUND10
        and str(progress_label).strip().upper() in {"DONE", "TOTAL DONE"}
    ):
        return "N/A"
    count_rows = {"DONE", "TOTAL", "TOTAL DONE", "OVERALL TOTAL"}
    as_count = column in COUNTABLE_ACTIVITIES and progress_label.upper() in count_rows
    return _cell_display(value, as_count=as_count)


def _row_label(df: pd.DataFrame, row_idx: int, location_col: int, progress_col: int) -> str:
    loc = str(df.iloc[row_idx, location_col]).strip().upper() if location_col < len(df.columns) else ""
    prog = str(df.iloc[row_idx, progress_col]).strip().upper() if progress_col < len(df.columns) else ""
    return loc or prog


def campus_date_snapshot(df: pd.DataFrame, date_str: str, campus: str = "") -> pd.DataFrame:
    """
    Excel-like snapshot for one campus date block.

    All campuses (including INDUK) show per-location rows for the selected date.
    INDUK desa accumulation is used on the Dashboard only, not here.

    MultiGE / Slab / Rack / UTP / AP: location DONE+TOTAL, recalc %;
      footer TOTAL DONE / OVERALL TOTAL = Σ location rows, avg = done/total.
    Fiber: DONE = %×TOTAL; footer from location sums.
    Controller / RFS: footer from sheet TOTAL DONE / OVERALL TOTAL only (recalc %).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    header_idx = _detect_header_row_index(df)
    header_row, subheader_row = _header_subheader(df, header_idx)
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)

    date_str_norm = _normalize_date_label(date_str)
    block_i = next(
        (i for i, d in enumerate(block_dates) if d == date_str or d == date_str_norm),
        None,
    )
    if block_i is None:
        return pd.DataFrame()

    _, act_cols = blocks[block_i]
    eq_cols = _equipment_cols(
        act_cols,
        len(df.columns),
        header_row=header_row,
        subheader_row=subheader_row,
    )
    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)

    # Per-location values after DONE/% rules (incl. MultiGE / Slab / Rack).
    block_vals_by_loc: dict[str, tuple[dict, dict, dict]] = {}
    for location, done_row, total_row, percent_row in location_blocks:
        block_vals_by_loc[location] = _location_block_values(
            df,
            done_row,
            total_row,
            percent_row,
            act_cols,
            include_equipment=True,
            eq_cols=eq_cols,
        )

    # Footer sums: trusted DONE/TOTAL cols + Fiber (derived DONE).
    sum_names = list(
        dict.fromkeys(
            list(TRUSTED_DONE_TOTAL_ACTIVITIES) + list(PCT_DERIVED_DONE_EXACT)
        )
    )
    sum_done, sum_total = _sum_location_done_total(
        location_blocks, df, act_cols, sum_names, eq_cols=eq_cols
    )
    sum_avg = _average_percent_from_totals(
        sum_done, sum_total, columns=sum_names
    )

    # Controller / RFS: sheet TOTAL DONE / OVERALL TOTAL only.
    summary_eq = _read_summary_only_equipment(
        df, act_cols, location_col, progress_col, eq_cols
    )
    summary_eq_avg = _average_percent_from_totals(
        {k: v[0] for k, v in summary_eq.items()},
        {k: v[1] for k, v in summary_eq.items()},
        columns=list(SUMMARY_ONLY_EQUIPMENT),
    )

    rows: list[dict[str, str]] = []
    current_location = ""

    summary_labels = {"TOTAL DONE", "OVERALL TOTAL", "AVERAGE PERCENTAGE", "AVERAGE PERCENT"}
    progress_labels = {"DONE", "TOTAL", "PERCENT", "PERCENTAGE"}

    def _footer_from_sums(name: str, kind: str) -> str | None:
        if kind == "TOTAL DONE":
            val = sum_done.get(name)
            return (
                _display_activity_cell(val, name, "TOTAL DONE")
                if val is not None
                else "N/A"
            )
        if kind == "OVERALL TOTAL":
            val = sum_total.get(name)
            return (
                _display_activity_cell(val, name, "OVERALL TOTAL")
                if val is not None
                else "N/A"
            )
        if kind == "AVERAGE PERCENTAGE":
            pct = sum_avg.get(name)
            return f"{pct:.2f}%" if pct is not None else "N/A"
        return None

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
            summary_kind = loc_upper
            if summary_kind == "AVERAGE PERCENT":
                summary_kind = "AVERAGE PERCENTAGE"
        else:
            location_out = current_location if progress == "DONE" else ""
            progress_out = "PERCENTAGE" if progress == "PERCENT" else progress
            summary_kind = ""

        row_data: dict[str, str] = {
            "Location": location_out,
            "Progress": progress_out,
        }
        done_vals = total_vals = pct_vals = {}
        if current_location in block_vals_by_loc:
            done_vals, total_vals, pct_vals = block_vals_by_loc[current_location]

        for act_name, col_idx in zip(ACTIVITIES, act_cols):
            if progress_out == "DONE" and act_name in PCT_DERIVED_DONE_ROUND10:
                row_data[act_name] = "N/A"
                continue
            if progress_out == "DONE" and act_name in PCT_DERIVED_DONE_EXACT:
                derived = done_vals.get(act_name)
                row_data[act_name] = (
                    _display_activity_cell(derived, act_name, "DONE")
                    if derived is not None
                    else "N/A"
                )
                continue
            # Footer: trusted (UTP/AP/Slab/Rack) + Fiber from location sums.
            if is_summary and act_name in sum_names:
                foot = _footer_from_sums(act_name, summary_kind)
                if foot is not None:
                    row_data[act_name] = foot
                    continue
            if (
                progress_out == "PERCENTAGE"
                and act_name in TRUSTED_DONE_TOTAL_ACTIVITIES
            ):
                pct = pct_vals.get(act_name)
                row_data[act_name] = f"{pct:.2f}%" if pct is not None else "N/A"
                continue
            val = df.iloc[r, col_idx] if col_idx < len(df.columns) else ""
            kind = loc_upper if is_summary else progress_out
            row_data[act_name] = _display_activity_cell(val, act_name, kind)

        for eq_name, col_idx in zip(ACTIVE_EQUIPMENT, eq_cols):
            if col_idx is None or col_idx < 0:
                row_data[eq_name] = "N/A"
                continue

            if eq_name in SUMMARY_ONLY_EQUIPMENT:
                if is_summary:
                    d, t = summary_eq.get(eq_name, (None, None))
                    if summary_kind == "TOTAL DONE":
                        row_data[eq_name] = (
                            _display_activity_cell(d, eq_name, "TOTAL DONE")
                            if d is not None
                            else "N/A"
                        )
                    elif summary_kind == "OVERALL TOTAL":
                        row_data[eq_name] = (
                            _display_activity_cell(t, eq_name, "OVERALL TOTAL")
                            if t is not None
                            else "N/A"
                        )
                    elif summary_kind == "AVERAGE PERCENTAGE":
                        pct = summary_eq_avg.get(eq_name)
                        row_data[eq_name] = (
                            f"{pct:.2f}%" if pct is not None else "N/A"
                        )
                    else:
                        row_data[eq_name] = "N/A"
                else:
                    # Location rows are not used for campus averages.
                    val = (
                        df.iloc[r, col_idx] if col_idx < len(df.columns) else ""
                    )
                    row_data[eq_name] = _display_activity_cell(
                        val, eq_name, progress_out
                    )
                continue

            if eq_name in TRUSTED_DONE_TOTAL_ACTIVITIES:
                if progress_out == "PERCENTAGE":
                    pct = pct_vals.get(eq_name)
                    row_data[eq_name] = (
                        f"{pct:.2f}%" if pct is not None else "N/A"
                    )
                    continue
                if is_summary:
                    foot = _footer_from_sums(eq_name, summary_kind)
                    if foot is not None:
                        row_data[eq_name] = foot
                        continue
                if progress_out == "DONE":
                    val = done_vals.get(eq_name)
                    row_data[eq_name] = (
                        _display_activity_cell(val, eq_name, "DONE")
                        if val is not None
                        else "N/A"
                    )
                    continue
                if progress_out == "TOTAL":
                    val = total_vals.get(eq_name)
                    row_data[eq_name] = (
                        _display_activity_cell(val, eq_name, "TOTAL")
                        if val is not None
                        else "N/A"
                    )
                    continue

            val = df.iloc[r, col_idx] if col_idx < len(df.columns) else ""
            kind = loc_upper if is_summary else progress_out
            row_data[eq_name] = _display_activity_cell(val, eq_name, kind)

        rows.append(row_data)

    return pd.DataFrame(rows)


def location_recalculated_percentages(
    df: pd.DataFrame,
    date_str: str,
    location: str,
) -> dict[str, float | None] | None:
    """
    Recalculated activity % for one location on one date.

    Uses the same rules as Check Daily Data (UTP/AP from DONE÷TOTAL, etc.).
    """
    if df is None or df.empty or not str(date_str).strip() or not str(location).strip():
        return None

    header_idx = _detect_header_row_index(df)
    header_row = df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)

    date_str_norm = _normalize_date_label(date_str)
    block_i = next(
        (
            i
            for i, d in enumerate(block_dates)
            if d == date_str
            or d == date_str_norm
            or _normalize_date_label(d) == date_str_norm
        ),
        None,
    )
    if block_i is None:
        return None

    _, act_cols = blocks[block_i]
    location_blocks = _iter_location_blocks(
        df, header_idx, location_col, progress_col
    )
    loc_norm = str(location).strip().upper()
    match = next(
        (block for block in location_blocks if str(block[0]).strip().upper() == loc_norm),
        None,
    )
    if match is None:
        return None

    _, done_row, total_row, percent_row = match
    _done, _total, pct_vals = _location_block_values(
        df, done_row, total_row, percent_row, act_cols
    )
    return pct_vals


def style_full_daily_complete_rows(snapshot: pd.DataFrame):
    """
    Full daily table: if every activity on a location's PERCENTAGE row is 100%,
    paint that whole PERCENTAGE row green and the location name (DONE row) green.
    """
    if snapshot is None or snapshot.empty:
        return snapshot

    act_cols = [c for c in ACTIVITIES if c in snapshot.columns]
    if not act_cols:
        return snapshot

    styles = pd.DataFrame("", index=snapshot.index, columns=snapshot.columns)
    green_row = "background-color: #C8E6C9; color: #1B5E20"
    green_loc = "background-color: #C8E6C9; color: #1B5E20; font-weight: 700"

    # Map location → DONE row index; check each PERCENTAGE row.
    current_loc = ""
    done_idx_by_loc: dict[str, object] = {}

    for idx, row in snapshot.iterrows():
        loc = str(row.get("Location", "") or "").strip()
        prog = str(row.get("Progress", "") or "").strip().upper()
        if prog == "DONE" and loc:
            current_loc = loc
            done_idx_by_loc[loc] = idx
            continue
        if prog != "PERCENTAGE" or not current_loc:
            continue

        pcts: list[float] = []
        all_hundred = True
        for col in act_cols:
            raw = str(row.get(col, "") or "").strip()
            if not raw or raw.upper() == "N/A":
                all_hundred = False
                break
            num = _parse_percent(raw)
            if num is None or abs(num - 100.0) > 0.05:
                all_hundred = False
                break
            pcts.append(num)

        if not all_hundred or len(pcts) != len(act_cols):
            continue

        for col in snapshot.columns:
            styles.at[idx, col] = green_row
        done_idx = done_idx_by_loc.get(current_loc)
        if done_idx is not None and "Location" in styles.columns:
            styles.at[done_idx, "Location"] = green_loc

    return snapshot.style.apply(lambda _: styles, axis=None)


__all__ = [
    "LocationProgress",
    "available_dates",
    "campus_date_snapshot",
    "location_recalculated_percentages",
    "induk_grouped_snapshot",
    "style_full_daily_complete_rows",
    "get_campus_overall",
    "get_induk_desa_overall",
    "induk_desa_building_increases",
    "location_change_summary",
    "location_changes_by_building",
    "parse_progress_sheet",
    "sheet_overall_percent",
    "campus_sheets_summary",
    "aggregate_overall_by_date",
    "locations_activity_timeseries",
]


def _find_summary_row(
    df: pd.DataFrame, location_col: int, progress_col: int, labels: set[str]
) -> int | None:
    """Locate a bottom summary row by location/progress label."""
    for row_idx in range(len(df) - 1, max(-1, len(df) - 40), -1):
        label = _row_label(df, row_idx, location_col, progress_col)
        if label in labels:
            return row_idx
    return None


def _find_average_percentage_row(
    df: pd.DataFrame, location_col: int, progress_col: int
) -> int | None:
    """Locate the bottom AVERAGE PERCENTAGE summary row."""
    return _find_summary_row(
        df, location_col, progress_col, {"AVERAGE PERCENTAGE", "AVERAGE PERCENT"}
    )


def _parse_overall_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Non-INDUK campus AVERAGE series.

    UTP / AP / Slab / Rack / MultiGE: DONE/TOTAL sums.
    Trunking: mean of location %.
    Fiber: derived DONE/TOTAL average.
    Controller / RFS: sheet TOTAL DONE / OVERALL TOTAL (recalc %).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    header_idx = _detect_header_row_index(df)
    header_row, subheader_row = _header_subheader(df, header_idx)
    location_col, progress_col = _detect_location_progress_cols(header_row)
    blocks = _find_date_blocks(header_row)
    block_dates = _extract_dates_for_blocks(df, blocks)
    avg_row_idx = _find_average_percentage_row(df, location_col, progress_col)
    done_row_idx = _find_summary_row(df, location_col, progress_col, {"TOTAL DONE"})
    total_row_idx = _find_summary_row(df, location_col, progress_col, {"OVERALL TOTAL"})
    if not blocks:
        return pd.DataFrame()

    location_blocks = _iter_location_blocks(df, header_idx, location_col, progress_col)
    avg_row = df.iloc[avg_row_idx] if avg_row_idx is not None else None
    done_row = df.iloc[done_row_idx] if done_row_idx is not None else None
    total_row = df.iloc[total_row_idx] if total_row_idx is not None else None
    records: list[dict] = []
    for date_label, (_, act_cols) in zip(block_dates, blocks):
        if not date_label:
            continue
        eq_cols = _equipment_cols(
            act_cols,
            len(df.columns),
            header_row=header_row,
            subheader_row=subheader_row,
        )
        record: dict = {"Date": _normalize_date_label(date_label)}
        sum_acts = list(
            dict.fromkeys(
                list(TRUSTED_DONE_TOTAL_ACTIVITIES) + list(PCT_DERIVED_DONE_EXACT)
            )
        )
        sum_done, sum_total = _sum_location_done_total(
            location_blocks,
            df,
            act_cols,
            sum_acts,
            eq_cols=eq_cols,
        )
        derived_avg = _average_percent_from_totals(
            sum_done, sum_total, columns=list(PCT_DERIVED_DONE_EXACT)
        )
        for act_name, col_idx in zip(ACTIVITIES, act_cols):
            if act_name in LOCATION_MEAN_PCT_ACTIVITIES:
                record[act_name] = _mean_location_percent(
                    location_blocks, df, act_cols, act_name
                )
            elif act_name in TRUSTED_DONE_TOTAL_ACTIVITIES:
                d = sum_done.get(act_name)
                t = sum_total.get(act_name)
                if d is not None and t is not None and t != 0:
                    record[act_name] = round(d / t * 100, 2)
                else:
                    d = (
                        _parse_number(done_row.iloc[col_idx])
                        if done_row is not None and col_idx < len(done_row)
                        else None
                    )
                    t = (
                        _parse_number(total_row.iloc[col_idx])
                        if total_row is not None and col_idx < len(total_row)
                        else None
                    )
                    record[act_name] = (
                        round(d / t * 100, 2) if d is not None and t else None
                    )
            elif act_name in PCT_DERIVED_DONE_EXACT:
                record[act_name] = derived_avg.get(act_name)
            elif avg_row is not None and col_idx < len(avg_row):
                record[act_name] = _parse_percent(avg_row.iloc[col_idx])
            else:
                record[act_name] = None

        for act_name in FRACTION_METRIC_ACTIVITIES:
            if act_name in ACTIVITIES:
                d = sum_done.get(act_name)
                t = sum_total.get(act_name)
                if d is None or t is None:
                    try:
                        col_idx = act_cols[ACTIVITIES.index(act_name)]
                    except (ValueError, IndexError):
                        continue
                    d = (
                        _parse_number(done_row.iloc[col_idx])
                        if done_row is not None and col_idx < len(done_row)
                        else None
                    )
                    t = (
                        _parse_number(total_row.iloc[col_idx])
                        if total_row is not None and col_idx < len(total_row)
                        else None
                    )
                _attach_fraction_fields(record, act_name, d, t)

        if "MultiGE Switch" in FRACTION_METRIC_ACTIVITIES:
            _attach_fraction_fields(
                record,
                "MultiGE Switch",
                sum_done.get("MultiGE Switch"),
                sum_total.get("MultiGE Switch"),
            )

        summary_eq = _read_summary_only_equipment(
            df, act_cols, location_col, progress_col, eq_cols
        )
        for eq_name in SUMMARY_ONLY_EQUIPMENT:
            if eq_name in FRACTION_METRIC_ACTIVITIES:
                d, t = summary_eq.get(eq_name, (None, None))
                _attach_fraction_fields(record, eq_name, d, t)

        if any(record.get(a) is not None for a in ACTIVITIES) or any(
            record.get(f"{a}__total") is not None for a in FRACTION_METRIC_ACTIVITIES
        ):
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
    """
    Cross-campus dashboard series.

    UTP Point / AP Mounting: sum DONE and TOTAL across campuses per date,
    then fraction = Total Done / Overall Total.
    Other activities: mean of campus % values for that date.
    """
    pct_buckets: dict[tuple[str, str], list[float]] = {}
    done_sums: dict[tuple[str, str], float] = {}
    total_sums: dict[tuple[str, str], float] = {}
    has_done: dict[tuple[str, str], bool] = {}
    has_total: dict[tuple[str, str], bool] = {}

    for name in campus_sheet_names():
        overall = parsed.get(name, {}).get("overall", pd.DataFrame())
        if overall is None or overall.empty:
            continue
        for _, row in overall.iterrows():
            date_str = row.get("Date")
            if not date_str:
                continue
            date_key = str(date_str)
            for act in ACTIVITIES:
                val = row.get(act)
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    pct_buckets.setdefault((date_key, act), []).append(float(val))
            for act in OVERALL_FRACTION_ACTIVITIES:
                d = row.get(f"{act}__done")
                t = row.get(f"{act}__total")
                if d is not None and not (isinstance(d, float) and pd.isna(d)):
                    key = (date_key, act)
                    done_sums[key] = done_sums.get(key, 0.0) + float(d)
                    has_done[key] = True
                if t is not None and not (isinstance(t, float) and pd.isna(t)):
                    key = (date_key, act)
                    total_sums[key] = total_sums.get(key, 0.0) + float(t)
                    has_total[key] = True

    dates = sorted(
        {d for d, _ in pct_buckets.keys()}
        | {d for d, _ in done_sums.keys()}
        | {d for d, _ in total_sums.keys()},
        key=_parse_date_key,
    )
    if not dates:
        return pd.DataFrame()

    records = []
    for date_str in dates:
        record: dict = {"Date": date_str}
        for act in ACTIVITIES:
            if act in OVERALL_FRACTION_ACTIVITIES:
                continue
            values = pct_buckets.get((date_str, act), [])
            record[act] = round(sum(values) / len(values), 2) if values else None
        for act in OVERALL_FRACTION_ACTIVITIES:
            d = done_sums.get((date_str, act)) if has_done.get((date_str, act)) else None
            t = total_sums.get((date_str, act)) if has_total.get((date_str, act)) else None
            _attach_fraction_fields(record, act, d, t)
        if any(record.get(a) is not None for a in ACTIVITIES) or any(
            record.get(f"{a}__total") is not None for a in OVERALL_FRACTION_ACTIVITIES
        ):
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
