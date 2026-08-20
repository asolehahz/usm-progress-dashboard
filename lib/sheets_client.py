"""Fetch data from public Google Sheets (read) and optional write via service account."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import streamlit as st

from config import (
    HISTORY_COLUMNS,
    HISTORY_GID,
    HISTORY_TAB_NAME,
    SHEET_ID,
    SHEET_TABS,
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
