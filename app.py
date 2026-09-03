"""
USM Progress Dashboard — reads live data from Google Sheets.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from app_config import (
    ACTIVITIES,
    CRITICAL_LEVELS,
    CAMPUS_ICONS,
    DASHBOARD_CHART_ACTIVITIES,
    FRACTION_METRIC_ACTIVITIES,
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
    induk_grouped_snapshot,
    location_change_summary,
    parse_progress_sheet,
    style_full_daily_complete_rows,
)
from lib.details import (
    _normalize_critical,
    details_rows_for_sheet,
    merge_details_with_progress,
)
from lib.gantt import (
    blackout_timeline_figure,
    build_current_progress_table,
    gantt_locations_overall,
    parse_gantt,
    schedule_timeline_table,
    style_gantt_schedule,
    synthetic_blackout_colors,
)
from lib.sheets_client import (
    append_history_row,
    append_issue_row,
    fetch_all_tabs,
    fetch_csv,
    fetch_details,
    fetch_gantt,
    fetch_gantt_cell_colors,
    fetch_history,
    fetch_issues,
    fetch_work_plan,
    sync_details_sheet,
    update_issue_status,
)
from lib.work_plan import build_work_plan_view, work_plan_dates

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


@st.cache_data(ttl=300, show_spinner="Loading data…")
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
    st.caption(
        "Note: Percentage values are the average percentage calculated across locations."
    )

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
            delta, _detail = _metric_delta_note(overall, act, buildings=buildings)
            with metric_cols[j]:
                st.metric(act, display, delta=delta)


def render_dashboard_chart(overall: pd.DataFrame):
    """Progress % line chart over dates (UTP / AP / Fiber)."""
    if overall is None or overall.empty or "Date" not in overall.columns:
        return

    st.subheader("Progress over time")
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


def render_change_summary(summary: pd.DataFrame, prev_date: str, latest_date: str):
    """Table of location×activity values that changed between the last two dates."""
    st.subheader("Changes since previous date")
    if summary is None or summary.empty:
        return
    st.caption(
        "**★ New** = activity was not tracked before (—) and now has data — "
        "e.g. Slab Coring or Rack Installation added to a building."
    )
    st.dataframe(summary, width="stretch", hide_index=True)


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
        prev_date = ""
        latest_date = ""
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
        if raw_df is not None and prev_date and latest_date:
            summary = location_change_summary(
                raw_df, prev_date, latest_date, group_filter=desa
            )
            render_change_summary(summary, prev_date, latest_date)
        return

    data = parsed.get(campus, {})
    overall = data.get("overall", pd.DataFrame())
    raw_df = data.get("raw_df")
    icon = CAMPUS_ICONS.get(campus, "🏫")
    render_activity_average_panel(
        overall,
        title=f"{icon} {campus}",
    )
    if (
        raw_df is not None
        and overall is not None
        and not getattr(overall, "empty", True)
        and len(overall) >= 2
    ):
        prev_date = str(overall.iloc[-2].get("Date", ""))
        latest_date = str(overall.iloc[-1].get("Date", ""))
        summary = location_change_summary(
            raw_df,
            prev_date,
            latest_date,
            induk_grouped_only=(campus == "INDUK"),
        )
        render_change_summary(summary, prev_date, latest_date)


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

    if campus == "INDUK":
        view_mode = st.radio(
            "Table view",
            options=["Accumulated (desa groups)", "Full (per location)"],
            horizontal=True,
            key=f"daily_view_{campus}",
            help=(
                "Accumulated rolls locations into the 7 desa groups. "
                "Full shows every building location."
            ),
        )
        use_full_view = not view_mode.startswith("Accumulated")
        if use_full_view:
            snapshot = campus_date_snapshot(raw_df, selected_date, campus=campus)
        else:
            snapshot = induk_grouped_snapshot(raw_df, selected_date)
    else:
        use_full_view = True
        snapshot = campus_date_snapshot(raw_df, selected_date, campus=campus)

    st.subheader(f"Sheet data for {selected_date}")
    if snapshot.empty:
        st.info("No DONE/TOTAL/PERCENTAGE rows found for this date.")
    else:
        display = (
            style_full_daily_complete_rows(snapshot) if use_full_view else snapshot
        )
        st.dataframe(display, width="stretch", hide_index=True)


def render_work_plan_vs_actual(parsed: dict[str, dict]):
    st.header("Work Plan vs Actual")
    st.caption("Daily work plan compared with reported progress changes.")

    plan = fetch_work_plan()
    dates = work_plan_dates(plan)
    if not dates:
        st.info("No work plan entries found yet.")
        return

    selected_date = st.selectbox(
        "Select date",
        options=dates,
        key="work_plan_date",
    )

    table, prev_date = build_work_plan_view(plan, parsed, selected_date)

    if prev_date:
        st.caption(
            f"Reported changes compare progress on **{selected_date}** "
            f"vs **{prev_date}** (all campuses)."
        )
    else:
        st.caption(f"Work plan for **{selected_date}**.")

    if table.empty:
        st.info("No plan rows for this date.")
        return

    st.dataframe(table, width="stretch", hide_index=True)


def _style_details_rows(df: pd.DataFrame):
    """Row colors: Critical=red, Medium=yellow, Completed=green."""
    if df is None or df.empty:
        return df
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    green = "background-color: #C8E6C9; color: #1B5E20"
    yellow = "background-color: #FFF9C4; color: #F57F17"
    red = "background-color: #FFCDD2; color: #B71C1C"

    for idx, row in df.iterrows():
        critical = str(row.get("Critical", "")).strip()
        progress = str(row.get("Progress", "")).strip()
        if critical == "Critical":
            style = red
        elif critical == "Medium":
            style = yellow
        elif progress == "Completed":
            style = green
        else:
            continue
        for col in df.columns:
            styles.at[idx, col] = style

    return df.style.apply(lambda _: styles, axis=None)


def render_gantt(parsed: dict[str, dict]):
    st.header("Gantt")
    st.caption(
        "Schedule from the **gantt** sheet. **Current Progress** uses recalculated "
        "daily INDUK data for each listed building (same rules as Dashboard)."
    )

    raw_gantt = fetch_gantt()
    schedule, date_cols, gantt_meta = parse_gantt(raw_gantt)
    if schedule.empty:
        st.warning("No rows found in the gantt sheet.")
        return

    column_indices = gantt_meta.get("column_indices") or {}
    sheet_row_indices = gantt_meta.get("sheet_row_indices") or []

    induk = parsed.get("INDUK", {})
    raw_df = induk.get("raw_df")
    dates = available_dates(raw_df, newest_first=True) if raw_df is not None else []
    latest_date = dates[0] if dates else ""

    tab_schedule, tab_progress = st.tabs(["Gantt Schedule", "Current Progress"])

    with tab_schedule:
        st.subheader("Building schedule")
        meta_view = schedule_timeline_table(schedule, date_cols)
        cell_colors = fetch_gantt_cell_colors()
        synthetic = synthetic_blackout_colors(
            schedule,
            date_cols,
            sheet_row_indices=list(sheet_row_indices),
            column_indices=dict(column_indices),
        )
        if cell_colors:
            for key, value in synthetic.items():
                cell_colors.setdefault(key, value)
            color_note = "Cell colours from the Google Sheet (blackout fill where not coloured)."
        else:
            cell_colors = synthetic
            color_note = "Blackout windows shown in red (from stop/start dates)."
        st.caption(color_note)
        styled = style_gantt_schedule(
            meta_view,
            cell_colors,
            sheet_row_indices=list(sheet_row_indices),
            column_indices=dict(column_indices),
        )
        st.dataframe(styled, width="stretch", hide_index=True)

        fig = blackout_timeline_figure(schedule)
        if fig is not None:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No blackout periods with valid start/end dates to chart.")

    with tab_progress:
        if raw_df is None or getattr(raw_df, "empty", True) or not latest_date:
            st.warning("No INDUK daily progress data available.")
            return

        st.caption(f"Latest daily data: **{latest_date}**")
        overall = gantt_locations_overall(
            raw_df, schedule, latest_date=latest_date
        )
        if overall is not None and not overall.empty:
            render_activity_average_panel(
                overall,
                title="🏫 Gantt locations (overall)",
            )

        progress_table = build_current_progress_table(
            raw_df, schedule, latest_date=latest_date
        )
        st.subheader("Per location")
        display_cols = (
            ["Location", "Blackout", "Remarks"]
            + list(ACTIVITIES)
            + ["Progress location"]
        )
        display_cols = [c for c in display_cols if c in progress_table.columns]
        st.dataframe(progress_table[display_cols], width="stretch", hide_index=True)


def render_location_details(parsed: dict[str, dict]):
    st.header("Location Details")
    st.caption(
        "Remarks and critical flag per building. Progress uses recalculated daily "
        "values (same rules as Check Daily Data), not raw sheet PERCENTAGE cells. "
        "Admin can edit Critical and Remarks here — saved to the DETAILS sheet."
    )

    details = fetch_details()
    view = merge_details_with_progress(details, parsed, include_missing_locations=True)

    tab_view, tab_admin = st.tabs(["View", "Admin — edit"])

    with tab_view:
        if view.empty:
            st.info("No locations found yet. Use Admin to sync / edit.")
        else:
            campuses = sorted(view["Campus"].dropna().unique().tolist())
            f1, f2, f3 = st.columns(3)
            with f1:
                campus_filter = st.multiselect(
                    "Campus", options=campuses, default=campuses, key="details_campus_f"
                )
            with f2:
                progress_filter = st.multiselect(
                    "Progress",
                    options=["Completed", "In Progress", "Not Started"],
                    default=["Completed", "In Progress", "Not Started"],
                    key="details_progress_f",
                )
            with f3:
                critical_filter = st.multiselect(
                    "Critical",
                    options=CRITICAL_LEVELS,
                    default=CRITICAL_LEVELS,
                    key="details_critical_f",
                )

            filtered = view[
                view["Campus"].isin(campus_filter)
                & view["Progress"].isin(progress_filter)
                & view["Critical"].isin(critical_filter)
            ].copy()
            if not filtered.empty:
                filtered["#"] = range(1, len(filtered) + 1)

            c1, c2, c3 = st.columns(3)
            c1.metric("Locations", len(filtered))
            c2.metric(
                "Critical",
                int((filtered["Critical"] == "Critical").sum()) if not filtered.empty else 0,
            )
            c3.metric(
                "Completed",
                int((filtered["Progress"] == "Completed").sum()) if not filtered.empty else 0,
            )

            display_cols = ["#", "Campus", "Location", "Critical", "Remarks", "Progress"]
            st.dataframe(
                _style_details_rows(filtered[display_cols]),
                width="stretch",
                hide_index=True,
            )

    with tab_admin:
        st.caption("Edit **Critical** and **Remarks** below, then click Save — updates the DETAILS sheet.")
        if not admin_login_form():
            st.stop()

        if view.empty:
            st.info("No locations from progress data yet.")
            return

        edit_df = view[["Campus", "Location", "Critical", "Remarks", "Progress"]].copy()
        edit_df["Critical"] = edit_df["Critical"].map(
            lambda v: v if str(v).strip() in CRITICAL_LEVELS else "Not Critical"
        )

        edited = st.data_editor(
            edit_df,
            width="stretch",
            hide_index=True,
            num_rows="fixed",
            disabled=["Campus", "Location", "Progress"],
            column_config={
                "Campus": st.column_config.TextColumn("Campus", width="medium"),
                "Location": st.column_config.TextColumn("Location", width="large"),
                "Critical": st.column_config.SelectboxColumn(
                    "Critical",
                    options=CRITICAL_LEVELS,
                    help="Not Critical, Medium (yellow), or Critical (red).",
                    required=True,
                    width="medium",
                ),
                "Remarks": st.column_config.TextColumn(
                    "Remarks",
                    help="Notes about this building.",
                    width="large",
                ),
                "Progress": st.column_config.TextColumn(
                    "Progress",
                    help="Auto from daily progress — not editable.",
                    width="medium",
                ),
            },
            key="details_data_editor",
        )

        col_a, col_b = st.columns([1, 2])
        with col_a:
            save = st.button("Save to DETAILS sheet", type="primary", key="details_save_all")
        with col_b:
            st.caption("Progress stays auto-calculated; only Critical + Remarks are written.")

        if save:
            to_save = edited.copy()
            to_save["Critical"] = to_save["Critical"].map(_normalize_critical)
            rows = details_rows_for_sheet(to_save)
            if sync_details_sheet(rows):
                st.success(f"Saved {len(rows) - 1} locations to DETAILS sheet.")
                st.rerun()
            else:
                st.error(
                    "Could not write to DETAILS. Add a Google service account to "
                    "Streamlit secrets (Editor access on the spreadsheet)."
                )


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
        st.error("Could not load data. Please try Refresh, or try again later.")
        st.exception(exc)
        st.stop()


def page_dashboard():
    render_dashboard(_load_or_fail())


def page_history():
    render_history()


def page_work_plan():
    render_work_plan_vs_actual(_load_or_fail())


def page_gantt():
    render_gantt(_load_or_fail())


def page_location_details():
    render_location_details(_load_or_fail())


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

    if st.sidebar.button("Refresh data"):
        # Clear nested sheet caches too — otherwise Refresh only re-parses
        # stale CSV still held by fetch_csv / fetch_all_tabs (ttl 5 min).
        fetch_csv.clear()
        fetch_all_tabs.clear()
        load_data.clear()
        fetch_history.clear()
        fetch_issues.clear()
        fetch_work_plan.clear()
        fetch_gantt.clear()
        fetch_gantt_cell_colors.clear()
        fetch_details.clear()
        st.rerun()

    nav = st.navigation(
        {
            "Overview": [
                st.Page(page_dashboard, title="Dashboard", icon="📊", default=True),
                st.Page(
                    page_work_plan,
                    title="Work Plan vs Actual",
                    icon="📋",
                    url_path="work-plan",
                ),
                st.Page(
                    page_location_details,
                    title="Location Details",
                    icon="📍",
                    url_path="location-details",
                ),
                # Temporarily hidden — restore Gantt page here when needed.
            ],
            "Check Daily Data": list(CAMPUS_PAGES.values()),
            # Temporarily hidden — restore Issue & Risk / Daily History here when needed.
        },
        position="sidebar",
    )
    nav.run()


if __name__ == "__main__":
    main()
