"""Local portfolio surface for the Healthcare Marketing Weekly Performance Readout."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from src.analytics import build_weekly_readout
from src.evaluation import visible_evaluation_summary
from src.observations import detect_observations
from src.pipeline import load_bundled_dataset
from src.qa import evaluate_report_week
from src.trends import BREAKDOWNS, TREND_KPIS, TREND_MODES, build_trend_series, trend_table


ROOT = Path(__file__).resolve().parent

KPI_DEFINITIONS = (
    ("Spend", "spend", "currency", "Budget deployed; neutral WoW delta."),
    ("Qualified Leads", "qualified_leads", "number", "CRM-qualified leads; higher is better."),
    ("CPQL", "cost_per_qualified_lead", "currency", "Spend / qualified leads; lower is better."),
    ("Conversions", "conversions", "number", "Converted qualified leads; higher is better."),
    ("Cost per Conversion", "cost_per_conversion", "currency", "Spend / conversions; lower is better."),
    ("Lead Qualification Rate", "lead_qualification_rate", "percent", "Qualified leads / leads; higher is better."),
)


st.set_page_config(
    page_title="Healthcare Marketing Weekly Performance Readout",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --readout-page: #142b3f;
        --readout-sidebar: #102538;
        --readout-surface: #1b3a50;
        --readout-surface-raised: #234b61;
        --readout-text: #f6fbff;
        --readout-muted: #c3d2dc;
        --readout-line: #41657a;
        --readout-gold-light: #fff0a6;
        --readout-gold: #f2cc6b;
        --readout-gold-deep: #c99534;
    }
    html, body,
    [data-testid="stAppViewContainer"],
    .stApp {
        background: var(--readout-page) !important;
        color: var(--readout-text) !important;
    }
    [data-testid="stSidebar"] {
        background: var(--readout-sidebar) !important;
    }
    [data-testid="stHeader"] {
        background: transparent !important;
    }
    h1, h2, h3 {
        color: var(--readout-text) !important;
        text-shadow: 0 1px 0 rgba(0, 0, 0, .28);
    }
    .eyebrow {
        display: inline-block;
        background: linear-gradient(180deg, var(--readout-gold-light) 0%, var(--readout-gold) 48%, var(--readout-gold-deep) 100%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        color: var(--readout-gold-light) !important;
        filter: drop-shadow(0 1px 0 rgba(72, 48, 12, .45));
        font-weight: 800;
    }
    p, li, [data-testid="stCaptionContainer"], [data-testid="stSidebar"] label {
        color: var(--readout-muted) !important;
    }
    .synthetic-banner {
        background: linear-gradient(135deg, rgba(242, 204, 107, .18), rgba(201, 149, 52, .34));
        border-left: 4px solid var(--readout-gold);
        color: var(--readout-gold-light) !important;
        padding: .8rem 1rem;
        font-weight: 750;
        letter-spacing: .04em;
        box-shadow: inset 0 1px 0 rgba(255, 240, 166, .18), 0 4px 14px rgba(0, 0, 0, .12);
    }
    [data-testid="stMetricLabel"] {
        color: var(--readout-muted) !important;
    }
    [data-testid="stMetricValue"] {
        color: var(--readout-text) !important;
    }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border: 1px solid var(--readout-line);
        border-radius: 8px;
        overflow: hidden;
    }
    [data-testid="stDataFrame"] [role="columnheader"],
    [data-testid="stTable"] thead th {
        background: var(--readout-surface-raised) !important;
        color: var(--readout-gold-light) !important;
        font-weight: 800 !important;
    }
    [data-testid="stDataFrame"] [role="gridcell"] {
        color: var(--readout-text) !important;
    }
    .stDataFrameGlideDataEditor {
        --gdg-accent-color: var(--readout-gold) !important;
        --gdg-accent-fg: var(--readout-page) !important;
        --gdg-accent-light: rgba(242, 204, 107, .18) !important;
        --gdg-text-dark: var(--readout-text) !important;
        --gdg-text-medium: var(--readout-muted) !important;
        --gdg-text-light: rgba(195, 210, 220, .72) !important;
        --gdg-text-bubble: var(--readout-muted) !important;
        --gdg-text-header: var(--readout-gold-light) !important;
        --gdg-text-group-header: var(--readout-gold-light) !important;
        --gdg-text-header-selected: var(--readout-page) !important;
        --gdg-bg-cell: var(--readout-surface) !important;
        --gdg-bg-cell-medium: var(--readout-surface) !important;
        --gdg-bg-header: var(--readout-surface-raised) !important;
        --gdg-bg-header-has-focus: #355b70 !important;
        --gdg-bg-header-hovered: #355b70 !important;
        --gdg-bg-group-header: var(--readout-surface-raised) !important;
        --gdg-bg-group-header-hovered: #355b70 !important;
        --gdg-bg-search-result: rgba(242, 204, 107, .18) !important;
        --gdg-border-color: var(--readout-line) !important;
        --gdg-horizontal-border-color: var(--readout-line) !important;
    }
    .readout-table-wrap {
        border: 1px solid var(--readout-line);
        border-radius: 8px;
        overflow-x: auto;
        background: var(--readout-surface);
    }
    .readout-table {
        width: 100%;
        border-collapse: collapse;
        color: var(--readout-text);
        font-size: .9rem;
    }
    .readout-table th {
        background: var(--readout-surface-raised);
        color: var(--readout-gold-light);
        font-weight: 800;
        letter-spacing: .01em;
        padding: .7rem .75rem;
        border-bottom: 2px solid var(--readout-gold-deep);
        text-align: left;
        white-space: nowrap;
    }
    .readout-table td {
        background: var(--readout-surface);
        color: var(--readout-text);
        padding: .65rem .75rem;
        border-bottom: 1px solid var(--readout-line);
        white-space: nowrap;
    }
    .readout-table tbody tr:nth-child(even) td {
        background: #1e4258;
    }
    .readout-table tbody tr:last-child td {
        border-bottom: 0;
    }
    [data-baseweb="tab-list"] {
        border-bottom: 1px solid var(--readout-line) !important;
    }
    button[data-baseweb="tab"], [role="tab"] {
        color: var(--readout-muted) !important;
    }
    button[data-baseweb="tab"][aria-selected="true"],
    [role="tab"][aria-selected="true"] {
        color: var(--readout-gold-light) !important;
        font-weight: 800 !important;
    }
    [data-testid="stTab"] {
        color: var(--readout-muted) !important;
    }
    [data-testid="stTab"][aria-selected="true"],
    [data-testid="stTab"][aria-selected="true"] * {
        color: var(--readout-gold-light) !important;
        font-weight: 800 !important;
    }
    [data-testid="stTab"] .react-aria-SelectionIndicator {
        background: linear-gradient(90deg, var(--readout-gold-deep), var(--readout-gold-light), var(--readout-gold-deep)) !important;
    }
    [data-baseweb="tab-highlight"] {
        background: linear-gradient(90deg, var(--readout-gold-deep), var(--readout-gold-light), var(--readout-gold-deep)) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def _currency(value: Any) -> str:
    return "N/A" if value is None else f"${float(value):,.2f}"


def _number(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):,.0f}"


def _percent(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.1%}"


def _display(value: Any, kind: str) -> str:
    return {"currency": _currency, "number": _number, "percent": _percent}[kind](value)


def _delta(change: dict[str, Any]) -> str:
    percent = change.get("percent")
    return "N/A WoW" if percent is None else f"{float(percent):+.1%} WoW"


def _metric_row(item: dict[str, Any]) -> dict[str, Any]:
    current = item["current"]
    return {
        "Channel": item["channel"],
        "Spend": _currency(current.get("spend")),
        "Qualified Leads": _number(current.get("qualified_leads")),
        "CPQL": _currency(current.get("cost_per_qualified_lead")),
        "Conversions": _number(current.get("conversions")),
        "Cost / Conversion": _currency(current.get("cost_per_conversion")),
        "Qualification Rate": _percent(current.get("lead_qualification_rate")),
    }


def _campaign_row(item: dict[str, Any]) -> dict[str, Any]:
    current = item["current"]
    return {
        "Channel": item["channel"],
        "Campaign": item["campaign"],
        "Spend": _currency(current.get("spend")),
        "Qualified Leads": _number(current.get("qualified_leads")),
        "CPQL": _currency(current.get("cost_per_qualified_lead")),
        "Conversions": _number(current.get("conversions")),
        "Cost / Conversion": _currency(current.get("cost_per_conversion")),
        "Qualification Rate": _percent(current.get("lead_qualification_rate")),
    }


def _html_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="readout-table-wrap"><p>No rows available.</p></div>'

    columns = list(rows[0])
    header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape('' if row.get(column) is None else str(row.get(column)))}</td>"
            for column in columns
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="readout-table-wrap"><table class="readout-table">'
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody>"
        "</table></div>"
    )


@st.cache_data(show_spinner=False)
def load_dataset():
    return load_bundled_dataset(ROOT)


dataset = load_dataset()

st.title("Healthcare Marketing Weekly Performance Readout")
st.markdown(
    '<div class="synthetic-banner">SYNTHETIC DATA · FICTIONAL HEALTHCARE MARKETING ORGANIZATION · NO LIVE ACCOUNTS</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="eyebrow">Portfolio demonstration</div>', unsafe_allow_html=True)
st.write("A decision-ready weekly paid-media readout with explicit source trust and QA boundaries.")

with st.sidebar:
    st.header("Report controls")
    reporting_week = st.selectbox(
        "Reporting week",
        dataset.week_starts,
        index=len(dataset.week_starts) - 1,
        help="Select one of the eight bundled synthetic reporting weeks.",
    )
    st.caption("Local-only build. It reads the three CSV exports in data/source_exports and makes no network calls.")

readout = build_weekly_readout(dataset, reporting_week)
qa = evaluate_report_week(dataset, reporting_week)
observations = detect_observations(readout)

report_tab, trend_tab, qa_tab = st.tabs(["Weekly report", "Trend explorer", "Data trust & QA"])

with report_tab:
    st.subheader("Weekly Paid Media Performance")
    st.caption(f"Reporting week: {reporting_week} · Prior week: {readout['prior_week'] or 'not available'}")

    for start in range(0, len(KPI_DEFINITIONS), 3):
        cols = st.columns(3)
        for column, (label, key, kind, note) in zip(cols, KPI_DEFINITIONS[start : start + 3]):
            with column:
                st.metric(label, _display(readout["current_metrics"].get(key), kind), _delta(readout["changes"][key]), delta_color="normal")
                st.caption(note)

    st.subheader("Channel Performance")
    st.markdown(_html_table([_metric_row(item) for item in readout["channel_performance"]]), unsafe_allow_html=True)

    st.subheader("Campaign Performance")
    st.caption("Campaign rows show named contributors to the channel result; they do not establish causality.")
    st.markdown(_html_table([_campaign_row(item) for item in readout["campaign_performance"]]), unsafe_allow_html=True)

    st.subheader("Evidence-backed observations")
    if observations:
        for observation in observations:
            with st.expander(f"{observation['classification'].replace('_', ' ').title()} · {observation['scope']}"):
                st.write(observation["summary"])
                st.caption(f"Confidence: {observation['confidence']}. {observation['why_it_matters']}")
    else:
        st.info("No material movement crossed the proof-of-concept observation thresholds for this week.")

with trend_tab:
    st.subheader("Trend Explorer")
    st.caption("All trend values are recalculated from trusted rows. Rolling ratios use aggregate numerators and denominators.")
    trend_controls = st.columns(4)
    start_week = trend_controls[0].selectbox("Start week", dataset.week_starts, index=max(0, len(dataset.week_starts) - 8), key="trend_start")
    end_week = trend_controls[1].selectbox("End week", dataset.week_starts, index=len(dataset.week_starts) - 1, key="trend_end")
    trend_kpi = trend_controls[2].selectbox("KPI", list(TREND_KPIS), index=2, key="trend_kpi")
    breakdown = trend_controls[3].selectbox("Breakdown", list(BREAKDOWNS), index=1, key="trend_breakdown")
    mode = st.radio("Trend mode", TREND_MODES, horizontal=True, key="trend_mode")
    if dataset.week_starts.index(start_week) > dataset.week_starts.index(end_week):
        st.error("Start week must be on or before end week.")
    else:
        series = build_trend_series(dataset, start_week, end_week, trend_kpi, breakdown, mode)
        st.markdown(_html_table(trend_table(series, trend_kpi)), unsafe_allow_html=True)

with qa_tab:
    st.subheader("Data Trust & Publication QA")
    qa_class = {"PASS": "qa-pass", "WARNING": "qa-warning", "REVIEW": "qa-review", "FAIL": "qa-review"}.get(qa.status, "")
    st.markdown(
        f'<div class="qa-card"><strong class="{qa_class}">{qa.status}</strong><br>{qa.publication_state}<br><span class="scope-note">{qa.reason}</span></div>',
        unsafe_allow_html=True,
    )
    st.write("")
    st.markdown("**Source coverage**")
    st.markdown(
        _html_table(
            [
                {
                    "Source": item.get("label", item.get("source_key", "Unknown")),
                    "Rows loaded": item.get("rows_loaded", 0),
                    "Trusted rows": item.get("trusted_rows", 0),
                    "Warnings": item.get("warning_count", 0),
                }
                for item in dataset.source_summaries
            ]
        ),
        unsafe_allow_html=True,
    )
    st.markdown("**Deterministic checks**")
    evaluation = visible_evaluation_summary(dataset)
    st.write(f"{evaluation['passed']}/{evaluation['total']} checks passed across the bundled dataset.")
    st.markdown(
        _html_table(
            [{"Check": result.name, "Status": "PASS" if result.passed else "REVIEW", "Evidence": result.evidence} for result in evaluation["results"]]
        ),
        unsafe_allow_html=True,
    )
    if qa.findings:
        st.markdown("**Findings for selected week**")
        st.markdown(_html_table([finding.as_dict() for finding in qa.findings]), unsafe_allow_html=True)
    else:
        st.success("No source-integrity findings for the selected week.")

st.divider()
st.caption("Scope note: this is a synthetic portfolio demonstration, not a clinical system, patient-data workflow, or production attribution model.")
