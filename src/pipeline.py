"""Synthetic multi-source ingestion, validation, normalization, and reconciliation.

This module is deliberately deterministic. It models the boundary between three
source exports and the trusted reporting rows consumed by the analytics layer.
It is a local proof of concept only; it does not connect to an ad platform, CRM,
warehouse, scheduler, or production credential.
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .validation import Dataset, ValidationWarning

SOURCE_LABELS = {
    "google": "Google Ads",
    "meta": "Meta Ads",
    "crm": "CRM",
}
SOURCE_KEYS = ("google", "meta", "crm")

MEDIA_SPECS = {
    "google": {
        "required": ("date", "campaign_id", "campaign_name", "impressions", "clicks", "spend"),
        "optional": ("platform_leads",),
    },
    "meta": {
        "required": ("report_date", "campaign_key", "campaign", "impressions", "link_clicks", "amount_spent"),
        "optional": ("leads",),
    },
}
CRM_REQUIRED = ("lead_id", "lead_created_at", "source_platform", "tracked_campaign", "qualified", "converted")

CAMPAIGNS = {
    "g-brand": ("Google", "G-BRAND", "Google Brand Search"),
    "google-brand-search": ("Google", "G-BRAND", "Google Brand Search"),
    "g-nonbrand": ("Google", "G-NONBRAND", "Google Non-Brand Search"),
    "google-non-brand-search": ("Google", "G-NONBRAND", "Google Non-Brand Search"),
    "m-prospecting": ("Meta", "M-PROSPECT", "Meta Prospecting"),
    "m-prospect": ("Meta", "M-PROSPECT", "Meta Prospecting"),
    "meta-prospecting": ("Meta", "M-PROSPECT", "Meta Prospecting"),
    "m-retargeting": ("Meta", "M-RETARGET", "Meta Retargeting"),
    "m-retarget": ("Meta", "M-RETARGET", "Meta Retargeting"),
    "meta-retargeting": ("Meta", "M-RETARGET", "Meta Retargeting"),
}


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _source_warning(
    warnings: list[ValidationWarning],
    *,
    source: str,
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
            source=source,
        )
    )


def _source_text(source: Any) -> tuple[str, str]:
    """Read a path, bytes value, or browser-upload object without writing it."""

    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_text(encoding="utf-8-sig"), path.name
    if isinstance(source, bytes):
        return source.decode("utf-8-sig"), "uploaded.csv"
    if hasattr(source, "getvalue"):
        value = source.getvalue()
        if isinstance(value, str):
            return value, getattr(source, "name", "uploaded.csv")
        return value.decode("utf-8-sig"), getattr(source, "name", "uploaded.csv")
    if hasattr(source, "read"):
        value = source.read()
        if isinstance(value, str):
            return value, getattr(source, "name", "uploaded.csv")
        return value.decode("utf-8-sig"), getattr(source, "name", "uploaded.csv")
    raise TypeError("Source must be a path, bytes, or file-like upload.")


def _read_csv_sections(source: Any) -> list[tuple[list[dict[str, str]], str, tuple[str, ...]]]:
    """Read one CSV or a concatenated set of weekly CSV sections.

    A repeated source header starts a new section.  This keeps weekly source
    schemas inspectable when an upstream export bundle contains one file per
    reporting week, including a section whose required field is absent.
    """

    text, filename = _source_text(source)
    lines = text.splitlines(keepends=True)
    sections: list[tuple[list[dict[str, str]], str, tuple[str, ...]]] = []
    header_line: str | None = None
    header_values: list[str] = []
    data_lines: list[str] = []

    def flush() -> None:
        if header_line is None:
            return
        reader = csv.DictReader(io.StringIO(header_line + "".join(data_lines)))
        sections.append((list(reader), filename, tuple(reader.fieldnames or ())))

    for line in lines:
        values = next(csv.reader([line]), []) if line.strip() else []
        is_repeated_header = bool(
            values
            and header_values
            and values[0] in {"lead_id", "date", "report_date", "week_start"}
            and values[0] == header_values[0]
        )
        if header_line is None and values:
            header_line = line
            header_values = values
        elif is_repeated_header:
            flush()
            header_line = line
            header_values = values
            data_lines = []
        elif header_line is not None:
            data_lines.append(line)
    flush()
    return sections


def _parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = (text[:10], text)
    formats = ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d")
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _number(
    value: Any,
    *,
    source: str,
    field_name: str,
    row_number: int,
    week_start: str | None,
    warnings: list[ValidationWarning],
    required: bool = True,
    integer: bool = True,
) -> int | float | None:
    text = str(value or "").strip()
    if not text:
        if required:
            _source_warning(
                warnings,
                source=source,
                row_number=row_number,
                week_start=week_start,
                field=field_name,
                code="missing_value",
                message=f"{field_name} is missing; the row is excluded from trusted reporting rows.",
            )
        else:
            _source_warning(
                warnings,
                source=source,
                row_number=row_number,
                week_start=week_start,
                field=field_name,
                code="missing_optional_metric",
                message=f"Optional {field_name} is missing; reporting uses CRM outcomes and retains the row.",
            )
        return None
    try:
        parsed = float(text.replace(",", ""))
    except ValueError:
        _source_warning(
            warnings,
            source=source,
            row_number=row_number,
            week_start=week_start,
            field=field_name,
            code="not_numeric",
            message=f"{field_name} is not numeric; the row is excluded from trusted reporting rows.",
        )
        return None
    if not math.isfinite(parsed):
        _source_warning(
            warnings,
            source=source,
            row_number=row_number,
            week_start=week_start,
            field=field_name,
            code="not_finite",
            message=f"{field_name} is not finite; the row is excluded from trusted reporting rows.",
        )
        return None
    if parsed < 0:
        _source_warning(
            warnings,
            source=source,
            row_number=row_number,
            week_start=week_start,
            field=field_name,
            code="negative_value",
            message=f"{field_name} is negative; the row is excluded from trusted reporting rows.",
        )
        return None
    if integer and not parsed.is_integer():
        _source_warning(
            warnings,
            source=source,
            row_number=row_number,
            week_start=week_start,
            field=field_name,
            code="non_integer_count",
            message=f"{field_name} must be a whole-number count; the row is excluded from trusted reporting rows.",
        )
        return None
    return int(parsed) if integer else round(parsed, 2)


def _canonical_campaign(
    value: Any,
    campaigns: Mapping[str, tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    return campaigns.get(_key(value))


def _normalize_media(
    source: str,
    raw_rows: list[dict[str, str]],
    warnings: list[ValidationWarning],
    campaigns: Mapping[str, tuple[str, str, str]],
) -> list[dict[str, Any]]:
    spec = MEDIA_SPECS[source]
    normalized: list[dict[str, Any]] = []
    field_map = {
        "google": {"date": "date", "campaign_id": "campaign_id", "campaign_name": "campaign_name", "impressions": "impressions", "clicks": "clicks", "spend": "spend", "platform_leads": "platform_leads"},
        "meta": {"date": "report_date", "campaign_id": "campaign_key", "campaign_name": "campaign", "impressions": "impressions", "clicks": "link_clicks", "spend": "amount_spent", "platform_leads": "leads"},
    }[source]
    for row_number, raw in enumerate(raw_rows, start=2):
        missing = [column for column in (*spec["required"],) if column not in raw]
        if missing:
            _source_warning(
                warnings,
                source=source,
                row_number=1,
                week_start=None,
                field="schema",
                code="missing_columns",
                message=f"Required columns are missing: {', '.join(missing)}.",
            )
            return []
        week_start = _parse_date(raw.get(field_map["date"]))
        row_is_valid = True
        if not week_start:
            row_is_valid = False
            _source_warning(
                warnings,
                source=source,
                row_number=row_number,
                week_start=None,
                field=field_map["date"],
                code="invalid_date",
                message="The source date is not a recognized date format; the row is excluded.",
            )
        campaign_match = _canonical_campaign(raw.get(field_map["campaign_id"]), campaigns)
        if not campaign_match:
            row_is_valid = False
            _source_warning(
                warnings,
                source=source,
                row_number=row_number,
                week_start=week_start,
                field=field_map["campaign_id"],
                code="unknown_campaign",
                message="The campaign identifier is not mapped to this project's configured campaign catalog.",
            )
            campaign_match = ("Unknown", str(raw.get(field_map["campaign_name"]) or "Unknown"), str(raw.get(field_map["campaign_name"]) or "Unknown"))
        values: dict[str, Any] = {}
        for canonical_field in ("impressions", "clicks", "spend"):
            parsed = _number(
                raw.get(field_map[canonical_field]),
                source=source,
                field_name=field_map[canonical_field],
                row_number=row_number,
                week_start=week_start,
                warnings=warnings,
                integer=canonical_field != "spend",
            )
            values[canonical_field] = parsed
            if parsed is None:
                row_is_valid = False
        optional_value = _number(
            raw.get(field_map["platform_leads"]),
            source=source,
            field_name=field_map["platform_leads"],
            row_number=row_number,
            week_start=week_start,
            warnings=warnings,
            required=False,
            integer=True,
        )
        if any(values[field] is None for field in ("impressions", "clicks", "spend")):
            row_is_valid = False
        if values["clicks"] is not None and values["impressions"] is not None and values["clicks"] > values["impressions"]:
            row_is_valid = False
            _source_warning(warnings, source=source, row_number=row_number, week_start=week_start, field="clicks", code="impossible_relationship", message="Clicks cannot exceed impressions; the row is excluded.")
        normalized.append(
            {
                "date": week_start,
                "week_start": week_start,
                "channel": campaign_match[0],
                "campaign_id": campaign_match[1],
                "campaign": campaign_match[2],
                "campaign_name": campaign_match[2],
                "spend": values["spend"],
                "impressions": values["impressions"],
                "clicks": values["clicks"],
                "platform_leads": optional_value,
                "leads": optional_value,
                "source": source,
                "source_row_number": row_number,
                "is_valid_for_metrics": row_is_valid,
            }
        )
    return normalized


def _as_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "qualified", "converted"}:
        return True
    if text in {"0", "false", "no", "n", "not qualified", "not converted"}:
        return False
    return None


def _normalize_crm(
    raw_rows: list[dict[str, str]],
    warnings: list[ValidationWarning],
    campaigns: Mapping[str, tuple[str, str, str]],
    *,
    fieldnames: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    normalized: list[dict[str, Any]] = []
    trusted: list[dict[str, Any]] = []
    seen_leads: set[str] = set()
    duplicate_count = 0
    unmatched_count = 0
    available_columns = set(fieldnames or (raw_rows[0].keys() if raw_rows else ()))
    missing_columns = [column for column in CRM_REQUIRED if column not in available_columns]
    if missing_columns:
        schema_week = _parse_date(raw_rows[0].get("lead_created_at")) if raw_rows else None
        missing_label = ", ".join(missing_columns)
        message = (
            f"Required CRM field missing: {missing_label}."
            if len(missing_columns) == 1
            else f"Required CRM fields missing: {missing_label}."
        )
        _source_warning(
            warnings,
            source="crm",
            row_number=1,
            week_start=schema_week,
            field="schema",
            code="missing_columns",
            message=message,
        )
        return [], [], 0, 0
    for row_number, raw in enumerate(raw_rows, start=2):
        lead_id = str(raw.get("lead_id") or "").strip()
        week_start = _parse_date(raw.get("lead_created_at"))
        campaign_match = _canonical_campaign(raw.get("tracked_campaign"), campaigns)
        qualified = _as_bool(raw.get("qualified"))
        converted = _as_bool(raw.get("converted"))
        row_is_valid = True
        missing_fields = [
            field
            for field, value in (
                ("lead_id", lead_id),
                ("lead_created_at", raw.get("lead_created_at")),
                ("source_platform", raw.get("source_platform")),
                ("tracked_campaign", raw.get("tracked_campaign")),
                ("qualified", raw.get("qualified")),
                ("converted", raw.get("converted")),
            )
            if not str(value or "").strip()
        ]
        for missing_field in missing_fields:
            row_is_valid = False
            _source_warning(
                warnings,
                source="crm",
                row_number=row_number,
                week_start=week_start,
                field=missing_field,
                code="missing_value",
                message=f"{missing_field} is missing; the CRM row is excluded from trusted reporting rows.",
            )
        if not missing_fields and (not week_start or qualified is None or converted is None):
            row_is_valid = False
            _source_warning(warnings, source="crm", row_number=row_number, week_start=week_start, field="lead", code="invalid_lead_record", message="CRM lead requires an identifier, parseable date, and boolean qualified/converted values.")
        if converted and not qualified:
            row_is_valid = False
            _source_warning(warnings, source="crm", row_number=row_number, week_start=week_start, field="converted", code="impossible_relationship", message="A converted lead must also be qualified; the row is excluded.")
        is_duplicate = bool(lead_id and lead_id in seen_leads)
        if is_duplicate:
            duplicate_count += 1
            row_is_valid = False
            _source_warning(warnings, source="crm", row_number=row_number, week_start=week_start, field="lead_id", code="duplicate_lead", message="Duplicate CRM lead_id detected; the later row is excluded.")
        if lead_id:
            seen_leads.add(lead_id)
        if not campaign_match:
            unmatched_count += 1
            row_is_valid = False
            _source_warning(warnings, source="crm", row_number=row_number, week_start=week_start, field="tracked_campaign", code="unmatched_campaign", message="CRM lead cannot be reconciled to a known synthetic campaign.")
        normalized_row = {
            "lead_id": lead_id,
            "week_start": week_start,
            "source_platform": str(raw.get("source_platform") or "").strip().title(),
            "tracked_campaign": str(raw.get("tracked_campaign") or "").strip(),
            "campaign_id": campaign_match[1] if campaign_match else None,
            "campaign": campaign_match[2] if campaign_match else None,
            "channel": campaign_match[0] if campaign_match else None,
            "qualified": bool(qualified),
            "converted": bool(converted),
            "source": "crm",
            "source_row_number": row_number,
            "is_valid_for_metrics": row_is_valid,
        }
        normalized.append(normalized_row)
        if row_is_valid:
            trusted.append(normalized_row)
    return normalized, trusted, duplicate_count, unmatched_count


def _source_summary(
    source: str,
    filename: str,
    rows: list[dict[str, Any]],
    warnings: list[ValidationWarning],
    *,
    configured: bool = True,
) -> dict[str, Any]:
    if not configured:
        return {
            "source": SOURCE_LABELS[source],
            "source_key": source,
            "filename": "Not configured",
            "rows_loaded": 0,
            "trusted_rows": 0,
            "warning_count": 0,
            "status": "Not configured",
            "configured": False,
        }
    source_warnings = [warning for warning in warnings if warning.source == source]
    status = "Needs attention" if not rows or any(w.code == "missing_columns" for w in source_warnings) else "Processed"
    if status == "Processed" and source_warnings:
        status = "Processed with warnings"
    return {
        "source": SOURCE_LABELS[source],
        "source_key": source,
        "filename": filename,
        "rows_loaded": len(rows),
        "trusted_rows": sum(1 for row in rows if row.get("is_valid_for_metrics")),
        "warning_count": len(source_warnings),
        "status": status,
        "configured": True,
    }


def process_source_files(
    sources: Mapping[str, Any],
    campaign_catalog: Mapping[str, tuple[str, str, str]] | None = None,
    expected_sources: Iterable[str] | None = None,
    client_name: str = "Synthetic HealthCo",
) -> Dataset:
    """Process the configured source set through one shared path."""

    campaigns = dict(campaign_catalog or CAMPAIGNS)
    expected = tuple(source for source in (expected_sources or SOURCE_KEYS) if source in SOURCE_KEYS)
    if not expected:
        expected = SOURCE_KEYS

    missing_sources = [source for source in expected if source not in sources or sources[source] is None]
    warnings: list[ValidationWarning] = []
    if missing_sources:
        for source in missing_sources:
            _source_warning(warnings, source=source, row_number=1, week_start=None, field="file", code="missing_source_file", message=f"{SOURCE_LABELS[source]} source file is required.")

    raw_exports: dict[str, list[dict[str, Any]]] = {}
    filenames: dict[str, str] = {}
    source_sections: dict[str, list[tuple[list[dict[str, str]], str, tuple[str, ...]]]] = {}
    for source in SOURCE_KEYS:
        if source not in sources or sources[source] is None:
            raw_exports[source] = []
            filenames[source] = f"{source}.csv"
            source_sections[source] = []
            continue
        try:
            sections = _read_csv_sections(sources[source])
        except (OSError, UnicodeDecodeError, TypeError) as exc:
            sections = []
            filename = getattr(sources[source], "name", f"{source}.csv")
            _source_warning(warnings, source=source, row_number=1, week_start=None, field="file", code="read_error", message=f"Could not read source file: {type(exc).__name__}.")
        source_sections[source] = sections
        raw_exports[source] = [row for rows, _, _ in sections for row in rows]
        filenames[source] = sections[0][1] if sections else getattr(sources[source], "name", f"{source}.csv")

    normalized_media: list[dict[str, Any]] = []
    for source in ("google", "meta"):
        normalized_media.extend(_normalize_media(source, raw_exports[source], warnings, campaigns))
    normalized_crm: list[dict[str, Any]] = []
    trusted_crm: list[dict[str, Any]] = []
    duplicate_count = 0
    unmatched_count = 0
    for rows, _, fieldnames in source_sections.get("crm", []):
        section_normalized, section_trusted, section_duplicates, section_unmatched = _normalize_crm(
            rows,
            warnings,
            campaigns,
            fieldnames=fieldnames,
        )
        normalized_crm.extend(section_normalized)
        trusted_crm.extend(section_trusted)
        duplicate_count += section_duplicates
        unmatched_count += section_unmatched

    crm_by_campaign: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in trusted_crm:
        crm_by_campaign.setdefault((row["week_start"], row["campaign_id"]), []).append(row)

    reporting_rows: list[dict[str, Any]] = []
    for media_row in normalized_media:
        crm_rows = crm_by_campaign.get((media_row["week_start"], media_row["campaign_id"]), [])
        reporting_rows.append(
            {
                **media_row,
                "leads": media_row.get("platform_leads"),
                "crm_leads": len(crm_rows),
                "qualified_leads": sum(1 for row in crm_rows if row["qualified"]),
                "conversions": sum(1 for row in crm_rows if row["converted"]),
                "attribution_status": "attributed" if crm_rows else "no CRM match",
            }
        )
    trusted_reporting = [row for row in reporting_rows if row.get("is_valid_for_metrics")]
    source_summaries = [
        _source_summary(
            source,
            filenames[source],
            normalized_media if source in {"google", "meta"} else normalized_crm,
            warnings,
            configured=source in expected,
        )
        for source in SOURCE_KEYS
    ]
    source_summaries[0]["trusted_rows"] = sum(1 for row in normalized_media if row.get("source") == "google" and row.get("is_valid_for_metrics"))
    source_summaries[1]["trusted_rows"] = sum(1 for row in normalized_media if row.get("source") == "meta" and row.get("is_valid_for_metrics"))
    source_summaries[2]["trusted_rows"] = len(trusted_crm)
    source_summaries[0]["rows_loaded"] = len(raw_exports["google"])
    source_summaries[1]["rows_loaded"] = len(raw_exports["meta"])
    source_summaries[2]["rows_loaded"] = len(raw_exports["crm"])
    unique_crm = len({str(row.get("lead_id") or "").strip() for row in raw_exports["crm"] if str(row.get("lead_id") or "").strip()})
    reconciliation = {
        "crm_leads_loaded": len(raw_exports["crm"]),
        "successfully_attributed": len(trusted_crm),
        "unmatched": unmatched_count,
        "duplicate_records_detected": duplicate_count,
        "trusted_rows_used_for_reporting": len(trusted_reporting),
        "unique_crm_leads": unique_crm,
        "assumption": "A CRM row is attributed to a campaign when its tracked_campaign alias maps to the canonical synthetic campaign_id in the same reporting week. This is a proof-of-concept assumption, not full marketing attribution.",
    }
    source_week_starts = {
        source: sorted({str(row.get("week_start")) for row in rows if row.get("week_start")})
        for source, rows in (("google", normalized_media), ("meta", normalized_media), ("crm", normalized_crm))
    }
    source_week_starts["google"] = sorted({str(row.get("week_start")) for row in normalized_media if row.get("source") == "google" and row.get("week_start")})
    source_week_starts["meta"] = sorted({str(row.get("week_start")) for row in normalized_media if row.get("source") == "meta" and row.get("week_start")})
    source_week_starts["crm"] = sorted(
        {
            parsed_week
            for row in raw_exports["crm"]
            if (parsed_week := _parse_date(row.get("lead_created_at")))
        }
    )
    return Dataset(
        rows=reporting_rows,
        valid_rows=trusted_reporting,
        warnings=warnings,
        source_summaries=source_summaries,
        reconciliation=reconciliation,
        raw_exports=raw_exports,
        normalized_media_rows=normalized_media,
        normalized_crm_rows=normalized_crm,
        campaign_catalog=campaigns,
        source_week_starts=source_week_starts,
        client_name=client_name,
    )


def load_bundled_dataset(
    project_root: str | Path,
    campaign_catalog: Mapping[str, tuple[str, str, str]] | None = None,
) -> Dataset:
    root = Path(project_root)
    source_root = root / "data" / "source_exports"
    return process_source_files(
        {
            "google": source_root / "google_ads.csv",
            "meta": source_root / "meta_ads.csv",
            "crm": source_root / "crm.csv",
        },
        campaign_catalog=campaign_catalog,
    )


def load_uploaded_dataset(
    google: Any,
    meta: Any | None = None,
    crm: Any | None = None,
    campaign_catalog: Mapping[str, tuple[str, str, str]] | None = None,
    expected_sources: Iterable[str] | None = None,
    client_name: str = "Synthetic HealthCo",
) -> Dataset:
    return process_source_files(
        {"google": google, "meta": meta, "crm": crm},
        campaign_catalog=campaign_catalog,
        expected_sources=expected_sources,
        client_name=client_name,
    )
