"""Validation and normalization for the fixed synthetic campaign dataset.

Invalid rows are preserved for inspection but excluded from KPI rollups. The
prototype never imputes or silently repairs questionable source values.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = (
    "week_start",
    "channel",
    "campaign",
    "spend",
    "impressions",
    "clicks",
    "leads",
    "qualified_leads",
    "conversions",
)
COUNT_COLUMNS = (
    "impressions",
    "clicks",
    "leads",
    "qualified_leads",
    "conversions",
)
NUMERIC_COLUMNS = ("spend",) + COUNT_COLUMNS


@dataclass(frozen=True)
class ValidationWarning:
    """A structured, user-visible data quality warning."""

    row_number: int
    week_start: str | None
    field: str
    code: str
    message: str
    source: str = "legacy"

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "week_start": self.week_start,
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "source": self.source,
        }


@dataclass
class Dataset:
    """Normalized dataset plus the rows and warnings needed for inspection."""

    rows: list[dict[str, Any]]
    valid_rows: list[dict[str, Any]]
    warnings: list[ValidationWarning]
    source_summaries: list[dict[str, Any]] = field(default_factory=list)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    raw_exports: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    normalized_media_rows: list[dict[str, Any]] = field(default_factory=list)
    normalized_crm_rows: list[dict[str, Any]] = field(default_factory=list)
    campaign_catalog: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    source_week_starts: dict[str, list[str]] = field(default_factory=dict)
    client_name: str = "Synthetic HealthCo"

    @property
    def week_starts(self) -> list[str]:
        return sorted({row["week_start"] for row in self.rows if row.get("week_start")})

    def warning_dicts(self) -> list[dict[str, Any]]:
        return [warning.as_dict() for warning in self.warnings]


def _warning(
    warnings: list[ValidationWarning],
    *,
    row_number: int,
    week_start: str | None,
    field: str,
    code: str,
    message: str,
) -> None:
    warnings.append(
        ValidationWarning(
            row_number=row_number,
            week_start=week_start,
            field=field,
            code=code,
            message=message,
        )
    )


def _parse_number(
    value: str | None,
    *,
    field: str,
    row_number: int,
    week_start: str | None,
    warnings: list[ValidationWarning],
) -> float | int | None:
    if value is None or not str(value).strip():
        _warning(
            warnings,
            row_number=row_number,
            week_start=week_start,
            field=field,
            code="missing_value",
            message=f"{field} is missing; the row is excluded from KPI rollups.",
        )
        return None

    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        _warning(
            warnings,
            row_number=row_number,
            week_start=week_start,
            field=field,
            code="not_numeric",
            message=f"{field} is not numeric; the row is excluded from KPI rollups.",
        )
        return None

    if not math.isfinite(parsed):
        _warning(
            warnings,
            row_number=row_number,
            week_start=week_start,
            field=field,
            code="not_finite",
            message=f"{field} is not finite; the row is excluded from KPI rollups.",
        )
        return None

    if parsed < 0:
        _warning(
            warnings,
            row_number=row_number,
            week_start=week_start,
            field=field,
            code="negative_value",
            message=f"{field} is negative; the row is excluded from KPI rollups.",
        )
        return None

    if field in COUNT_COLUMNS and not parsed.is_integer():
        _warning(
            warnings,
            row_number=row_number,
            week_start=week_start,
            field=field,
            code="non_integer_count",
            message=f"{field} must be a whole-number count; the row is excluded from KPI rollups.",
        )
        return None

    return int(parsed) if field in COUNT_COLUMNS else parsed


def load_campaign_data(path: str | Path) -> Dataset:
    """Read and validate a CSV without mutating or imputing its values."""

    csv_path = Path(path)
    rows: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    warnings: list[ValidationWarning] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing_columns:
            _warning(
                warnings,
                row_number=1,
                week_start=None,
                field="schema",
                code="missing_columns",
                message=f"Required columns are missing: {', '.join(missing_columns)}.",
            )
            return Dataset(rows=[], valid_rows=[], warnings=warnings)

        for row_number, raw_row in enumerate(reader, start=2):
            week_value = (raw_row.get("week_start") or "").strip()
            week_start: str | None = week_value or None
            row_is_valid = True

            if not week_value:
                row_is_valid = False
                _warning(
                    warnings,
                    row_number=row_number,
                    week_start=None,
                    field="week_start",
                    code="missing_value",
                    message="week_start is missing; the row is excluded from KPI rollups.",
                )
            else:
                try:
                    date.fromisoformat(week_value)
                except ValueError:
                    row_is_valid = False
                    _warning(
                        warnings,
                        row_number=row_number,
                        week_start=week_value,
                        field="week_start",
                        code="invalid_date",
                        message="week_start must be an ISO date (YYYY-MM-DD); the row is excluded from KPI rollups.",
                    )

            channel = (raw_row.get("channel") or "").strip()
            campaign = (raw_row.get("campaign") or "").strip()
            for field, value in (("channel", channel), ("campaign", campaign)):
                if not value:
                    row_is_valid = False
                    _warning(
                        warnings,
                        row_number=row_number,
                        week_start=week_start,
                        field=field,
                        code="missing_value",
                        message=f"{field} is missing; the row is excluded from KPI rollups.",
                    )

            normalized: dict[str, Any] = {
                "week_start": week_value,
                "channel": channel,
                "campaign": campaign,
                "row_number": row_number,
            }
            parsed_values: dict[str, float | int | None] = {}
            warning_count_before = len(warnings)
            for field in NUMERIC_COLUMNS:
                parsed_values[field] = _parse_number(
                    raw_row.get(field),
                    field=field,
                    row_number=row_number,
                    week_start=week_start,
                    warnings=warnings,
                )
                normalized[field] = parsed_values[field]

            if len(warnings) > warning_count_before:
                row_is_valid = False

            relationships = (
                ("clicks", "impressions", "clicks cannot exceed impressions"),
                ("leads", "clicks", "leads cannot exceed clicks"),
                ("qualified_leads", "leads", "qualified_leads cannot exceed leads"),
                ("conversions", "qualified_leads", "conversions cannot exceed qualified_leads"),
            )
            for child, parent, message in relationships:
                child_value = parsed_values[child]
                parent_value = parsed_values[parent]
                if child_value is not None and parent_value is not None and child_value > parent_value:
                    row_is_valid = False
                    _warning(
                        warnings,
                        row_number=row_number,
                        week_start=week_start,
                        field=child,
                        code="impossible_relationship",
                        message=f"{message}; the row is excluded from KPI rollups.",
                    )

            normalized["is_valid_for_metrics"] = row_is_valid
            rows.append(normalized)
            if row_is_valid:
                valid_rows.append(normalized)

    return Dataset(rows=rows, valid_rows=valid_rows, warnings=warnings)
