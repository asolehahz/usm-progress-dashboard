"""
USM Progress Dashboard — reads live data from Google Sheets.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import (
    ACTIVITIES,
    CAMPUS_ICONS,
    INDUK_LOCATION_GROUPS,
    SHEET_ID,
    campus_sheet_names,
    dashboard_select_options,
    parse_dashboard_selection,
)
from lib.auth import admin_login_form
from lib.data_parser import (
    aggregate_overall_by_date,
    available_dates,
    campus_date_snapshot,
    get_campus_overall,
    get_induk_desa_overall,
    parse_progress_sheet,
    sheet_overall_percent,
)
from lib.sheets_client import append_history_row, fetch_all_tabs, fetch_history

st.set_page_config(
    page_title="USM Progress Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Distinct hues so activity lines stay easy to tell apart
CHART_COLORS = [
    "#4B2876",  # purple
    "#F7941D",  # orange
    "#0077B6",  # blue
    "#2A9D8F",  # teal
    "#E63946",  # red
    "#6A994E",  # green
    "#C77DFF",  # violet
    "#BC6C25",  # brown
]
ACTIVITY_COLORS = {name: CHART_COLORS[i] for i, name in enumerate(ACTIVITIES)}

st.markdown(
    """
    <style>
    .stApp { background-color: #FFFFFF; }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #4B2876 0%, #3A1F5C 100%);
        border-right: none;
    }
    [data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] .sidebar-brand {
        background: #F7941D;
        color: #FFFFFF !important;
        padding: 1rem 1.1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
        text-align: center;
    }
    [data-testid="stSidebar"] .sidebar-brand h2 {
        color: #FFFFFF !important;
        margin: 0;
        font-size: 1.25rem;
        font-weight: 700;
    }
    [data-testid="stSidebar"] .sidebar-brand p {
        color: #FFF5E6 !important;
        margin: 0.25rem 0 0 0;
        font-size: 0.8rem;
    }
    [data-testid="stSidebar"] a {
        color: #FFD699 !important;
        font-weight: 600;
    }
    [data-testid="stSidebarNav"] a {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebarNav"] a:hover {
        background: rgba(247,148,29,0.35) !important;
    }
    [data-testid="stSidebarNav"] span {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] button {
        background: #F7941D !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] button:hover {
        background: #FFB347 !important;
        color: #4B2876 !important;
    }

    /* Main content */
    h1, h2, h3 { color: #4B2876 !important; }
    [data-testid="stMetricValue"] { color: #4B2876 !important; font-weight: 700; }
    [data-testid="stMetricLabel"] { color: #6B4E8C !important; }

    /* Campus cards */
    .campus-card {
        background: #FFFFFF;
        border: 2px solid #E8DFF5;
        border-left: 6px solid #F7941D;
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.5rem;
        box-shadow: 0 2px 8px rgba(75,40,118,0.08);
    }
    .campus-card:hover {
        border-color: #4B2876;
        box-shadow: 0 4px 14px rgba(75,40,118,0.15);
    }
    .campus-card-icon { font-size: 2rem; line-height: 1; }
    .campus-card-name {
        color: #4B2876;
        font-weight: 700;
        font-size: 1.05rem;
        margin: 0.4rem 0 0.15rem 0;
    }
    .campus-card-pct {
        color: #F7941D;
        font-size: 1.75rem;
        font-weight: 800;
        line-height: 1.1;
    }
    .campus-card-meta { color: #888; font-size: 0.85rem; }

    /* Campus open buttons */
    div[data-testid="stButton"] button[kind="secondary"],
    div.campus-card + div[data-testid="stButton"] button {
        background: linear-gradient(90deg, #4B2876, #6B3FA0) !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 0.6rem 1rem !important;
    }
    div[data-testid="stButton"] button[kind="secondary"]:hover,
    div.campus-card + div[data-testid="stButton"] button:hover {
        background: linear-gradient(90deg, #F7941D, #FFB347) !important;
        color: #4B2876 !important;
    }

    [data-testid="stExpander"] summary { color: #4B2876; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner="Loading data from Google Sheets…")
def load_data() -> dict[str, dict]:
    """Load and parse every tab defined in config.SHEET_TABS."""
    tabs = fetch_all_tabs()
    parsed: dict[str, dict] = {}
    for sheet_name, df in tabs.items():
        locations, _ = parse_progress_sheet(df, sheet_name=sheet_name)
        overall = get_campus_overall(df, sheet_name)
        parsed[sheet_name] = {"locations": locations, "overall": overall, "raw_df": df}
    return parsed


def render_activity_average_panel(overall: pd.DataFrame, title: str, caption: str = ""):
    """Show latest-date average % only (metric boxes, no historical chart)."""
    if overall is None or overall.empty:
        st.warning("No average percentage data found for this selection.")
        return

    latest = overall.iloc[-1]
    latest_date = latest.get("Date", "—")
    st.subheader(title)
    if caption:
        st.caption(caption)
    st.caption(f"Showing **latest data only** — date: **{latest_date}**")

    metric_cols = st.columns(4)
    for i, act in enumerate(ACTIVITIES):
        val = latest.get(act)
        display = f"{val:.1f}%" if val is not None and not pd.isna(val) else "N/A"
        metric_cols[i % 4].metric(act, display)


def render_dashboard(parsed: dict[str, dict]):
    st.header("Dashboard")

    selected = st.selectbox(
        "Select campus / desa to view average percentage",
        options=dashboard_select_options(),
        key="dashboard_campus_select",
    )
    campus, desa = parse_dashboard_selection(selected)

    if desa:
        raw_df = parsed.get("INDUK", {}).get("raw_df")
        overall = get_induk_desa_overall(raw_df, desa) if raw_df is not None else pd.DataFrame()
        render_activity_average_panel(
            overall,
            title=f"🏛️ Desa average % — {desa}",
            caption="Latest grouped % from INDUK (same desa groups as INDUK(DESA)).",
        )
        return

    overall = parsed.get(campus, {}).get("overall", pd.DataFrame())
    icon = CAMPUS_ICONS.get(campus, "🏫")
    extra = (
        " INDUK locations are grouped by desa before averaging."
        if campus == "INDUK"
        else ""
    )
    render_activity_average_panel(
        overall,
        title=f"{icon} Campus average % — {campus}",
        caption=f"Latest AVERAGE PERCENTAGE from the sheet.{extra}",
    )


def _campus_page_runner(campus: str):
    def _run():
        st.session_state["selected_campus"] = campus
        render_campus_detail(_load_or_fail(), campus=campus)

    return _run


def _campus_url(name: str) -> str:
    return name.lower().replace(" ", "-")


CAMPUS_PAGES = {
    name: st.Page(
        _campus_page_runner(name),
        title=name,
        icon=CAMPUS_ICONS.get(name, "🏫"),
        url_path=_campus_url(name),
    )
    for name in campus_sheet_names()
}


def render_campus_detail(parsed: dict[str, dict], campus: str | None = None):
    campus_names = campus_sheet_names()
    if campus not in campus_names:
        campus = st.session_state.get("selected_campus", campus_names[0])
    st.session_state["selected_campus"] = campus
    st.header(f"Check Daily Data — {campus}")
    st.caption(
        "Excel-style view for one date: DONE, TOTAL, PERCENTAGE (including Active Equipment: "
        "Controller, Access Switch, Dist. Switch), plus TOTAL DONE / OVERALL TOTAL / "
        "AVERAGE PERCENTAGE. Empty cells show as N/A."
        + (
            " INDUK locations are grouped by desa before totals and percentages are calculated."
            if campus == "INDUK"
            else ""
        )
    )

    data = parsed.get(campus, {})
    locations = data.get("locations", [])
    overall = data.get("overall")
    raw_df = data.get("raw_df")

    if raw_df is None or getattr(raw_df, "empty", True):
        st.info(f"No sheet data loaded for **{campus}**.")
        return

    icon = CAMPUS_ICONS.get(campus, "🏫")
    overall_df = overall if overall is not None else pd.DataFrame()
    avg = sheet_overall_percent(locations, overall_df)
    loc_count = len(INDUK_LOCATION_GROUPS) if campus == "INDUK" else len(locations)

    c1, c2, c3 = st.columns(3)
    c1.metric(f"{icon} Campus", campus)
    c2.metric("Latest average %", f"{avg:.1f}%")
    c3.metric("Locations tracked", loc_count)

    daily_dates = available_dates(raw_df)
    if not daily_dates:
        st.warning("No date blocks found in this campus sheet.")
        return

    selected_date = st.selectbox(
        "Select date",
        options=daily_dates[::-1],
        key=f"daily_date_{campus}",
    )
    snapshot = campus_date_snapshot(raw_df, selected_date, campus=campus)
    st.subheader(f"Sheet data for {selected_date}")
    if snapshot.empty:
        st.info("No DONE/TOTAL/PERCENTAGE rows found for this date.")
    else:
        st.dataframe(snapshot, width="stretch", hide_index=True)


def render_overall_data(parsed: dict[str, dict]):
    st.header("Overall Data by Date")
    st.caption("Summary percentages from each campus sheet tab, segregated by date.")

    campus_options = ["All campuses (combined)"] + campus_sheet_names()
    selected = st.selectbox("Campus", campus_options)

    if selected == "All campuses (combined)":
        overall = aggregate_overall_by_date(parsed)
        locations = []
        for name in campus_sheet_names():
            locations.extend(parsed.get(name, {}).get("locations", []))
    else:
        data = parsed.get(selected, {})
        overall = data.get("overall")
        locations = data.get("locations", [])

    if overall is None or overall.empty:
        st.warning("No summary rows found for this selection.")
        return

    selected_date = st.selectbox("Select date", overall["Date"].tolist()[::-1])
    row = overall[overall["Date"] == selected_date].iloc[0]

    cols = st.columns(4)
    for i, act in enumerate(ACTIVITIES):
        val = row.get(act)
        cols[i % 4].metric(act, f"{val:.1f}%" if val is not None else "—")

    st.subheader("All dates")
    display = overall.copy()
    for act in ACTIVITIES:
        if act in display.columns:
            display[act] = display[act].apply(lambda x: f"{x:.1f}%" if x is not None else "—")
    st.dataframe(display, width="stretch", hide_index=True)

    if selected == "All campuses (combined)":
        st.subheader("Latest % by campus")
        campus_cols = st.columns(min(3, len(campus_sheet_names())))
        for i, name in enumerate(campus_sheet_names()):
            data = parsed.get(name, {})
            locs = data.get("locations", [])
            ov = data.get("overall")
            pct = sheet_overall_percent(locs, ov)
            icon = CAMPUS_ICONS.get(name, "🏫")
            campus_cols[i % len(campus_cols)].metric(f"{icon} {name}", f"{pct}%")

    label = selected if selected != "All campuses (combined)" else "all campuses"
    with st.expander(f"All locations — latest snapshot ({label})"):
        snap_rows = []
        for loc in locations:
            latest = loc.latest_date
            if not latest:
                continue
            snap = {
                "Location": loc.location,
                "Campus": loc.sheet_name,
                "Date": latest,
            }
            for act, val in loc.by_date[latest].items():
                snap[act] = f"{val:.1f}%" if val is not None else "—"
            snap_rows.append(snap)
        if snap_rows:
            st.dataframe(snap_rows, width="stretch", hide_index=True)


def render_history():
    st.header("Daily Work History")
    st.caption("Plan-before-work and after-work updates. Public users can view; only admin can add entries.")

    history = fetch_history()
    tab_view, tab_admin = st.tabs(["View history", "Admin — add entry"])

    with tab_view:
        if history.empty:
            st.info(
                "No history entries yet. Create a **Daily History** tab in your Google Sheet "
                "with columns: `Date | Campus | Type | Title | Description | Image_URLs` "
                "then set `HISTORY_GID` in `config.py`."
            )
        else:
            filter_campus = st.multiselect(
                "Filter by campus",
                options=sorted(history["Campus"].dropna().unique()) if "Campus" in history.columns else [],
            )
            filtered = history
            if filter_campus and "Campus" in history.columns:
                filtered = history[history["Campus"].isin(filter_campus)]

            for _, entry in filtered.iloc[::-1].iterrows():
                entry_type = entry.get("Type", "Update")
                icon = "📋" if str(entry_type).lower().startswith("plan") else "✅"
                with st.container(border=True):
                    st.markdown(f"### {icon} {entry.get('Title', 'Update')} — {entry.get('Date', '')}")
                    st.caption(f"{entry.get('Campus', '')} · {entry_type}")
                    if entry.get("Description"):
                        st.write(entry["Description"])
                    urls = str(entry.get("Image_URLs", "")).strip()
                    if urls:
                        for url in [u.strip() for u in urls.split(",") if u.strip()]:
                            try:
                                st.image(url, width="stretch")
                            except Exception:
                                st.markdown(f"[Photo link]({url})")

    with tab_admin:
        st.warning("Admin only — entries are saved to your Google Sheet.")
        if not admin_login_form():
            st.stop()

        with st.form("add_history"):
            date = st.date_input("Date")
            campus = st.selectbox("Campus", campus_sheet_names())
            entry_type = st.selectbox("Type", ["Plan (before work)", "After work update"])
            title = st.text_input("Title")
            description = st.text_area("Description")
            image_urls = st.text_input(
                "Image URLs (comma-separated)",
                help="Upload photos to Google Drive, set sharing to 'Anyone with link', paste URLs here.",
            )
            if st.form_submit_button("Save entry"):
                ok = append_history_row(
                    {
                        "Date": date.strftime("%d/%m/%Y"),
                        "Campus": campus,
                        "Type": entry_type,
                        "Title": title,
                        "Description": description,
                        "Image_URLs": image_urls,
                    }
                )
                if ok:
                    fetch_history.clear()
                    st.success("Entry saved to Google Sheet!")
                    st.rerun()
                else:
                    st.error(
                        "Could not write to sheet. Add a **Google service account** to Streamlit secrets "
                        "(see README). You can also add rows manually in the Daily History tab."
                    )


def _load_or_fail() -> dict[str, dict]:
    try:
        return load_data()
    except Exception as exc:
        st.error(
            "Could not load Google Sheet. Make sure the sheet is shared as "
            "**Anyone with the link → Viewer**."
        )
        st.exception(exc)
        st.stop()


def page_dashboard():
    render_dashboard(_load_or_fail())


def page_overall():
    render_overall_data(_load_or_fail())


def page_history():
    render_history()


def main():
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <h2>USM Progress</h2>
            <p>Campus installation tracker</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(f"[Open Google Sheet ↗](https://docs.google.com/spreadsheets/d/{SHEET_ID})")

    if st.sidebar.button("Refresh data"):
        load_data.clear()
        fetch_history.clear()
        st.rerun()

    nav = st.navigation(
        {
            "Overview": [
                st.Page(page_dashboard, title="Dashboard", icon="📊", default=True),
            ],
            "Check Daily Data": list(CAMPUS_PAGES.values()),
            "More": [
                st.Page(page_overall, title="Overall Data", icon="📈"),
                st.Page(page_history, title="Daily History", icon="🗂️"),
            ],
        },
        position="sidebar",
    )
    nav.run()


if __name__ == "__main__":
    main()
