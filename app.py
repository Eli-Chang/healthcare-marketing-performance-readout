"""Local portfolio surface for the Healthcare Marketing Weekly Performance Readout."""

from __future__ import annotations

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
    :root { --navy: #12304a; --ink: #17324d; --muted: #617486; --line: #d9e2e8; --gold: #d9a441; --cream: #fbf4e2; }
    .block-container { max-width: 1320px; padding-top: 2.2rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: var(--navy); letter-spacing: -0.02em; }
    h1 { font-size: 2.65rem !important; }
    h2 { margin-top: 1.6rem !important; }
    .synthetic-banner { background: var(--cream); border-left: 4px solid var(--gold); color: #6b4c15; padding: .8rem 1rem; font-weight: 700; letter-spacing: .04em; margin: .6rem 0 1.8rem; }
    .eyebrow { color: #1f5b82; font-size: .76rem; font-weight: 800; letter-spacing: .17em; text-transform: uppercase; margin-bottom: -.35rem; }
    .scope-note { color: var(--muted); font-size: .9rem; line-height: 1.55; }
    .qa-card { border: 1px solid var(--line); border-radius: .55rem; padding: 1rem 1.1rem; background: #fff; min-height: 7.2rem; }
    .qa-card strong { color: var(--navy); font-size: 1.15rem; }
    .qa-pass { color: #1f6b4d; }
    .qa-warning { color: #946c1c; }
    .qa-review { color: #a45135; }
    [data-testid="stMetricValue"] { color: var(--navy); }
    [data-testid="stMetricLabel"] { color: #4b6479; }
    .stDataFrame { border: 1px solid var(--line); }
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
                st.metric(label, _display(readout["current_metrics"].get(key), kind), _delta(readout["changes"][key]), delta_color="off")
                st.caption(note)

    st.subheader("Channel Performance")
    st.dataframe([_metric_row(item) for item in readout["channel_performance"]], hide_index=True, width="stretch")

    st.subheader("Campaign Performance")
    st.caption("Campaign rows show named contributors to the channel result; they do not establish causality.")
    st.dataframe([_campaign_row(item) for item in readout["campaign_performance"]], hide_index=True, width="stretch")

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
        st.dataframe(trend_table(series, trend_kpi), hide_index=True, width="stretch")

with qa_tab:
    st.subheader("Data Trust & Publication QA")
    qa_class = {"PASS": "qa-pass", "WARNING": "qa-warning", "REVIEW": "qa-review", "FAIL": "qa-review"}.get(qa.status, "")
    st.markdown(
        f'<div class="qa-card"><strong class="{qa_class}">{qa.status}</strong><br>{qa.publication_state}<br><span class="scope-note">{qa.reason}</span></div>',
        unsafe_allow_html=True,
    )
    st.write("")
    st.markdown("**Source coverage**")
    st.dataframe(
        [
            {
                "Source": item.get("label", item.get("source_key", "Unknown")),
                "Rows loaded": item.get("rows_loaded", 0),
                "Trusted rows": item.get("trusted_rows", 0),
                "Warnings": item.get("warning_count", 0),
            }
            for item in dataset.source_summaries
        ],
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Deterministic checks**")
    evaluation = visible_evaluation_summary(dataset)
    st.write(f"{evaluation['passed']}/{evaluation['total']} checks passed across the bundled dataset.")
    st.dataframe(
        [{"Check": result.name, "Status": "PASS" if result.passed else "REVIEW", "Evidence": result.evidence} for result in evaluation["results"]],
        hide_index=True,
        width="stretch",
    )
    if qa.findings:
        st.markdown("**Findings for selected week**")
        st.dataframe([finding.as_dict() for finding in qa.findings], hide_index=True, width="stretch")
    else:
        st.success("No source-integrity findings for the selected week.")

st.divider()
st.caption("Scope note: this is a synthetic portfolio demonstration, not a clinical system, patient-data workflow, or production attribution model.")
