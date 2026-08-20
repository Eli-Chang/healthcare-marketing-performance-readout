"""Trusted, single-KPI trend series for the Client Report."""

from __future__ import annotations

from typing import Any

from .analytics import calculate_metrics
from .validation import Dataset


TREND_KPIS: dict[str, dict[str, str]] = {
    "Spend": {"key": "spend", "format": "currency"},
    "Qualified Leads": {"key": "qualified_leads", "format": "number"},
    "CPQL": {"key": "cost_per_qualified_lead", "format": "currency"},
    "Conversions": {"key": "conversions", "format": "number"},
    "Cost per Conversion": {"key": "cost_per_conversion", "format": "currency"},
    "Lead Qualification Rate": {"key": "lead_qualification_rate", "format": "percent"},
}
BREAKDOWNS = ("Overall", "Channel", "Campaign")
TREND_MODES = ("Weekly", "4-week rolling")


def validate_week_range(week_starts: list[str], start_week: str, end_week: str) -> None:
    """Fail closed when the selected range is not present or is reversed."""

    if start_week not in week_starts or end_week not in week_starts:
        raise ValueError("Trend Explorer weeks must come from the available reporting weeks.")
    if week_starts.index(start_week) > week_starts.index(end_week):
        raise ValueError("Trend Explorer start week cannot be after the end week.")


def default_week_range(week_starts: list[str], lookback_weeks: int = 8) -> tuple[str, str]:
    """Return the last bounded range available in the dataset."""

    if not week_starts:
        raise ValueError("Trend Explorer requires at least one reporting week.")
    start_index = max(0, len(week_starts) - lookback_weeks)
    return week_starts[start_index], week_starts[-1]


def _group_name(row: dict[str, Any], breakdown: str) -> str:
    if breakdown == "Overall":
        return "Overall"
    return str(row.get("channel") if breakdown == "Channel" else row.get("campaign") or "Unknown")


def _metric_value(metrics: dict[str, Any], kpi: str) -> float | int | None:
    key = TREND_KPIS[kpi]["key"]
    return metrics.get(key)


def build_trend_series(
    dataset: Dataset,
    start_week: str,
    end_week: str,
    kpi: str,
    breakdown: str,
    mode: str = "Weekly",
) -> list[dict[str, Any]]:
    """Build one compatible KPI series per selected breakdown value.

    Every aggregation uses ``Dataset.valid_rows``. Rolling ratio metrics are
    calculated from the aggregate numerator and denominator in each window,
    never by averaging the weekly ratios.
    """

    weeks = dataset.week_starts
    validate_week_range(weeks, start_week, end_week)
    if kpi not in TREND_KPIS:
        raise ValueError(f"Unknown Trend Explorer KPI: {kpi}")
    if breakdown not in BREAKDOWNS:
        raise ValueError(f"Unknown Trend Explorer breakdown: {breakdown}")
    if mode not in TREND_MODES:
        raise ValueError(f"Unknown Trend Explorer mode: {mode}")

    selected_weeks = weeks[weeks.index(start_week) : weeks.index(end_week) + 1]
    rows: list[dict[str, Any]] = []
    for week in selected_weeks:
        if mode == "Weekly":
            window_weeks = [week]
            label = week
        else:
            end_index = weeks.index(week)
            window_weeks = weeks[max(0, end_index - 3) : end_index + 1]
            label = week

        window_rows = [row for row in dataset.valid_rows if row.get("week_start") in window_weeks]
        groups = sorted({_group_name(row, breakdown) for row in dataset.rows})
        if breakdown == "Overall":
            groups = ["Overall"] if dataset.rows else []
        for group in groups:
            grouped_rows = [row for row in window_rows if _group_name(row, breakdown) == group]
            metrics = calculate_metrics(grouped_rows)
            rows.append(
                {
                    "week": label,
                    "series": group,
                    "value": _metric_value(metrics, kpi) if grouped_rows else None,
                    "trusted_row_count": len(grouped_rows),
                    "window_weeks": list(window_weeks),
                    "mode": mode,
                    "kpi": kpi,
                    "breakdown": breakdown,
                }
            )
    return rows


def trend_table(series: list[dict[str, Any]], kpi: str) -> list[dict[str, Any]]:
    """Create a compact inspectable table from a chart series."""

    number_format = TREND_KPIS[kpi]["format"]
    output: list[dict[str, Any]] = []
    for item in series:
        value = item["value"]
        if value is None:
            display = "N/A"
        elif number_format == "currency":
            display = f"${float(value):,.2f}"
        elif number_format == "percent":
            display = f"{float(value):.1%}"
        else:
            display = f"{float(value):,.0f}"
        output.append({"Week": item["week"], "Series": item["series"], kpi: display})
    return output
