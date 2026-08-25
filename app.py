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
    DASHBOARD_CHART_ACTIVITIES,
    FRACTION_METRIC_ACTIVITIES,
    SHEET_ID,
    campus_sheet_names,
    dashboard_select_options,
    parse_dashboard_selection,
)
from lib.auth import admin_login_form
from lib.data_parser import (
    available_dates,
    campus_date_snapshot,
    get_campus_overall,
    get_induk_desa_overall,
    induk_desa_building_increases,
    parse_progress_sheet,
)
from lib.sheets_client import (
    append_history_row,
    append_issue_row,
    fetch_all_tabs,
    fetch_history,
    fetch_issues,
    update_issue_status,
)

st.set_page_config(
    page_title="USM Progress Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

CHART_COLORS = [
    "#4B2876",
    "#F7941D",
    "#0077B6",
    "#2A9D8F",
    "#E63946",
    "#6A994E",
    "#C77DFF",
    "#BC6C25",
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


def _metric_delta_note(
    overall: pd.DataFrame,
    act: str,
    buildings: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Option B: metric + delta pill; caption when there is a change.
    Fractions: +N done since date (a → b); INDUK may append · K01, K05.
    Zero change → caption "no changes".
    """
    if overall is None or len(overall) < 2:
        return None, None

    latest = overall.iloc[-1]
    prev = overall.iloc[-2]
    prev_date = str(prev.get("Date", ""))

    building_note = ""
    if buildings:
        building_note = " · " + ", ".join(buildings)

    if act in FRACTION_METRIC_ACTIVITIES:
        d0 = prev.get(f"{act}__done")
        d1 = latest.get(f"{act}__done")
        t0 = prev.get(f"{act}__total")
        t1 = latest.get(f"{act}__total")
        if any(v is None or (isinstance(v, float) and pd.isna(v)) for v in (d0, d1, t0, t1)):
            return None, None
        d0, d1 = int(d0), int(d1)
        delta_done = d1 - d0
        if delta_done == 0:
            return None, "no changes"
        delta = f"{delta_done:+d}"
        caption = f"{delta_done:+d} done since {prev_date} ({d0} → {d1}){building_note}"
        return delta, caption

    v0 = prev.get(act)
    v1 = latest.get(act)
    if v0 is None or v1 is None or pd.isna(v0) or pd.isna(v1):
        return None, None
    diff = float(v1) - float(v0)
    if abs(diff) < 1e-9:
        return None, "no changes"
    delta = f"{diff:+.1f}%"
    caption = f"{diff:+.1f}% since {prev_date}{building_note}"
    return delta, caption


def render_activity_average_panel(
    overall: pd.DataFrame,
    title: str,
    building_increases: dict[str, list[str]] | None = None,
):
    """Latest metric boxes; optional INDUK building increase labels."""
    if overall is None or overall.empty:
        st.warning("No average percentage data found for this selection.")
        return

    latest = overall.iloc[-1]
    st.subheader(title)

    # Two fixed rows of 4 so cards stay aligned (equal structure per cell).
    for row_start in (0, 4):
        metric_cols = st.columns(4)
        for j in range(4):
            i = row_start + j
            if i >= len(ACTIVITIES):
                break
            act = ACTIVITIES[i]
            if act in FRACTION_METRIC_ACTIVITIES:
                done = latest.get(f"{act}__done")
                total = latest.get(f"{act}__total")
                if done is not None and total is not None and not (
                    pd.isna(done) or pd.isna(total)
                ):
                    display = f"{int(done)}/{int(total)}"
                else:
                    display = "N/A"
            else:
                val = latest.get(act)
                display = f"{val:.1f}%" if val is not None and not pd.isna(val) else "N/A"

            buildings = (building_increases or {}).get(act)
            delta, detail = _metric_delta_note(overall, act, buildings=buildings)
            with metric_cols[j]:
                st.metric(act, display, delta=delta)
                # Always reserve caption space so columns stay level.
                st.caption(detail if detail else "\u00a0")

    # Chart hidden for now — set True to show again.
    show_dashboard_chart = False
    if show_dashboard_chart:
        date_order = overall["Date"].tolist()
        fig = go.Figure()
        for i, act in enumerate(DASHBOARD_CHART_ACTIVITIES):
            if act in overall.columns:
                fig.add_trace(
                    go.Scatter(
                        x=overall["Date"],
                        y=overall[act],
                        mode="lines+markers",
                        name=act,
                        line=dict(
                            color=ACTIVITY_COLORS.get(act, CHART_COLORS[i % len(CHART_COLORS)]),
                            width=2,
                        ),
                        marker=dict(size=6),
                        connectgaps=False,
                    )
                )
        fig.update_layout(
            height=420,
            xaxis_title="Date (mm/dd/yyyy)",
            yaxis_title="Progress (%)",
            yaxis_range=[0, 105],
            xaxis=dict(
                categoryorder="array",
                categoryarray=date_order,
                type="category",
                tickangle=-30,
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=40, r=20, t=40, b=60),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FAFAFA",
            font=dict(color="#4B2876"),
            colorway=CHART_COLORS,
        )
        st.plotly_chart(fig, width="stretch")


def render_dashboard(parsed: dict[str, dict]):
    st.header("Dashboard")

    selected = st.selectbox(
        "Select campus / desa",
        options=dashboard_select_options(),
        key="dashboard_campus_select",
    )
    campus, desa = parse_dashboard_selection(selected)

    if desa:
        raw_df = parsed.get("INDUK", {}).get("raw_df")
        overall = get_induk_desa_overall(raw_df, desa) if raw_df is not None else pd.DataFrame()
        icon = CAMPUS_ICONS.get("INDUK", "🏫")
        building_increases: dict[str, list[str]] = {}
        if raw_df is not None and overall is not None and len(overall) >= 2:
            prev_date = str(overall.iloc[-2].get("Date", ""))
            latest_date = str(overall.iloc[-1].get("Date", ""))
            building_increases = induk_desa_building_increases(
                raw_df, desa, prev_date, latest_date
            )
        render_activity_average_panel(
            overall,
            title=f"{icon} {desa}",
            building_increases=building_increases,
        )
        return

    overall = parsed.get(campus, {}).get("overall", pd.DataFrame())
    icon = CAMPUS_ICONS.get(campus, "🏫")
    render_activity_average_panel(
        overall,
        title=f"{icon} {campus}",
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

    data = parsed.get(campus, {})
    raw_df = data.get("raw_df")

    if raw_df is None or getattr(raw_df, "empty", True):
        st.info(f"No sheet data loaded for **{campus}**.")
        return

    daily_dates = available_dates(raw_df)
    if not daily_dates:
        st.warning("No date blocks found in this campus sheet.")
        return

    selected_date = st.selectbox(
        "Select date",
        options=daily_dates,
        key=f"daily_date_{campus}",
    )
    snapshot = campus_date_snapshot(raw_df, selected_date, campus=campus)
    st.subheader(f"Sheet data for {selected_date}")
    if snapshot.empty:
        st.info("No DONE/TOTAL/PERCENTAGE rows found for this date.")
    else:
        st.dataframe(snapshot, width="stretch", hide_index=True)


def render_issues():
    st.header("Issue & Risk")
    st.caption("Public can view. Only admin can add entries or change Open/Close status.")

    issues = fetch_issues()
    tab_view, tab_admin = st.tabs(["View issues", "Admin — manage"])

    with tab_view:
        if issues.empty:
            st.info(
                "No issues yet. Admin can add entries here, or create an **Issue & Risk** tab "
                "in Google Sheets with columns: "
                "`No | Issue_Risk | Picture_URLs | Action | Status`."
            )
        else:
            status_filter = st.multiselect(
                "Filter by status",
                options=["Open", "Close"],
                default=["Open", "Close"],
            )
            display = issues.copy()
            if "Status" in display.columns and status_filter:
                display = display[display["Status"].isin(status_filter)]

            # Normalize column names for display
            rename = {
                "No": "No",
                "Issue_Risk": "Issue / Risk",
                "Picture_URLs": "Pictures",
                "Action": "Action",
                "Status": "Open/Close",
            }
            show = display.rename(columns={k: v for k, v in rename.items() if k in display.columns})
            preferred = ["No", "Issue / Risk", "Pictures", "Action", "Open/Close"]
            cols = [c for c in preferred if c in show.columns]
            st.dataframe(show[cols] if cols else show, width="stretch", hide_index=True)

            # Show pictures for rows that have URLs
            pic_col = "Picture_URLs" if "Picture_URLs" in display.columns else None
            if pic_col:
                with_pics = display[display[pic_col].astype(str).str.strip() != ""]
                if not with_pics.empty:
                    st.subheader("Pictures")
                    for _, row in with_pics.iterrows():
                        st.markdown(f"**#{row.get('No', '')} — {row.get('Issue_Risk', '')}**")
                        urls = str(row.get(pic_col, "")).strip()
                        for url in [u.strip() for u in urls.split(",") if u.strip()]:
                            try:
                                st.image(url, width="stretch")
                            except Exception:
                                st.markdown(f"[Image link]({url})")

    with tab_admin:
        st.warning("Admin only — entries are saved to your Google Sheet.")
        if not admin_login_form():
            st.stop()

        st.subheader("Add issue / risk")
        with st.form("add_issue"):
            issue_text = st.text_area("Issue / Risk", height=100)
            action = st.text_area("Action", height=80)
            status = st.selectbox("Open/Close", ["Open", "Close"])
            picture_urls = st.text_input(
                "Picture URLs (optional, comma-separated)",
                help="Upload to Google Drive, set sharing to Anyone with link, paste URLs here.",
            )
            if st.form_submit_button("Save entry"):
                existing = fetch_issues()
                next_no = 1
                if not existing.empty and "No" in existing.columns:
                    nums = pd.to_numeric(existing["No"], errors="coerce").dropna()
                    if not nums.empty:
                        next_no = int(nums.max()) + 1
                ok = append_issue_row(
                    {
                        "No": str(next_no),
                        "Issue_Risk": issue_text,
                        "Picture_URLs": picture_urls,
                        "Action": action,
                        "Status": status,
                    }
                )
                if ok:
                    fetch_issues.clear()
                    st.success(f"Saved as No. {next_no}")
                    st.rerun()
                else:
                    st.error(
                        "Could not write to sheet. Add a Google service account to Streamlit secrets "
                        "(see README), or add rows manually in the Issue & Risk tab."
                    )

        st.subheader("Update Open/Close status")
        existing = fetch_issues()
        if existing.empty or "No" not in existing.columns:
            st.info("No issues to update yet.")
        else:
            options = [
                f"{row.get('No', '')} — {str(row.get('Issue_Risk', ''))[:60]}"
                for _, row in existing.iterrows()
            ]
            with st.form("update_issue_status"):
                chosen = st.selectbox("Select issue", options)
                new_status = st.selectbox("New status", ["Open", "Close"], key="issue_status_update")
                if st.form_submit_button("Update status"):
                    issue_no = str(chosen).split(" — ", 1)[0].strip()
                    ok = update_issue_status(issue_no, new_status)
                    if ok:
                        fetch_issues.clear()
                        st.success(f"Issue #{issue_no} set to {new_status}")
                        st.rerun()
                    else:
                        st.error("Could not update status. Check service account access.")


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
                        "Date": date.strftime("%m/%d/%Y"),
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


def page_history():
    render_history()


def page_issues():
    render_issues()


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
        fetch_issues.clear()
        st.rerun()

    nav = st.navigation(
        {
            "Overview": [
                st.Page(page_dashboard, title="Dashboard", icon="📊", default=True),
            ],
            "Check Daily Data": list(CAMPUS_PAGES.values()),
            "More": [
                st.Page(page_issues, title="Issue & Risk", icon="⚠️", url_path="issue-risk"),
                st.Page(page_history, title="Daily History", icon="🗂️"),
            ],
        },
        position="sidebar",
    )
    nav.run()


if __name__ == "__main__":
    main()
