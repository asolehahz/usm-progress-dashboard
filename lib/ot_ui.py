"""Shared OT Staff UI used by the standalone ot_app and (optionally) main app."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib.ot_staff import (
    all_staff_ot_summary,
    append_total_row,
    attach_payment_periods,
    detail_table_for_display,
    earliest_ot_date,
    filter_jabatan,
    filter_payment_period,
    filter_staff,
    jabatan_units,
    latest_ot_date,
    payment_period_label,
    payment_period_options,
    payment_period_ot_summary,
    staff_names,
)
from lib.sheets_client import fetch_ot_pic, fetch_ot_ptd


def _payment_select(
    df: pd.DataFrame,
    first_date: date | None,
    last_date: date | None,
    key: str,
) -> tuple[str, pd.DataFrame]:
    """Payment period dropdown → (selection label, filtered frame)."""
    options = payment_period_options(df, first_date, last_date=last_date)
    labels = ["All payments"] + [label for _num, label in options]
    selected = st.selectbox("Select payment", options=labels, key=key)
    view = filter_payment_period(df, selected, first_date)
    return selected, view


def _show_payment_totals(
    df: pd.DataFrame,
    role: str,
    first_date: date | None,
    last_date: date | None,
    title: str,
):
    """Summary metrics: overall total + each payment (1st, 2nd, …), then table."""
    tagged = attach_payment_periods(df, first_date)
    summary = payment_period_ot_summary(
        tagged,
        role,
        first_date,
        last_date=last_date,
        include_total=True,
        only_present=True,
    )
    st.subheader(title)
    if summary.empty:
        st.info("No payment totals to show.")
        return summary

    display = summary.drop(columns=["Payment #"], errors="ignore")
    period_rows = summary[
        summary["Payment"].astype(str).str.strip().str.lower() != "overall total"
    ].copy()
    overall_pay = (
        float(period_rows["Total Pay (RM)"].sum()) if not period_rows.empty else 0.0
    )
    overall_hours = (
        float(period_rows["Total Hours"].sum()) if not period_rows.empty else 0.0
    )

    # Highlight overall total + 1st payment (then 2nd, 3rd… if present)
    metric_items: list[tuple[str, str]] = [
        ("Overall total (RM)", f"{overall_pay:,.2f}"),
        ("Overall total (hours)", f"{overall_hours:.2f}"),
    ]
    for _, row in period_rows.sort_values("Payment #").iterrows():
        num = row.get("Payment #")
        try:
            num_i = int(num)
        except (TypeError, ValueError):
            continue
        short = (
            payment_period_label(first_date, num_i).split(" (")[0]
            if first_date is not None
            else f"Payment {num_i}"
        )
        metric_items.append(
            (f"{short} (RM)", f"{float(row['Total Pay (RM)']):,.2f}")
        )

    # Show up to 4 metrics per row
    for i in range(0, len(metric_items), 4):
        chunk = metric_items[i : i + 4]
        cols = st.columns(len(chunk))
        for col, (label, value) in zip(cols, chunk):
            col.metric(label, value)

    st.dataframe(display, width="stretch", hide_index=True)
    return summary


def render_ot_role_tab(
    df: pd.DataFrame,
    role: str,
    key_prefix: str,
    first_date: date | None,
    last_date: date | None,
):
    """One OT role tab: jabatan → staff → payment periods + TOTAL + details."""
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

    staff_last = latest_ot_date(staff_df) or last_date
    _show_payment_totals(
        staff_df,
        role,
        first_date,
        staff_last,
        f"{staff} — all payments",
    )

    selected_payment, view_df = _payment_select(
        staff_df, first_date, staff_last, f"{key_prefix}_payment"
    )
    st.subheader(
        "OT details"
        if selected_payment == "All payments"
        else f"OT details — {selected_payment}"
    )
    if view_df.empty:
        st.warning("No OT rows for this payment.")
        return
    st.dataframe(
        detail_table_for_display(view_df),
        width="stretch",
        hide_index=True,
    )


def render_overall_pay_role(
    df: pd.DataFrame,
    role: str,
    key_prefix: str,
    first_date: date | None,
    last_date: date | None,
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
    unit_last = latest_ot_date(unit_df) or last_date
    jabatan_label = (
        selected_jabatan if selected_jabatan != "All" else "all units"
    )

    _show_payment_totals(
        unit_df,
        role,
        first_date,
        unit_last,
        f"Overall Pay {role} — {jabatan_label}",
    )

    selected_payment, view_df = _payment_select(
        unit_df, first_date, unit_last, f"{key_prefix}_payment"
    )
    staff_summary = all_staff_ot_summary(view_df, role)
    st.subheader(
        "By staff"
        if selected_payment == "All payments"
        else f"By staff — {selected_payment}"
    )
    if staff_summary.empty:
        st.info("No staff OT totals to show.")
        return

    staff_summary = append_total_row(staff_summary, "Nama Staf", label="Overall total")
    data_rows = staff_summary[staff_summary["Nama Staf"] != "Overall total"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Staff", len(data_rows))
    c2.metric(
        "Overall total (hours)",
        f"{float(data_rows['Total Hours'].sum()) if not data_rows.empty else 0:.2f}",
    )
    c3.metric(
        "Overall total (RM)",
        f"{float(data_rows['Total Pay (RM)'].sum()) if not data_rows.empty else 0:,.2f}",
    )
    st.dataframe(staff_summary, width="stretch", hide_index=True)


def render_overall_bayaran(
    df_ptd: pd.DataFrame,
    df_pic: pd.DataFrame,
    first_date: date | None,
    last_date: date | None,
):
    """Third top-level tab: overall pay for all staff, split PTD / PIC."""
    tab_ptd, tab_pic = st.tabs(["Overall Pay PTD", "Overall Pay PIC"])
    with tab_ptd:
        render_overall_pay_role(
            df_ptd, "PTD", "ot_overall_ptd", first_date, last_date
        )
    with tab_pic:
        render_overall_pay_role(
            df_pic, "PIC", "ot_overall_pic", first_date, last_date
        )


def render_ot_staff():
    st.header("OT Staff")
    df_ptd = fetch_ot_ptd()
    df_pic = fetch_ot_pic()
    first_date = earliest_ot_date(df_ptd, df_pic)
    last_date = latest_ot_date(df_ptd, df_pic)
    tab_ptd, tab_pic, tab_overall = st.tabs(
        ["OT PTD", "OT PIC", "Overall Bayaran"]
    )
    with tab_ptd:
        render_ot_role_tab(df_ptd, "PTD", "ot_ptd", first_date, last_date)
    with tab_pic:
        render_ot_role_tab(df_pic, "PIC", "ot_pic", first_date, last_date)
    with tab_overall:
        render_overall_bayaran(df_ptd, df_pic, first_date, last_date)
