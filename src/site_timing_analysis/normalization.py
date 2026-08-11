# Project: Site Timing Analysis
# File: src/site_timing_analysis/normalization.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Normalizes raw audit-log records into canonical event rows.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from .errors import NormalizationError
from .models import RawAuditEvent, NormalizedAuditEvent


_TIMESTAMP_RE = re.compile(
    r"^(?P<prefix>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<suffix>Z|[+-]\d{2}:\d{2})?$"
)


def _coerce_timestamp(value: str, *, case_id: str, row_number: int) -> datetime:
    text = value.strip()
    match = _TIMESTAMP_RE.match(text)
    if not match:
        raise NormalizationError(case_id, row_number, f"Invalid timestamp format: '{value}'")

    prefix = match.group("prefix").replace("T", " ")
    fraction = match.group("fraction")
    suffix = match.group("suffix")

    if fraction is not None:
        microseconds = fraction[:6].ljust(6, "0")
        normalized = f"{prefix}.{microseconds}"
    else:
        normalized = prefix

    if suffix == "Z":
        normalized += "+00:00"
    elif suffix:
        normalized += suffix

    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise NormalizationError(case_id, row_number, f"Failed to parse timestamp '{value}'") from exc


def _coerce_event_type(value: str | None, *, case_id: str, row_number: int) -> str:
    if value is None:
        raise NormalizationError(case_id, row_number, "Missing AuditRecordBase_Type")
    normalized = value.strip()
    if normalized == "":
        raise NormalizationError(case_id, row_number, "Empty AuditRecordBase_Type")
    return normalized


def _coerce_segment_id(event: RawAuditEvent) -> str | None:
    if event.raw_segment_id is not None and str(event.raw_segment_id).strip() != "":
        return str(event.raw_segment_id).strip()
    treatment_id = event.raw_payload.get("TreatmentId")
    if treatment_id is None:
        return None
    normalized = str(treatment_id).strip()
    return normalized if normalized != "" else None


def normalize_audit_events(
    raw_events: Iterable[RawAuditEvent],
) -> tuple[list[NormalizedAuditEvent], list[NormalizedAuditEvent]]:
    kept: list[NormalizedAuditEvent] = []
    dropped: list[NormalizedAuditEvent] = []

    for event in raw_events:
        if event.raw_timestamp is None:
            raise NormalizationError(event.case_id, event.row_number, "Missing TimeStamp")

        timestamp = _coerce_timestamp(
            event.raw_timestamp,
            case_id=event.case_id,
            row_number=event.row_number,
        )
        event_type = _coerce_event_type(
            event.raw_event_type,
            case_id=event.case_id,
            row_number=event.row_number,
        )
        normalized = NormalizedAuditEvent(
            case_id=event.case_id,
            row_number=event.row_number,
            timestamp=timestamp,
            event_type=event_type,
            segment_id=_coerce_segment_id(event),
            event_kind=event.raw_event_kind,
            source="auditlog",
            raw_payload=event.raw_payload,
        )

        if event_type == "SignalRecord":
            normalized.is_dropped = True
            normalized.drop_reason = "filtered_signal_record"
            dropped.append(normalized)
            continue
        kept.append(normalized)

    return kept, dropped
