"""
USM OT Staff PTD — standalone Streamlit website (PTD only, no PIC).

Run locally:
    streamlit run ot_app.py

Streamlit Cloud: New app → same repo → Main file path = ot_app.py
(PIC-only share app uses ot_pic_app.py instead.)
"""

from __future__ import annotations

import streamlit as st

from lib.ot_ui import render_ot_role_tab, render_overall_pay_role
from lib.ot_staff import earliest_ot_date, latest_ot_date
from lib.sheets_client import fetch_csv, fetch_ot_ptd

st.set_page_config(
    page_title="USM OT Staff PTD",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #4B2876 0%, #3A1F5C 100%);
    }
    [data-testid="stSidebar"] * { color: #FFFFFF !important; }
    [data-testid="stSidebar"] .sidebar-brand {
        padding: 0.5rem 0 1rem 0;
    }
    [data-testid="stSidebar"] .sidebar-brand h2 {
        margin: 0;
        color: #FFFFFF !important;
        font-size: 1.35rem;
    }
    [data-testid="stSidebar"] .sidebar-brand p {
        margin: 0.25rem 0 0 0;
        opacity: 0.9;
        font-size: 0.9rem;
    }
    div[data-testid="stButton"] button {
        background: linear-gradient(90deg, #F7941D, #FFB347) !important;
        color: #4B2876 !important;
        border: none !important;
        font-weight: 600 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_ot_ptd_only():
    """PTD-only OT website (no PIC)."""
    st.header("OT Staff PTD")
    df_ptd = fetch_ot_ptd()
    first_date = earliest_ot_date(df_ptd)
    last_date = latest_ot_date(df_ptd)
    tab_ptd, tab_overall = st.tabs(["OT PTD", "Overall Bayaran"])
    with tab_ptd:
        render_ot_role_tab(df_ptd, "PTD", "ot_ptd_share", first_date, last_date)
    with tab_overall:
        render_overall_pay_role(
            df_ptd, "PTD", "ot_ptd_share_overall", first_date, last_date
        )


def main():
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <h2>USM OT Staff PTD</h2>
            <p>PTD overtime only</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Refresh data"):
        fetch_csv.clear()
        fetch_ot_ptd.clear()
        st.rerun()

    render_ot_ptd_only()


if __name__ == "__main__":
    main()
