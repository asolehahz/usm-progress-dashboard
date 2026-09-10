"""Shared OT Staff UI used by the standalone ot_app and (optionally) main app."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_config import OT_RATES_RM_PER_HOUR
from lib.ot_staff import (
    all_staff_ot_summary,
    detail_table_for_display,
    filter_jabatan,
    filter_month,
    filter_staff,
    jabatan_units,
    monthly_ot_summary,
    staff_months,
    staff_names,
)
from lib.sheets_client import fetch_ot_pic, fetch_ot_ptd


def render_ot_role_tab(df: pd.DataFrame, role: str, key_prefix: str):
    """One OT role tab: jabatan → staff → month, then summary + detail rows."""
    rates = OT_RATES_RM_PER_HOUR.get(role.upper(), {})
    st.caption(
        f"Rates (**{role}**): "
        f"Hari biasa/bekerja RM {rates.get('Biasa', 0):.2f}/jam · "
        f"Hujung Minggu RM {rates.get('Hujung Minggu', 0):.2f}/jam · "
        f"Cuti Umum RM {rates.get('Cuti Umum', 0):.2f}/jam"
    )
    if df is None or df.empty:
        st.info(f"No staff rows found in OT STAFF {role} sheet.")
        return

    units = jabatan_units(df)
    jabatan_options = ["All"] + units
    selected_jabatan = st.selectbox(
        "Select Jabatan/Unit",
        options=jabatan_options,
        key=f"{key_prefix}_jabatan",
    )
    unit_df = filter_jabatan(df, selected_jabatan)
    names = staff_names(unit_df)
    if not names:
        st.info(
            "No staff found for this Jabatan/Unit."
            if selected_jabatan != "All"
            else f"No staff rows found in OT STAFF {role} sheet."
        )
        return

    staff = st.selectbox(
        "Select staff name",
        options=names,
        key=f"{key_prefix}_staff",
    )
    staff_df = filter_staff(unit_df, staff)
    if staff_df.empty:
        st.warning("No OT rows for this staff.")
        return

    months = staff_months(staff_df)
    month_options = ["All months"] + months
    selected_month = st.selectbox(
        "Select month",
        options=month_options,
        key=f"{key_prefix}_month",
    )
    view_df = filter_month(staff_df, selected_month)
    if view_df.empty:
        st.warning("No OT rows for this month.")
        return

    summary = monthly_ot_summary(view_df, role)
    title_month = (
        selected_month if selected_month != "All months" else "all months"
    )
    st.subheader(f"Overall OT — {staff} ({title_month})")
    if summary.empty:
        st.info("Could not group OT by month (check Tarikh format).")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Months", len(summary))
        c2.metric("Total OT hours", f"{summary['Total Hours'].sum():.2f}")
        c3.metric(
            "Total OT pay (RM)",
            f"{summary['Total Pay (RM)'].sum():,.2f}",
        )
        st.dataframe(summary, width="stretch", hide_index=True)

    st.subheader("OT details")
    st.dataframe(
        detail_table_for_display(view_df),
        width="stretch",
        hide_index=True,
    )


def render_overall_pay_role(df: pd.DataFrame, role: str, key_prefix: str):
    """Overall bayaran for all staff in one role (PTD or PIC)."""
    rates = OT_RATES_RM_PER_HOUR.get(role.upper(), {})
    st.caption(
        f"Rates (**{role}**): "
        f"Hari biasa/bekerja RM {rates.get('Biasa', 0):.2f}/jam · "
        f"Hujung Minggu RM {rates.get('Hujung Minggu', 0):.2f}/jam · "
        f"Cuti Umum RM {rates.get('Cuti Umum', 0):.2f}/jam"
    )
    if df is None or df.empty:
        st.info(f"No staff rows found in OT STAFF {role} sheet.")
        return

    units = jabatan_units(df)
    jabatan_options = ["All"] + units
    selected_jabatan = st.selectbox(
        "Select Jabatan/Unit",
        options=jabatan_options,
        key=f"{key_prefix}_jabatan",
    )
    unit_df = filter_jabatan(df, selected_jabatan)

    months = staff_months(unit_df)
    month_options = ["All months"] + months
    selected_month = st.selectbox(
        "Select month",
        options=month_options,
        key=f"{key_prefix}_month",
    )
    view_df = filter_month(unit_df, selected_month)
    if view_df.empty:
        st.warning("No OT rows for this filter.")
        return

    summary = all_staff_ot_summary(view_df, role)
    title_month = (
        selected_month if selected_month != "All months" else "all months"
    )
    jabatan_label = (
        selected_jabatan if selected_jabatan != "All" else "all units"
    )
    st.subheader(f"Overall Pay {role} — {jabatan_label} ({title_month})")
    if summary.empty:
        st.info("No staff OT totals to show.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Staff", len(summary))
    c2.metric("Total OT hours", f"{summary['Total Hours'].sum():.2f}")
    c3.metric(
        "Total OT pay (RM)",
        f"{summary['Total Pay (RM)'].sum():,.2f}",
    )
    st.dataframe(summary, width="stretch", hide_index=True)


def render_overall_bayaran(df_ptd: pd.DataFrame, df_pic: pd.DataFrame):
    """Third top-level tab: overall pay for all staff, split PTD / PIC."""
    st.caption(
        "Bayaran OT semua staff. Pilih **Overall Pay PTD** atau **Overall Pay PIC**, "
        "kemudian tapis Jabatan/Unit dan bulan."
    )
    tab_ptd, tab_pic = st.tabs(["Overall Pay PTD", "Overall Pay PIC"])
    with tab_ptd:
        render_overall_pay_role(df_ptd, "PTD", "ot_overall_ptd")
    with tab_pic:
        render_overall_pay_role(df_pic, "PIC", "ot_overall_pic")


def render_ot_staff():
    st.header("OT Staff")
    st.caption(
        "Overtime from **OT STAFF PTD** and **OT STAFF PIC** sheets. "
        "Per-staff tabs: Jabatan/Unit → name → month. "
        "**Overall Bayaran**: all-staff pay totals (PTD / PIC)."
    )
    df_ptd = fetch_ot_ptd()
    df_pic = fetch_ot_pic()
    tab_ptd, tab_pic, tab_overall = st.tabs(
        ["OT PTD", "OT PIC", "Overall Bayaran"]
    )
    with tab_ptd:
        render_ot_role_tab(df_ptd, "PTD", "ot_ptd")
    with tab_pic:
        render_ot_role_tab(df_pic, "PIC", "ot_pic")
    with tab_overall:
        render_overall_bayaran(df_ptd, df_pic)
