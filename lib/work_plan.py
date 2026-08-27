"""Work Plan vs Actual — read plan sheet and fill reported changes from progress data."""

from __future__ import annotations

import re

import pandas as pd

from app_config import ACTIVITIES, WORK_PLAN_COLUMNS, campus_sheet_names
from lib.data_parser import (
    _normalize_date_label,
    _parse_date_key,
    available_dates,
    location_changes_by_building,
)


def _normalize_location_key(location: str) -> str:
    """
    Fuzzy key so plan labels match progress sheet names.

    Examples:
      'K05 - DS Aman Damai'     → 'K05'
      'Blok SH1' / 'Blok SH 1'  → 'SH1'
      '- Blok Desasiswa Murni 1' / 'Desasiswa Murni 1' → 'MURNI1'
      'Desasiswa Murni 5 & 6' / 'Desasiswa Murni 5&6' → 'MURNI56'
    """
    text = str(location or "").strip().upper()
    # Strip leading bullets / dashes / weird chars
    text = re.sub(r"^[^A-Z0-9]+", "", text)
    # Common typo: letter O instead of zero
    text = re.sub(r"\bK[O](\d)\b", r"K0\1", text)
    text = text.replace("KO8", "K08")

    # Prefer explicit building code K01 / H06 / L12 / M03 / F25
    code = re.search(r"\b([A-Z]\d{2})\b", text)
    if code:
        return code.group(1)

    # SH blocks: Blok SH1 / Blok SH 1 / SH1
    sh = re.search(r"\bSH\s*(\d+)\b", text)
    if sh:
        return f"SH{sh.group(1)}"

    # Strip common prefixes then compress
    text = re.sub(r"\b(BLOK|BLOCK|DESASISWA|DS)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", "", text)
    return text


def _location_match_keys(location: str) -> list[str]:
    """All lookup keys for one location label."""
    keys: list[str] = []
    primary = _normalize_location_key(location)
    if primary:
        keys.append(primary)
    # Also keep a compressed full-string key as fallback
    compact = re.sub(r"[^A-Z0-9]+", "", str(location or "").strip().upper())
    compact = re.sub(r"^[^A-Z0-9]+", "", compact)
    if compact and compact not in keys:
        keys.append(compact)
    return keys


def work_type_to_activities(work_type: str) -> list[str]:
    """Map free-text plan work type to progress activity columns."""
    key = str(work_type or "").strip().lower()
    if not key:
        return list(ACTIVITIES)

    acts: list[str] = []
    if "trunking" in key:
        acts.append("Trunking")
    if "cabling" in key or "lay cable" in key:
        acts.extend(["Lay Cable", "Termination"])
    if "termination" in key and "Termination" not in acts:
        acts.append("Termination")
    if re.search(r"\bap\b", key) or "ap mounting" in key:
        acts.append("AP Mounting")
    if "utp" in key:
        acts.append("UTP Point")
    if "fiber" in key:
        acts.append("Fiber Optic")
    if "slab" in key or "coring" in key:
        acts.append("Slab Coring (hole)")
    if "rack" in key:
        acts.append("Rack Installation (nos)")

    # Deduplicate, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for a in acts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out if out else list(ACTIVITIES)


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


def _previous_progress_date(df: pd.DataFrame, selected: str) -> str | None:
    dates = available_dates(df, newest_first=False)
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


def _index_changes_by_location_keys(
    changes_by_code: dict[str, dict[str, str]],
    raw_df: pd.DataFrame,
) -> dict[str, dict[str, str]]:
    """
    Expand building-code lookup with fuzzy location keys from sheet names
    so plan labels like 'Blok SH1' match progress 'Blok SH 1'.
    """
    from lib.data_parser import (
        _building_short_label,
        _detect_header_row_index,
        _detect_location_progress_cols,
        _iter_location_blocks,
    )

    indexed: dict[str, dict[str, str]] = {
        code.upper(): dict(acts) for code, acts in changes_by_code.items()
    }

    if raw_df is None or raw_df.empty:
        return indexed

    header_idx = _detect_header_row_index(raw_df)
    header_row = raw_df.iloc[header_idx]
    location_col, progress_col = _detect_location_progress_cols(header_row)
    for location, *_ in _iter_location_blocks(
        raw_df, header_idx, location_col, progress_col
    ):
        code = _building_short_label(location).upper()
        acts = changes_by_code.get(code) or changes_by_code.get(code.strip())
        if not acts:
            # Fallback: match by normalized key equality against stored keys
            loc_keys = set(_location_match_keys(location))
            for stored_key, stored_acts in changes_by_code.items():
                if stored_key.upper() in loc_keys or _normalize_location_key(
                    stored_key
                ) in loc_keys:
                    acts = stored_acts
                    break
        if not acts:
            continue
        for key in _location_match_keys(location):
            indexed[key] = acts

    return indexed


def _collect_changes_across_campuses(
    parsed: dict[str, dict], selected_date: str
) -> tuple[dict[str, dict[str, str]], str | None]:
    """
    Merge progress deltas from all campus sheets for selected_date vs previous.
    Returns (lookup_by_normalized_key, example_prev_date).
    """
    selected_norm = _normalize_date_label(selected_date)
    merged: dict[str, dict[str, str]] = {}
    prev_used: str | None = None

    for campus in campus_sheet_names():
        raw_df = parsed.get(campus, {}).get("raw_df")
        if raw_df is None or getattr(raw_df, "empty", True):
            continue
        date_list = available_dates(raw_df, newest_first=False)
        dates = {_normalize_date_label(d) for d in date_list}
        if selected_norm not in dates:
            continue

        prev_date = _previous_progress_date(raw_df, selected_date)
        if not prev_date:
            continue
        prev_used = prev_used or prev_date

        by_code = location_changes_by_building(raw_df, prev_date, selected_date)
        indexed = _index_changes_by_location_keys(by_code, raw_df)

        for key, acts in indexed.items():
            if key not in merged:
                merged[key] = dict(acts)
            else:
                merged[key].update(acts)

    return merged, prev_used


def _lookup_location_changes(
    changes: dict[str, dict[str, str]], plan_location: str
) -> dict[str, str]:
    for key in _location_match_keys(plan_location):
        if key in changes:
            return changes[key]
    return {}


def build_work_plan_view(
    plan: pd.DataFrame,
    parsed_or_induk: dict[str, dict] | pd.DataFrame,
    selected_date: str,
) -> tuple[pd.DataFrame, str | None]:
    """
    Filter plan rows for selected_date and fill Reported changes from progress.

    Accepts full parsed campus dict (preferred) or a single INDUK raw_df for
    backward compatibility.
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

    if isinstance(parsed_or_induk, dict):
        changes_by_key, prev_date = _collect_changes_across_campuses(
            parsed_or_induk, selected_date
        )
    else:
        # Legacy: single campus dataframe (INDUK)
        induk_df = parsed_or_induk
        prev_date = _previous_progress_date(induk_df, selected_date)
        changes_by_key = {}
        if induk_df is not None and not getattr(induk_df, "empty", True) and prev_date:
            by_code = location_changes_by_building(induk_df, prev_date, selected_date)
            changes_by_key = _index_changes_by_location_keys(by_code, induk_df)

    out_rows: list[dict[str, str]] = []
    for _, row in day_rows.iterrows():
        planned_acts = work_type_to_activities(row["Type_of_work"])
        reported = str(row.get("Reported_changes", "") or "").strip()

        if not reported:
            loc_changes = _lookup_location_changes(changes_by_key, row["Location"])
            if not prev_date:
                reported = "No earlier progress date to compare"
            elif not loc_changes:
                reported = "No change"
            else:
                matched = [
                    loc_changes[act] for act in planned_acts if act in loc_changes
                ]
                if matched:
                    reported = "; ".join(matched)
                else:
                    reported = "; ".join(loc_changes[a] for a in sorted(loc_changes))

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
