"""Executable deterministic evaluation harness for the interview demo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analytics import build_weekly_readout, calculate_metrics
from .observations import detect_observations, recommended_follow_up
from .pipeline import process_source_files
from .trends import build_trend_series
from .validation import Dataset

SCENARIO_WEEKS = {
    "efficiency improvement": "2026-01-19",
    "spend increase without proportional outcome": "2026-01-26",
    "data-quality problem": "2026-02-09",
    "stable week": "2026-02-02",
    "unexplained change": "2026-02-16",
}


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    passed: bool
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "evidence": self.evidence}


def run_evaluations(dataset: Dataset) -> list[EvaluationResult]:
    """Run five repeatable checks against the actual fixed dataset."""

    results: list[EvaluationResult] = []

    efficiency = build_weekly_readout(dataset, SCENARIO_WEEKS["efficiency improvement"])
    efficiency_observations = detect_observations(efficiency)
    meta = next(item for item in efficiency["channel_performance"] if item["channel"] == "Meta")
    cpql_percent = meta["changes"]["cost_per_qualified_lead"]["percent"]
    results.append(
        EvaluationResult(
            "Efficiency improvement",
            any(item["classification"] == "efficiency_improvement" for item in efficiency_observations)
            and cpql_percent is not None
            and cpql_percent <= -0.20
            and meta["current"]["qualified_leads"] == 50,
            f"Meta qualified leads={meta['current']['qualified_leads']}; CPQL change={cpql_percent:.1%}.",
        )
    )

    spend = build_weekly_readout(dataset, SCENARIO_WEEKS["spend increase without proportional outcome"])
    spend_observations = detect_observations(spend)
    spend_follow_up = recommended_follow_up(spend_observations)
    spend_follow_up_text = " ".join(spend_follow_up).lower()
    results.append(
        EvaluationResult(
            "Spend increase without proportional outcome",
            any(item["classification"] == "spend_without_proportional_outcome" for item in spend_observations)
            and "one week" in spend_follow_up_text
            and "drastic reallocation" in spend_follow_up_text
            and "cut the budget" not in spend_follow_up_text,
            f"Flags={sum(item['classification'] == 'spend_without_proportional_outcome' for item in spend_observations)}; follow-up is review-only.",
        )
    )

    quality = build_weekly_readout(dataset, SCENARIO_WEEKS["data-quality problem"])
    quality_observations = detect_observations(quality)
    results.append(
        EvaluationResult(
            "Data-quality problem",
            bool(quality["validation_warnings"])
            and any(item["classification"] == "data_quality" for item in quality_observations)
            and quality["valid_row_count"] < quality["source_row_count"],
            f"Warnings={len(quality['validation_warnings'])}; valid rows={quality['valid_row_count']}/{quality['source_row_count']}.",
        )
    )

    stable = build_weekly_readout(dataset, SCENARIO_WEEKS["stable week"])
    stable_observations = detect_observations(stable)
    results.append(
        EvaluationResult(
            "Stable week",
            len(stable_observations) == 1 and stable_observations[0]["classification"] == "stable_week",
            "Only the stable_week classification was produced; no material change crossed the configured rules.",
        )
    )

    unexplained = build_weekly_readout(dataset, SCENARIO_WEEKS["unexplained change"])
    unexplained_observations = detect_observations(unexplained)
    forbidden_causal_phrases = ("creative improved", "targeting worked better", "the audience changed")
    narrative_text = " ".join(item["summary"] + " " + item["why_it_matters"] for item in unexplained_observations).lower()
    results.append(
        EvaluationResult(
            "Unexplained change",
            any(item["classification"] == "change_without_cause" for item in unexplained_observations)
            and not any(phrase in narrative_text for phrase in forbidden_causal_phrases),
            "Conversion movement is flagged with an explicit no-causality limitation.",
        )
    )

    return results


def run_pipeline_evaluations(dataset: Dataset) -> list[EvaluationResult]:
    """Run checks for the Version 2 source and reconciliation path."""

    results: list[EvaluationResult] = []
    source_keys = {summary.get("source_key") for summary in dataset.source_summaries}
    results.append(
        EvaluationResult(
            "Three separated sources",
            source_keys == {"google", "meta", "crm"}
            and all(summary.get("rows_loaded", 0) > 0 for summary in dataset.source_summaries),
            f"Sources={', '.join(sorted(source_keys))}; each bundled export loaded rows.",
        )
    )
    canonical_fields = {"date", "channel", "campaign_id", "campaign_name", "spend", "impressions", "clicks", "platform_leads"}
    normalized_fields = set(dataset.normalized_media_rows[0]) if dataset.normalized_media_rows else set()
    results.append(
        EvaluationResult(
            "Media normalization",
            canonical_fields.issubset(normalized_fields)
            and {row.get("channel") for row in dataset.normalized_media_rows} == {"Google", "Meta"},
            f"Canonical media rows={len(dataset.normalized_media_rows)}; channels=Google and Meta.",
        )
    )
    recon = dataset.reconciliation
    results.append(
        EvaluationResult(
            "CRM reconciliation",
            recon.get("successfully_attributed", 0) > 0
            and recon.get("unmatched", 0) == 1
            and recon.get("duplicate_records_detected", 0) == 1,
            f"Attributed={recon.get('successfully_attributed')}; unmatched={recon.get('unmatched')}; duplicates={recon.get('duplicate_records_detected')}.",
        )
    )
    results.append(
        EvaluationResult(
            "Unified reporting dataset",
            len(dataset.rows) == 32 and len(dataset.valid_rows) == 31 and all("qualified_leads" in row for row in dataset.rows),
            f"Unified rows={len(dataset.rows)}; trusted rows={len(dataset.valid_rows)}.",
        )
    )
    readout = build_weekly_readout(dataset, SCENARIO_WEEKS["efficiency improvement"])
    observations = detect_observations(readout)
    results.append(
        EvaluationResult(
            "Campaign driver detection",
            any(item["classification"] == "campaign_driver" for item in observations)
            and any(item["classification"] == "campaign_efficiency_improvement" for item in observations),
            "The efficient week identifies both the campaign movement and its calculated channel contribution.",
        )
    )
    quality = build_weekly_readout(dataset, SCENARIO_WEEKS["data-quality problem"])
    results.append(
        EvaluationResult(
            "Invalid source row handling",
            len(quality["validation_warnings"]) >= 1
            and quality["source_row_count"] == 4
            and quality["valid_row_count"] == 3,
            f"Affected week trusted rows={quality['valid_row_count']}/{quality['source_row_count']}; warnings={len(quality['validation_warnings'])}.",
        )
    )
    zero_metrics = calculate_metrics(
        [{"spend": 100, "impressions": 10, "clicks": 0, "leads": 0, "crm_leads": 0, "qualified_leads": 0, "conversions": 0}]
    )
    results.append(
        EvaluationResult(
            "Safe zero denominators",
            zero_metrics["cpc"] is None and zero_metrics["cost_per_qualified_lead"] is None,
            "Zero denominators produce n/a ratios rather than an exception or fabricated rate.",
        )
    )
    missing_upload = process_source_files({"google": b"date,campaign_id,campaign_name,impressions,clicks,spend\n", "meta": b"report_date,campaign_key,campaign,impressions,link_clicks,amount_spent\n"})
    results.append(
        EvaluationResult(
            "Upload schema guard",
            not missing_upload.rows and any(w.code == "missing_source_file" for w in missing_upload.warnings),
            "The shared pipeline fails closed when one of the three proof-of-concept files is missing.",
        )
    )

    normal_weeks = {
        "2026-01-05",
        "2026-01-12",
        "2026-01-19",
        "2026-01-26",
        "2026-02-02",
        "2026-02-23",
    }
    normal_metrics = [build_weekly_readout(dataset, week)["current_metrics"] for week in sorted(normal_weeks)]
    realism_pass = all(
        20_000 <= metrics["spend"] <= 30_000
        and 70 <= metrics["qualified_leads"] <= 120
        and 200 <= metrics["cost_per_qualified_lead"] <= 350
        and 15 <= metrics["conversions"] <= 30
        and 800 <= metrics["cost_per_conversion"] <= 1_600
        and 0.45 <= metrics["lead_qualification_rate"] <= 0.65
        for metrics in normal_metrics
    )
    results.append(
        EvaluationResult(
            "Bundled funnel realism",
            realism_pass,
            f"Checked {len(normal_metrics)} trusted normal weeks against scale, CPQL, conversion, and qualification-rate ranges; defect weeks remain explicit exceptions.",
        )
    )

    platform_leads = sum(
        row["platform_leads"]
        for row in dataset.normalized_media_rows
        if row.get("platform_leads") is not None
    )
    attribution_rate = recon.get("successfully_attributed", 0) / platform_leads if platform_leads else 0
    relationship_pass = (
        0.85 <= attribution_rate <= 1.0
        and all(
            row.get("impressions", 0) >= row.get("clicks", 0)
            and (
                row.get("leads") is None
                or row.get("clicks", 0) >= row.get("leads", 0)
            )
            and row.get("qualified_leads", 0) <= row.get("crm_leads", 0)
            and row.get("conversions", 0) <= row.get("qualified_leads", 0)
            and (
                row.get("platform_leads") is None
                or row.get("crm_leads", 0) <= row.get("platform_leads", 0)
            )
            for row in dataset.valid_rows
        )
        and all(
            0 < row["qualified_leads"] < row["crm_leads"]
            for row in dataset.valid_rows
            if row.get("crm_leads")
        )
    )
    results.append(
        EvaluationResult(
            "Funnel relationship and reconciliation guard",
            relationship_pass,
            f"Platform leads={platform_leads}; attributed CRM={recon.get('successfully_attributed')}; attribution ratio={attribution_rate:.1%}; clicks, leads, qualification, and conversion relationships were checked.",
        )
    )
    return results


def evaluation_summary(dataset: Dataset) -> dict[str, Any]:
    results = run_evaluations(dataset)
    passed = sum(result.passed for result in results)
    return {"passed": passed, "total": len(results), "all_passed": passed == len(results), "results": results}


def pipeline_evaluation_summary(dataset: Dataset) -> dict[str, Any]:
    results = run_pipeline_evaluations(dataset)
    passed = sum(result.passed for result in results)
    return {"passed": passed, "total": len(results), "all_passed": passed == len(results), "results": results}


def visible_evaluation_summary(dataset: Dataset) -> dict[str, Any]:
    """Return only the checks that belong in the pilot-facing QA surface."""

    core = evaluation_summary(dataset)
    pipeline = pipeline_evaluation_summary(dataset)
    results = [*core["results"], *pipeline["results"]]
    passed = sum(result.passed for result in results)
    return {
        "passed": passed,
        "total": len(results),
        "all_passed": passed == len(results),
        "results": results,
        "core": core,
        "pipeline": pipeline,
    }
