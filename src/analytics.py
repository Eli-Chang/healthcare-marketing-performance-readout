"""Deterministic KPI calculations and verified weekly facts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .pipeline import load_bundled_dataset
from .validation import Dataset

BASE_METRICS = (
    "spend",
    "impressions",
    "clicks",
    "leads",
    "crm_leads",
    "qualified_leads",
    "conversions",
)
DERIVED_METRICS = (
    "cpc",
    "cost_per_lead",
    "cost_per_qualified_lead",
    "cost_per_conversion",
    "lead_qualification_rate",
    "lead_to_qualified_rate",
    "qualified_to_conversion_rate",
    "lead_to_conversion_rate",
)
CHANGE_METRICS = BASE_METRICS + DERIVED_METRICS


def safe_divide(numerator: float | int | None, denominator: float | int | None) -> float | None:
    """Return a ratio only when the denominator is meaningful."""

    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def calculate_metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate trusted rows and derive only logically supported ratios."""

    row_list = list(rows)
    totals: dict[str, float | int] = {}
    for metric in BASE_METRICS:
        totals[metric] = sum(float(row.get(metric, 0)) for row in row_list if row.get(metric) is not None)

    for metric in ("impressions", "clicks", "leads", "crm_leads", "qualified_leads", "conversions"):
        totals[metric] = int(totals[metric])

    totals["spend"] = round(float(totals["spend"]), 2)
    totals["cpc"] = safe_divide(totals["spend"], totals["clicks"])
    totals["cost_per_lead"] = safe_divide(totals["spend"], totals["leads"])
    totals["cost_per_qualified_lead"] = safe_divide(totals["spend"], totals["qualified_leads"])
    totals["cost_per_conversion"] = safe_divide(totals["spend"], totals["conversions"])
    totals["lead_qualification_rate"] = safe_divide(totals["qualified_leads"], totals["leads"])
    totals["lead_to_qualified_rate"] = safe_divide(totals["qualified_leads"], totals["leads"])
    totals["qualified_to_conversion_rate"] = safe_divide(totals["conversions"], totals["qualified_leads"])
    totals["lead_to_conversion_rate"] = safe_divide(totals["conversions"], totals["leads"])
    totals["row_count"] = len(row_list)
    return totals


def calculate_change(current: Any, prior: Any) -> dict[str, Any]:
    """Calculate a transparent absolute and percentage week-over-week change."""

    if current is None or prior is None:
        return {"current": current, "prior": prior, "absolute": None, "percent": None}
    absolute = float(current) - float(prior)
    percent = None if float(prior) == 0 else absolute / float(prior)
    return {
        "current": current,
        "prior": prior,
        "absolute": round(absolute, 4),
        "percent": round(percent, 6) if percent is not None else None,
    }


def _round_metric(value: Any) -> Any:
    if value is None or isinstance(value, int):
        return value
    return round(float(value), 6)


def _metrics_for_scope(rows: list[dict[str, Any]], week_start: str | None, scope: str | None = None) -> dict[str, Any]:
    scoped = [
        row
        for row in rows
        if (week_start is None or row.get("week_start") == week_start)
        and (scope is None or row.get("channel") == scope)
    ]
    return calculate_metrics(scoped)


def _metrics_for_campaign(rows: list[dict[str, Any]], week_start: str | None, campaign_id: str) -> dict[str, Any]:
    scoped = [
        row
        for row in rows
        if (week_start is None or row.get("week_start") == week_start)
        and row.get("campaign_id") == campaign_id
    ]
    return calculate_metrics(scoped)


def build_weekly_readout(dataset: Dataset, week_start: str) -> dict[str, Any]:
    """Build the structured facts that the UI and optional model layer consume."""

    all_weeks = dataset.week_starts
    if week_start not in all_weeks:
        raise ValueError(f"Unknown reporting week: {week_start}")

    week_index = all_weeks.index(week_start)
    prior_week = all_weeks[week_index - 1] if week_index > 0 else None
    current_rows = [row for row in dataset.valid_rows if row["week_start"] == week_start]
    prior_rows = [row for row in dataset.valid_rows if prior_week and row["week_start"] == prior_week]
    current_metrics = calculate_metrics(current_rows)
    prior_metrics = calculate_metrics(prior_rows) if prior_week else None

    changes = {
        metric: calculate_change(
            current_metrics.get(metric),
            prior_metrics.get(metric) if prior_metrics else None,
        )
        for metric in CHANGE_METRICS
    }

    channels = sorted(
        {
            row["channel"]
            for row in dataset.rows
            if row.get("week_start") in {week_start, prior_week} and row.get("channel")
        }
    )
    channel_performance: list[dict[str, Any]] = []
    for channel in channels:
        current = _metrics_for_scope(dataset.valid_rows, week_start, channel)
        prior = _metrics_for_scope(dataset.valid_rows, prior_week, channel) if prior_week else None
        channel_performance.append(
            {
                "channel": channel,
                "current": current,
                "prior": prior,
                "changes": {
                    metric: calculate_change(current.get(metric), prior.get(metric) if prior else None)
                    for metric in CHANGE_METRICS
                },
            }
        )

    campaign_keys = sorted(
        {
            (row.get("campaign_id"), row.get("campaign"), row.get("channel"))
            for row in dataset.rows
            if row.get("campaign_id") and row.get("campaign")
        },
        key=lambda item: (item[2], item[1]),
    )
    campaign_performance: list[dict[str, Any]] = []
    for campaign_id, campaign_name, channel in campaign_keys:
        current = _metrics_for_campaign(dataset.valid_rows, week_start, campaign_id)
        prior = _metrics_for_campaign(dataset.valid_rows, prior_week, campaign_id) if prior_week else None
        campaign_performance.append(
            {
                "campaign_id": campaign_id,
                "campaign": campaign_name,
                "channel": channel,
                "current": current,
                "prior": prior,
                "changes": {
                    metric: calculate_change(current.get(metric), prior.get(metric) if prior else None)
                    for metric in CHANGE_METRICS
                },
            }
        )

    warnings = [
        warning.as_dict()
        for warning in dataset.warnings
        if warning.week_start in {week_start, prior_week}
    ]
    source_rows = [row for row in dataset.rows if row.get("week_start") == week_start]
    facts = {
        "client": dataset.client_name,
        "reporting_week": week_start,
        "prior_week": prior_week,
        "current_metrics": {key: _round_metric(value) for key, value in current_metrics.items()},
        "prior_metrics": (
            {key: _round_metric(value) for key, value in prior_metrics.items()} if prior_metrics else None
        ),
        "changes": changes,
        "channel_performance": channel_performance,
        "campaign_performance": campaign_performance,
        "validation_warnings": warnings,
        "source_summaries": dataset.source_summaries,
        "reconciliation": dataset.reconciliation,
        "valid_row_count": len(current_rows),
        "source_row_count": len(source_rows),
    }
    return {
        "client": dataset.client_name,
        "reporting_week": week_start,
        "prior_week": prior_week,
        "current_metrics": current_metrics,
        "prior_metrics": prior_metrics,
        "changes": changes,
        "channel_performance": channel_performance,
        "campaign_performance": campaign_performance,
        "validation_warnings": warnings,
        "source_summaries": dataset.source_summaries,
        "reconciliation": dataset.reconciliation,
        "valid_row_count": len(current_rows),
        "source_row_count": len(source_rows),
        "facts": facts,
        "source_rows": source_rows,
    }


def load_readout_dataset(project_root: str | Path) -> Dataset:
    """Convenience loader used by the app and command-line checks."""

    return load_bundled_dataset(project_root)
