"""Shared OT Staff UI used by the standalone ot_app and (optionally) main app."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.ot_staff import (
    all_staff_ot_summary,
    detail_table_for_display,
    earliest_ot_date,
    filter_jabatan,
    filter_payment_period,
    filter_staff,
    jabatan_units,
    payment_period_options,
    payment_period_ot_summary,
    staff_names,
)
from lib.sheets_client import fetch_ot_pic, fetch_ot_ptd


def _payment_select(
    df: pd.DataFrame, first_date: date | None, key: str
) -> tuple[str, pd.DataFrame]:
    """Payment period dropdown → (selection label, filtered frame)."""
    options = payment_period_options(df, first_date)
    labels = ["All payments"] + [label for _num, label in options]
    selected = st.selectbox("Select payment", options=labels, key=key)
    view = filter_payment_period(df, selected, first_date)
    return selected, view


def render_ot_role_tab(
    df: pd.DataFrame, role: str, key_prefix: str, first_date: date | None
):
    """One OT role tab: jabatan → staff → payment period, then summary + detail."""
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

    selected_payment, view_df = _payment_select(
        staff_df, first_date, f"{key_prefix}_payment"
    )
    if view_df.empty:
        st.warning("No OT rows for this payment.")
        return

    summary = payment_period_ot_summary(view_df, role)
    title_pay = (
        selected_payment
        if selected_payment != "All payments"
        else "all payments"
    )
    st.subheader(f"{staff} — {title_pay}")
    if summary.empty:
        st.info("No payment totals to show.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Payments", len(summary))
        c2.metric("Total OT hours", f"{summary['Total Hours'].sum():.2f}")
        c3.metric(
            "Amount to be paid (RM)",
            f"{summary['Total Pay (RM)'].sum():,.2f}",
        )
        st.dataframe(summary, width="stretch", hide_index=True)

    st.subheader("OT details")
    st.dataframe(
        detail_table_for_display(view_df),
        width="stretch",
        hide_index=True,
    )


def render_overall_pay_role(
    df: pd.DataFrame, role: str, key_prefix: str, first_date: date | None
):
    """Overall bayaran for all staff in one role (PTD or PIC)."""
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

    selected_payment, view_df = _payment_select(
        unit_df, first_date, f"{key_prefix}_payment"
    )
    if view_df.empty:
        st.warning("No OT rows for this filter.")
        return

    staff_summary = all_staff_ot_summary(view_df, role)
    period_summary = payment_period_ot_summary(view_df, role)
    title_pay = (
        selected_payment
        if selected_payment != "All payments"
        else "all payments"
    )
    jabatan_label = (
        selected_jabatan if selected_jabatan != "All" else "all units"
    )
    st.subheader(f"Overall Pay {role} — {jabatan_label} — {title_pay}")
    if staff_summary.empty:
        st.info("No staff OT totals to show.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Staff", len(staff_summary))
    c2.metric("Total OT hours", f"{staff_summary['Total Hours'].sum():.2f}")
    c3.metric(
        "Amount to be paid (RM)",
        f"{staff_summary['Total Pay (RM)'].sum():,.2f}",
    )
    if not period_summary.empty and selected_payment == "All payments":
        st.dataframe(period_summary, width="stretch", hide_index=True)
    st.dataframe(staff_summary, width="stretch", hide_index=True)


def render_overall_bayaran(
    df_ptd: pd.DataFrame, df_pic: pd.DataFrame, first_date: date | None
):
    """Third top-level tab: overall pay for all staff, split PTD / PIC."""
    tab_ptd, tab_pic = st.tabs(["Overall Pay PTD", "Overall Pay PIC"])
    with tab_ptd:
        render_overall_pay_role(df_ptd, "PTD", "ot_overall_ptd", first_date)
    with tab_pic:
        render_overall_pay_role(df_pic, "PIC", "ot_overall_pic", first_date)


def render_ot_staff():
    st.header("OT Staff")
    df_ptd = fetch_ot_ptd()
    df_pic = fetch_ot_pic()
    first_date = earliest_ot_date(df_ptd, df_pic)
    tab_ptd, tab_pic, tab_overall = st.tabs(
        ["OT PTD", "OT PIC", "Overall Bayaran"]
    )
    with tab_ptd:
        render_ot_role_tab(df_ptd, "PTD", "ot_ptd", first_date)
    with tab_pic:
        render_ot_role_tab(df_pic, "PIC", "ot_pic", first_date)
    with tab_overall:
        render_overall_bayaran(df_ptd, df_pic, first_date)
