"""Transparent proof-of-concept rules for noteworthy changes."""

from __future__ import annotations

from typing import Any

POC_THRESHOLDS = {
    "material_percent_change": 0.20,
    "material_qualified_lead_absolute_change": 3,
    "material_conversion_absolute_change": 2,
    "material_spend_increase": 0.25,
    "outcome_proportionality_fraction": 0.50,
    "campaign_driver_fraction": 0.50,
}


def _is_material(change: dict[str, Any], minimum_absolute: float = 0) -> bool:
    absolute = change.get("absolute")
    percent = change.get("percent")
    return (
        absolute is not None
        and percent is not None
        and abs(float(absolute)) >= minimum_absolute
        and abs(float(percent)) >= POC_THRESHOLDS["material_percent_change"]
    )


def _observation(
    *,
    classification: str,
    scope: str,
    metric: str,
    current: Any,
    prior: Any,
    change: dict[str, Any],
    summary: str,
    confidence: str,
    why_it_matters: str,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "scope": scope,
        "metric": metric,
        "current_value": current,
        "prior_value": prior,
        "absolute_change": change.get("absolute"),
        "percent_change": change.get("percent"),
        "summary": summary,
        "confidence": confidence,
        "why_it_matters": why_it_matters,
    }


def detect_observations(readout: dict[str, Any]) -> list[dict[str, Any]]:
    """Return evidence-backed observations before any narrative generation."""

    observations: list[dict[str, Any]] = []
    for channel_data in readout["channel_performance"]:
        channel = channel_data["channel"]
        current = channel_data["current"]
        prior = channel_data["prior"] or {}
        changes = channel_data["changes"]

        qualified_change = changes["qualified_leads"]
        cpql_change = changes["cost_per_qualified_lead"]
        spend_change = changes["spend"]
        conversion_change = changes["conversions"]

        if (
            _is_material(qualified_change, POC_THRESHOLDS["material_qualified_lead_absolute_change"])
            and cpql_change.get("percent") is not None
            and float(cpql_change["percent"]) <= -POC_THRESHOLDS["material_percent_change"]
        ):
            observations.append(
                _observation(
                    classification="efficiency_improvement",
                    scope=channel,
                    metric="cost_per_qualified_lead",
                    current=current.get("cost_per_qualified_lead"),
                    prior=prior.get("cost_per_qualified_lead"),
                    change=cpql_change,
                    summary=(
                        f"{channel} qualified leads increased while cost per qualified lead improved materially."
                    ),
                    confidence="high",
                    why_it_matters="The calculated trend is positive, but the supplied fields do not establish causality.",
                )
            )

        spend_percent = spend_change.get("percent")
        qualified_percent = qualified_change.get("percent")
        if (
            spend_percent is not None
            and float(spend_percent) >= POC_THRESHOLDS["material_spend_increase"]
            and (
                qualified_percent is None
                or float(qualified_percent)
                < float(spend_percent) * POC_THRESHOLDS["outcome_proportionality_fraction"]
            )
        ):
            observations.append(
                _observation(
                    classification="spend_without_proportional_outcome",
                    scope=channel,
                    metric="spend",
                    current=current.get("spend"),
                    prior=prior.get("spend"),
                    change=spend_change,
                    summary=(
                        f"{channel} spend increased materially without a proportional qualified-lead increase."
                    ),
                    confidence="high",
                    why_it_matters="This is a review signal, not evidence for an immediate budget decision.",
                )
            )

        if (
            qualified_change.get("percent") is not None
            and float(qualified_change["percent"]) <= -POC_THRESHOLDS["material_percent_change"]
            and abs(float(qualified_change.get("absolute") or 0))
            >= POC_THRESHOLDS["material_qualified_lead_absolute_change"]
        ):
            observations.append(
                _observation(
                    classification="channel_underperformance",
                    scope=channel,
                    metric="qualified_leads",
                    current=current.get("qualified_leads"),
                    prior=prior.get("qualified_leads"),
                    change=qualified_change,
                    summary=f"{channel} qualified leads declined materially week over week.",
                    confidence="medium",
                    why_it_matters="The decline is visible in the supplied data, but no driver is provided.",
                )
            )

        conversion_abs = abs(float(conversion_change.get("absolute") or 0))
        if (
            conversion_change.get("percent") is not None
            and conversion_abs >= POC_THRESHOLDS["material_conversion_absolute_change"]
            and abs(float(conversion_change["percent"])) >= POC_THRESHOLDS["material_percent_change"]
        ):
            observations.append(
                _observation(
                    classification="change_without_cause",
                    scope=channel,
                    metric="conversions",
                    current=current.get("conversions"),
                    prior=prior.get("conversions"),
                    change=conversion_change,
                    summary=f"{channel} conversions changed materially, but the supplied data do not explain why.",
                    confidence="medium",
                    why_it_matters="The readout should describe the movement without inventing a causal explanation.",
                )
            )

    if readout["validation_warnings"]:
        invalid_campaigns = sorted(
            {
                row.get("campaign")
                for row in readout.get("source_rows", [])
                if not row.get("is_valid_for_metrics") and row.get("campaign")
            }
        )
        campaign_scope = ", ".join(invalid_campaigns) if invalid_campaigns else "the affected source rows"
        observations.insert(
            0,
            {
                "classification": "data_quality",
                "scope": campaign_scope,
                "metric": "validation_warnings",
                "current_value": len(readout["validation_warnings"]),
                "prior_value": None,
                "absolute_change": None,
                "percent_change": None,
                "summary": f"Data quality limits confident reporting for {campaign_scope}; one or more source rows were excluded from KPI rollups.",
                "confidence": "high",
                "why_it_matters": "Correct or confirm the source row before treating the affected campaign trend as decision-ready.",
            },
        )

    for campaign_data in readout.get("campaign_performance", []):
        current = campaign_data["current"]
        prior = campaign_data["prior"] or {}
        changes = campaign_data["changes"]
        qualified_change = changes["qualified_leads"]
        cpql_change = changes["cost_per_qualified_lead"]
        if (
            _is_material(qualified_change, POC_THRESHOLDS["material_qualified_lead_absolute_change"])
            and cpql_change.get("percent") is not None
            and float(cpql_change["percent"]) <= -POC_THRESHOLDS["material_percent_change"]
        ):
            observations.append(
                _observation(
                    classification="campaign_efficiency_improvement",
                    scope=campaign_data["campaign"],
                    metric="cost_per_qualified_lead",
                    current=current.get("cost_per_qualified_lead"),
                    prior=prior.get("cost_per_qualified_lead"),
                    change=cpql_change,
                    summary=f"{campaign_data['campaign']} improved qualified-lead efficiency on the calculated campaign metrics.",
                    confidence="high",
                    why_it_matters="This identifies a campaign-level movement, not a causal explanation for why it happened.",
                )
            )

    for channel_data in readout.get("channel_performance", []):
        channel_qualified_change = channel_data["changes"]["qualified_leads"]
        channel_delta = abs(float(channel_qualified_change.get("absolute") or 0))
        if channel_delta < POC_THRESHOLDS["material_qualified_lead_absolute_change"]:
            continue
        campaign_changes = [
            campaign
            for campaign in readout.get("campaign_performance", [])
            if campaign["channel"] == channel_data["channel"]
        ]
        driver = max(
            campaign_changes,
            key=lambda campaign: abs(float(campaign["changes"]["qualified_leads"].get("absolute") or 0)),
            default=None,
        )
        if driver is None:
            continue
        driver_delta = abs(float(driver["changes"]["qualified_leads"].get("absolute") or 0))
        if driver_delta / channel_delta >= POC_THRESHOLDS["campaign_driver_fraction"]:
            observations.append(
                {
                    "classification": "campaign_driver",
                    "scope": channel_data["channel"],
                    "metric": "qualified_leads",
                    "current_value": driver["current"].get("qualified_leads"),
                    "prior_value": (driver["prior"] or {}).get("qualified_leads"),
                    "absolute_change": driver["changes"]["qualified_leads"].get("absolute"),
                    "percent_change": driver["changes"]["qualified_leads"].get("percent"),
                    "summary": f"{driver['campaign']} contributed {driver_delta / channel_delta:.0%} of {channel_data['channel']}'s qualified-lead movement.",
                    "confidence": "high",
                    "why_it_matters": "This is a calculated contribution share; the supplied fields do not prove campaign causality.",
                }
            )

    if not observations:
        observations.append(
            {
                "classification": "stable_week",
                "scope": "overall",
                "metric": "overall_performance",
                "current_value": readout["current_metrics"],
                "prior_value": readout["prior_metrics"],
                "absolute_change": None,
                "percent_change": None,
                "summary": "No calculated movement crossed the proof-of-concept materiality rules.",
                "confidence": "high",
                "why_it_matters": "A stable week should not be turned into a dramatic narrative.",
            }
        )

    return observations


def recommended_follow_up(observations: list[dict[str, Any]]) -> list[str]:
    """Produce restrained follow-up prompts, never automated business decisions."""

    classifications = {observation["classification"] for observation in observations}
    follow_up: list[str] = []
    if "data_quality" in classifications:
        follow_up.append("Validate or correct the flagged source row before relying on this week's trend.")
    if "efficiency_improvement" in classifications:
        follow_up.append("Check whether the improvement persists for another week and ask what changed operationally.")
    if "spend_without_proportional_outcome" in classifications:
        follow_up.append(
            "Review the Google inputs and the next week's quality before considering any budget change; one week is not enough evidence for a drastic reallocation."
        )
    if "channel_underperformance" in classifications:
        follow_up.append("Investigate the next period and the underlying campaign context before assigning a cause.")
    if "change_without_cause" in classifications:
        follow_up.append("Ask what documented campaign or funnel change coincided with the movement; these fields do not explain it.")
    if "stable_week" in classifications:
        follow_up.append("Continue monitoring; no major budget or workflow change is supported by this week's movement alone.")
    return follow_up
