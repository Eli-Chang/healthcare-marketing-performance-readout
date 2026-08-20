"""Deterministic reporting QA and publication routing.

The QA engine evaluates data integrity and source trust. It deliberately does
not treat poor marketing performance as a data problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Mapping

PASS = "PASS"
WARNING = "WARNING"
REVIEW = "REVIEW"
FAIL = "FAIL"

PUBLICATION_STATES = {
    PASS: "published_automatically",
    WARNING: "published_with_warnings",
    REVIEW: "review_required",
    FAIL: "failed_incomplete",
}

_INTEGRITY_FAIL_CODES = {
    "missing_source_file",
    "missing_columns",
    "read_error",
    "invalid_date",
    "missing_value",
    "not_numeric",
    "not_finite",
    "non_integer_count",
    "negative_value",
    "impossible_relationship",
    "duplicate_lead",
    "unmatched_campaign",
    "unknown_campaign",
    "invalid_lead_record",
    "source_period_mismatch",
}


@dataclass(frozen=True)
class QAFinding:
    severity: str
    code: str
    title: str
    message: str
    source: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "details": self.details,
        }


@dataclass(frozen=True)
class QARouting:
    status: str
    publication_state: str
    reason: str
    findings: tuple[QAFinding, ...]
    client_quality_summary: dict[str, Any]

    @property
    def auto_publish(self) -> bool:
        return self.status in {PASS, WARNING}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "publication_state": self.publication_state,
            "reason": self.reason,
            "findings": [finding.as_dict() for finding in self.findings],
            "client_quality_summary": self.client_quality_summary,
        }


def _warning_rows(dataset: Any, week_start: str) -> list[Any]:
    return [warning for warning in dataset.warnings if warning.week_start == week_start]


def _source_status(dataset: Any, expected_sources: Iterable[str]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    expected = [str(source) for source in expected_sources]
    summaries = {str(row.get("source_key")): row for row in dataset.source_summaries}
    missing = [source for source in expected if not summaries.get(source) or not int(summaries[source].get("rows_loaded") or 0)]
    return missing, summaries


def _historical_signal(dataset: Any, week_start: str, *, source: str) -> tuple[float, float] | None:
    values: list[float] = []
    for week in dataset.week_starts:
        if week >= week_start:
            continue
        rows = [
            row for row in dataset.normalized_media_rows
            if row.get("source") == source and row.get("week_start") == week and row.get("platform_leads") is not None
        ]
        values.append(sum(float(row.get("platform_leads") or 0) for row in rows))
    current = sum(
        float(row.get("platform_leads") or 0)
        for row in dataset.normalized_media_rows
        if row.get("source") == source and row.get("week_start") == week_start and row.get("platform_leads") is not None
    )
    if len(values) < 3 or current <= 0:
        return None
    baseline = float(median(values))
    return current, baseline


def evaluate_report_week(
    dataset: Any,
    week_start: str,
    *,
    expected_sources: Iterable[str] = ("google", "meta", "crm"),
    recoverable_warning_codes: Iterable[str] = (),
) -> QARouting:
    """Evaluate one reporting week using only deterministic source evidence."""

    expected = [str(source) for source in expected_sources]
    recoverable = {str(code) for code in recoverable_warning_codes}
    missing_sources, summaries = _source_status(dataset, expected)
    findings: list[QAFinding] = []

    for source in missing_sources:
        label = {"google": "Google Ads", "meta": "Meta Ads", "crm": "CRM"}.get(source, source.title())
        findings.append(
            QAFinding(
                FAIL,
                "missing_source_file",
                "Expected source missing",
                f"Publication blocked: the expected {label} source has not been received for the reporting week.",
                source,
            )
        )

    source_weeks = getattr(dataset, "source_week_starts", {}) or {}
    for source in expected:
        if source in missing_sources:
            continue
        available_weeks = {str(value) for value in source_weeks.get(source, [])}
        if week_start not in available_weeks:
            label = {"google": "Google Ads", "meta": "Meta Ads", "crm": "CRM"}.get(source, source.title())
            findings.append(
                QAFinding(
                    FAIL,
                    "source_period_mismatch",
                    "Source reporting period does not match",
                    f"Publication blocked: the {label} export does not contain the expected reporting week {week_start}.",
                    source,
                    {"expected_week": week_start, "available_weeks": sorted(available_weeks)},
                )
            )

    week_rows = [row for row in dataset.rows if row.get("week_start") == week_start]
    trusted_rows = [row for row in dataset.valid_rows if row.get("week_start") == week_start]
    if not week_rows:
        findings.append(QAFinding(FAIL, "empty_reporting_period", "Reporting period is empty", f"Publication blocked: no source rows were received for {week_start}."))
    elif not trusted_rows:
        findings.append(QAFinding(FAIL, "no_trusted_rows", "No trusted reporting rows", f"Publication blocked: {week_start} has no rows that can responsibly enter KPI rollups."))

    week_warnings = _warning_rows(dataset, week_start)
    structural_crm_failure = any(
        warning.source == "crm" and warning.code == "missing_columns"
        for warning in week_warnings
    )
    for warning in week_warnings:
        if warning.code == "missing_optional_metric":
            continue
        if warning.code in recoverable:
            findings.append(
                QAFinding(
                    WARNING,
                    warning.code,
                    "Recoverable data-quality warning",
                    warning.message,
                    warning.source,
                    {"field": warning.field, "row_number": warning.row_number},
                )
            )
        elif warning.code in _INTEGRITY_FAIL_CODES:
            findings.append(
                QAFinding(
                    FAIL,
                    warning.code,
                    "Data integrity failure",
                    warning.message,
                    warning.source,
                    {"field": warning.field, "row_number": warning.row_number},
                )
            )

    if "crm" in expected and trusted_rows and not structural_crm_failure:
        media_rows = [row for row in dataset.normalized_media_rows if row.get("week_start") == week_start and row.get("platform_leads") is not None]
        platform_leads = sum(float(row.get("platform_leads") or 0) for row in media_rows)
        crm_leads = sum(float(row.get("crm_leads") or 0) for row in trusted_rows)
        if platform_leads > 0:
            ratio = crm_leads / platform_leads
            if ratio < 0.55 or ratio > 1.25:
                findings.append(
                    QAFinding(
                        REVIEW,
                        "attribution_discrepancy",
                        "Attribution anomaly requires review",
                        f"CRM attributed leads are {ratio:.0%} of platform-reported leads while the source files remain technically processable.",
                        "crm",
                        {"platform_leads": platform_leads, "crm_leads": crm_leads, "ratio": round(ratio, 4)},
                    )
                )

    for source in ("google", "meta"):
        signal = _historical_signal(dataset, week_start, source=source)
        if signal:
            current, baseline = signal
            if baseline and (current < baseline * 0.35 or current > baseline * 2.5):
                source_label = {"google": "Google Ads", "meta": "Meta Ads", "crm": "CRM"}.get(source, source.replace("_", " ").title())
                findings.append(
                    QAFinding(
                        REVIEW,
                        "historical_source_anomaly",
                        "Historical source anomaly requires review",
                        f"{source_label} platform leads are materially outside the recent source range ({current:.0f} versus a recent median of {baseline:.0f}).",
                        source,
                        {"current": current, "recent_median": baseline},
                    )
                )

    if any(finding.severity == FAIL for finding in findings):
        status = FAIL
        reason = next(finding.message for finding in findings if finding.severity == FAIL)
    elif any(finding.severity == REVIEW for finding in findings):
        status = REVIEW
        reason = next(finding.message for finding in findings if finding.severity == REVIEW)
    elif any(finding.severity == WARNING for finding in findings):
        status = WARNING
        reason = "The report was published with a recoverable data-quality warning; the affected record was excluded deterministically."
    else:
        status = PASS
        reason = "All configured source, schema, reconciliation, and integrity checks passed; the report was published automatically."

    received = sum(1 for source in expected if source not in missing_sources)
    warning_codes = {warning.code for warning in week_warnings}
    exact_duplicates = sum(1 for code in warning_codes if code == "duplicate_lead")
    unmapped = sum(1 for code in warning_codes if code in {"unknown_campaign", "unmatched_campaign"})
    attribution_findings = [finding for finding in findings if finding.code == "attribution_discrepancy"]
    summary = {
        "expected_sources": len(expected),
        "received_sources": received,
        "rows_processed": len(week_rows),
        "trusted_rows": len(trusted_rows),
        "exact_duplicates": exact_duplicates,
        "unmapped_campaigns": unmapped,
        "attribution_check": "review" if attribution_findings else "passed",
        "status_label": {
            PASS: "Published automatically",
            WARNING: "Published with warnings",
            REVIEW: "Publication held for review",
            FAIL: "Publication blocked",
        }[status],
    }
    return QARouting(status, PUBLICATION_STATES[status], reason, tuple(findings), summary)


def client_safe_quality_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the compact trust facts safe for a client report."""

    summary = report.get("client_quality_summary") or {}
    return {
        "expected_sources": int(summary.get("expected_sources") or 0),
        "received_sources": int(summary.get("received_sources") or 0),
        "rows_processed": int(summary.get("rows_processed") or 0),
        "trusted_rows": int(summary.get("trusted_rows") or 0),
        "exact_duplicates": int(summary.get("exact_duplicates") or 0),
        "unmapped_campaigns": int(summary.get("unmapped_campaigns") or 0),
        "attribution_check": str(summary.get("attribution_check") or "not available"),
        "status_label": str(summary.get("status_label") or "Published"),
    }
