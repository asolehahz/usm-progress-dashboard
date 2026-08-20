"""
USM Progress Dashboard — reads live data from Google Sheets.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from config import ACTIVITIES, CAMPUS_ICONS, SHEET_ID, SHEET_TABS, campus_sheet_names
from lib.auth import admin_login_form
from lib.data_parser import (
    aggregate_overall_by_date,
    campus_sheets_summary,
    locations_activity_timeseries,
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


@st.cache_data(ttl=300, show_spinner="Loading data from Google Sheets…")
def load_data() -> dict[str, dict]:
    """Load and parse every tab defined in config.SHEET_TABS."""
    tabs = fetch_all_tabs()
    parsed: dict[str, dict] = {}
    for sheet_name, df in tabs.items():
        locations, overall = parse_progress_sheet(df, sheet_name=sheet_name)
        parsed[sheet_name] = {"locations": locations, "overall": overall}
    return parsed


def render_dashboard(parsed: dict[str, dict]):
    st.header("Campus Overview")
    st.caption(
        "Each campus has its own sheet tab in Google Sheets. "
        "Click a campus to view activity progress over time."
    )

    summary = campus_sheets_summary(parsed)
    cols = st.columns(2)
    for i, (campus, info) in enumerate(summary.items()):
        with cols[i % 2]:
            if st.button(
                f"{info['icon']}  {campus}  —  {info['overall']}%  ({info['count']} locations)",
                key=f"campus_btn_{campus}",
                use_container_width=True,
            ):
                st.session_state["selected_campus"] = campus
                st.session_state["page"] = "Campus Detail"
                st.rerun()

    overall = aggregate_overall_by_date(parsed)
    if not overall.empty:
        st.subheader("All Campuses — Combined Progress Trend")
        latest = overall.iloc[-1]
        metric_cols = st.columns(min(4, len(ACTIVITIES)))
        for i, act in enumerate(ACTIVITIES[:4]):
            val = latest.get(act)
            metric_cols[i].metric(act, f"{val:.1f}%" if val is not None else "—")

        fig = go.Figure()
        for act in ACTIVITIES:
            if act in overall.columns:
                fig.add_trace(
                    go.Scatter(
                        x=overall["Date"],
                        y=overall[act],
                        mode="lines+markers",
                        name=act,
                    )
                )
        fig.update_layout(
            height=420,
            xaxis_title="Date",
            yaxis_title="Progress (%)",
            yaxis_range=[0, 105],
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=40, r=20, t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)


def render_campus_detail(parsed: dict[str, dict]):
    st.header("Campus Detail")
    campus_names = campus_sheet_names()
    default_idx = 0
    if "selected_campus" in st.session_state and st.session_state["selected_campus"] in campus_names:
        default_idx = campus_names.index(st.session_state["selected_campus"])

    campus = st.selectbox("Select campus (sheet tab)", campus_names, index=default_idx)
    st.session_state["selected_campus"] = campus

    data = parsed.get(campus, {})
    locations = data.get("locations", [])
    overall = data.get("overall")

    if not locations:
        st.info(f"No progress data in the **{campus}** sheet yet.")
        return

    ts = locations_activity_timeseries(locations)
    icon = CAMPUS_ICONS.get(campus, "🏫")
    avg = sheet_overall_percent(locations, overall)

    c1, c2, c3 = st.columns(3)
    c1.metric(f"{icon} Campus", campus)
    c2.metric("Overall progress", f"{avg:.1f}%")
    c3.metric("Locations tracked", len(locations))

    fig = px.line(
        ts,
        x="Date",
        y="Percent",
        color="Activity",
        markers=True,
        title=f"{campus} — Activity progress by date",
    )
    fig.update_layout(height=480, yaxis_range=[0, 105], legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Location breakdown (latest)"):
        rows = []
        for loc in locations:
            latest = loc.latest_date
            rows.append(
                {
                    "Location": loc.location,
                    "Latest date": latest or "—",
                    "Overall %": f"{loc.overall_percent:.1f}%",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)


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
    st.dataframe(display, use_container_width=True, hide_index=True)

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
            st.dataframe(snap_rows, use_container_width=True, hide_index=True)


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
                                st.image(url, use_container_width=True)
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


def main():
    st.sidebar.title("USM Progress")
    st.sidebar.markdown(f"[Open Google Sheet](https://docs.google.com/spreadsheets/d/{SHEET_ID})")

    with st.sidebar.expander("Sheet tabs loaded"):
        for name in SHEET_TABS:
            st.write(f"• {name}")

    pages = ["Dashboard", "Campus Detail", "Overall Data", "Daily History"]

    if "page" not in st.session_state:
        st.session_state["page"] = "Dashboard"

    choice = st.sidebar.radio("Navigate", pages, index=pages.index(st.session_state["page"]))
    st.session_state["page"] = choice

    if st.sidebar.button("Refresh data"):
        load_data.clear()
        fetch_history.clear()
        st.rerun()

    try:
        parsed = load_data()
    except Exception as exc:
        st.error(
            "Could not load Google Sheet. Make sure the sheet is shared as "
            "**Anyone with the link → Viewer**."
        )
        st.exception(exc)
        st.stop()

    if choice == "Dashboard":
        render_dashboard(parsed)
    elif choice == "Campus Detail":
        render_campus_detail(parsed)
    elif choice == "Overall Data":
        render_overall_data(parsed)
    elif choice == "Daily History":
        render_history()


if __name__ == "__main__":
    main()
