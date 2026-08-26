"""Fetch data from public Google Sheets (read) and optional write via service account."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import streamlit as st

from app_config import (
    DETAILS_COLUMNS,
    DETAILS_GID,
    DETAILS_TAB_NAME,
    HISTORY_COLUMNS,
    HISTORY_GID,
    HISTORY_TAB_NAME,
    ISSUES_COLUMNS,
    ISSUES_GID,
    ISSUES_TAB_NAME,
    SHEET_ID,
    SHEET_TABS,
    WORK_PLAN_COLUMNS,
    WORK_PLAN_GID,
    WORK_PLAN_TAB_NAME,
)


def _export_url(gid: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&gid={gid}"
    )


@st.cache_data(ttl=300, show_spinner=False)
def fetch_csv(gid: str) -> pd.DataFrame:
    url = _export_url(gid)
    return pd.read_csv(url, header=None, keep_default_na=False)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_all_tabs() -> dict[str, pd.DataFrame]:
    return {name: fetch_csv(gid) for name, gid in SHEET_TABS.items()}


def _get_gspread_client():
    """Return authenticated gspread client if secrets are configured."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return None

    if "gcp_service_account" not in st.secrets:
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=scopes,
    )
    return gspread.authorize(creds)


def _parse_history_df(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    header = [str(c).strip() for c in raw.iloc[0]]
    if header[0].lower() != "date" and "Date" not in header:
        raw.columns = HISTORY_COLUMNS[: len(raw.columns)]
        return raw
    body = raw.iloc[1:].copy()
    body.columns = header[: len(body.columns)]
    return body.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_history() -> pd.DataFrame:
    """Load daily history tab; returns empty DataFrame with expected columns if missing."""
    if HISTORY_GID:
        try:
            return _parse_history_df(fetch_csv(HISTORY_GID))
        except Exception:
            pass

    client = _get_gspread_client()
    if client:
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            worksheet = spreadsheet.worksheet(HISTORY_TAB_NAME)
            return _parse_history_df(pd.DataFrame(worksheet.get_all_values()))
        except Exception:
            pass

    return pd.DataFrame(columns=HISTORY_COLUMNS)


def append_history_row(row: dict[str, Any]) -> bool:
    """Append a row to the Daily History sheet. Requires service account in secrets."""
    client = _get_gspread_client()
    if not client:
        return False

    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(HISTORY_TAB_NAME)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=HISTORY_TAB_NAME,
            rows=1000,
            cols=len(HISTORY_COLUMNS),
        )
        worksheet.append_row(HISTORY_COLUMNS)

    values = [str(row.get(col, "")) for col in HISTORY_COLUMNS]
    worksheet.append_row(values)
    fetch_csv.clear()
    fetch_history.clear()
    return True


def _parse_named_df(raw: pd.DataFrame, columns: list[str], first_header: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=columns)
    header = [str(c).strip() for c in raw.iloc[0]]
    if header and header[0].lower() != first_header.lower() and first_header not in header:
        raw.columns = columns[: len(raw.columns)]
        return raw
    body = raw.iloc[1:].copy()
    body.columns = header[: len(body.columns)]
    # Keep only known columns when present
    for col in columns:
        if col not in body.columns:
            body[col] = ""
    return body[columns].reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_issues() -> pd.DataFrame:
    """Load Issue & Risk tab; empty frame with expected columns if missing."""
    if ISSUES_GID:
        try:
            return _parse_named_df(fetch_csv(ISSUES_GID), ISSUES_COLUMNS, "No")
        except Exception:
            pass

    client = _get_gspread_client()
    if client:
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            worksheet = spreadsheet.worksheet(ISSUES_TAB_NAME)
            return _parse_named_df(
                pd.DataFrame(worksheet.get_all_values()), ISSUES_COLUMNS, "No"
            )
        except Exception:
            pass

    return pd.DataFrame(columns=ISSUES_COLUMNS)


def _parse_work_plan_df(raw: pd.DataFrame) -> pd.DataFrame:
    from lib.work_plan import parse_work_plan

    return parse_work_plan(raw)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_work_plan() -> pd.DataFrame:
    """Load Work Plan VS Actual tab."""
    if WORK_PLAN_GID:
        try:
            return _parse_work_plan_df(fetch_csv(WORK_PLAN_GID))
        except Exception:
            pass

    client = _get_gspread_client()
    if client:
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            worksheet = spreadsheet.worksheet(WORK_PLAN_TAB_NAME)
            return _parse_work_plan_df(pd.DataFrame(worksheet.get_all_values()))
        except Exception:
            pass

    return pd.DataFrame(columns=WORK_PLAN_COLUMNS)


def _parse_details_df(raw: pd.DataFrame) -> pd.DataFrame:
    from lib.details import parse_details

    return parse_details(raw)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_details() -> pd.DataFrame:
    """Load DETAILS tab."""
    if DETAILS_GID:
        try:
            return _parse_details_df(fetch_csv(DETAILS_GID))
        except Exception:
            pass

    client = _get_gspread_client()
    if client:
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            worksheet = spreadsheet.worksheet(DETAILS_TAB_NAME)
            return _parse_details_df(pd.DataFrame(worksheet.get_all_values()))
        except Exception:
            pass

    return pd.DataFrame(columns=DETAILS_COLUMNS)


def sync_details_sheet(rows: list[list[str]]) -> bool:
    """
    Replace DETAILS sheet contents with header + data rows.
    Requires service account in Streamlit secrets.
    """
    client = _get_gspread_client()
    if not client:
        return False

    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(DETAILS_TAB_NAME)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=DETAILS_TAB_NAME,
            rows=max(1000, len(rows) + 10),
            cols=len(rows[0]) if rows else 5,
        )

    worksheet.clear()
    if rows:
        # gspread: update starting at A1
        worksheet.update(range_name="A1", values=rows, value_input_option="USER_ENTERED")
    fetch_csv.clear()
    fetch_details.clear()
    return True


def update_details_fields(
    campus: str, location: str, *, critical: str, remarks: str
) -> bool:
    """Update Critical / Remarks for one location row. Requires service account."""
    client = _get_gspread_client()
    if not client:
        return False

    try:
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet(DETAILS_TAB_NAME)
    except Exception:
        return False

    values = worksheet.get_all_values()
    if not values:
        return False

    # Find header row that contains Campus + Location
    header_idx = None
    header: list[str] = []
    for i, row in enumerate(values[:5]):
        cells = [str(c).strip().lower() for c in row]
        if "campus" in cells and "location" in cells:
            header_idx = i
            header = [str(c).strip() for c in row]
            break
    if header_idx is None:
        return False

    col_campus = col_location = col_critical = col_remarks = None
    for idx, name in enumerate(header):
        low = name.lower()
        if low == "campus":
            col_campus = idx
        elif low == "location":
            col_location = idx
        elif "critical" in low:
            col_critical = idx
        elif "remark" in low:
            col_remarks = idx

    if col_campus is None or col_location is None:
        return False

    campus_t = str(campus).strip()
    location_t = str(location).strip()
    for i, row in enumerate(values[header_idx + 1 :], start=header_idx + 2):
        c = str(row[col_campus]).strip() if len(row) > col_campus else ""
        loc = str(row[col_location]).strip() if len(row) > col_location else ""
        if c == campus_t and loc == location_t:
            if col_critical is not None:
                worksheet.update_cell(i, col_critical + 1, critical)
            if col_remarks is not None:
                worksheet.update_cell(i, col_remarks + 1, remarks)
            fetch_csv.clear()
            fetch_details.clear()
            return True
    return False


def append_issue_row(row: dict[str, Any]) -> bool:
    """Append a row to Issue & Risk sheet. Requires service account in secrets."""
    client = _get_gspread_client()
    if not client:
        return False

    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(ISSUES_TAB_NAME)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=ISSUES_TAB_NAME,
            rows=1000,
            cols=len(ISSUES_COLUMNS),
        )
        worksheet.append_row(ISSUES_COLUMNS)

    values = [str(row.get(col, "")) for col in ISSUES_COLUMNS]
    worksheet.append_row(values)
    fetch_csv.clear()
    fetch_issues.clear()
    return True


def update_issue_status(issue_no: str, status: str) -> bool:
    """Update Status for a matching No value. Requires service account."""
    client = _get_gspread_client()
    if not client:
        return False

    try:
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet(ISSUES_TAB_NAME)
    except Exception:
        return False

    rows = worksheet.get_all_values()
    if not rows:
        return False

    header = [str(c).strip() for c in rows[0]]
    try:
        no_idx = header.index("No")
        status_idx = header.index("Status")
    except ValueError:
        return False

    target = str(issue_no).strip()
    for i, row in enumerate(rows[1:], start=2):
        if len(row) > no_idx and str(row[no_idx]).strip() == target:
            worksheet.update_cell(i, status_idx + 1, status)
            fetch_csv.clear()
            fetch_issues.clear()
            return True
    return False
