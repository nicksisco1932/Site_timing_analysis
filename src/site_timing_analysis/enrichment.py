from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable

from .models import EnrichedEvent, NormalizedAuditEvent, SyntheticEvent, TimingLogEntry


_SESSION_FIELD_TO_EVENT: dict[str, str] = {
    "TimePatientSedatedAt": "Ready4Urology",
    "TimeUaInsertedAt": "DeviceInsertionEnds",
    "TimePatientTransferredAt": "PatientTransferEnds",
}
_KNOWN_UNMAPPED_SESSION_FIELDS: tuple[str, ...] = ("TimeUaRemovedAt",)
_SESSION_PRE_END_FIELDS: tuple[str, ...] = (
    "TimePatientSedatedAt",
    "TimeUaInsertedAt",
)
_SESSION_END_MARKER_FIELDS: tuple[str, ...] = (
    "TimeUaRemovedAt",
    "TimePatientTransferredAt",
)

_TIMING_LABEL_TO_EVENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "Anesthesia Team starts to prepapre the patient ": (("AnesthesiaStart", "start"),),
    "Anesthesia Team starts to prepare the patient ": (("AnesthesiaStart", "start"),),
    "Patient is ready for Urology team": (("Ready4Urology", "end"),),
    "Devices Insertion": (("DeviceInsertionBegins", "start"), ("DeviceInsertionEnds", "end")),
    "Patient Transfer from MRI Bed to Recovery room": (
        ("PatientTransferBegins", "start"),
        ("PatientTransferEnds", "end"),
    ),
    "Initial Device Imaging (From first until last survey)": (("InitialImaging", "start"),),
}


def _looks_like_session_sentinel(text: str) -> bool:
    normalized = text.strip().lower().replace("t", " ")
    if normalized.startswith("0001-01-01"):
        return True
    if normalized in {"1/1/0001 12:00:00 am", "01/01/0001 12:00:00 am"}:
        return True
    return False


def _parse_optional_datetime(raw_value: Any) -> tuple[datetime | None, str]:
    if raw_value is None:
        return None, "missing"
    text = str(raw_value).strip()
    if text == "":
        return None, "missing"
    if _looks_like_session_sentinel(text):
        return None, "sentinel"

    normalized = text.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    if "." in normalized:
        left, right = normalized.split(".", 1)
        frac = right
        tz_suffix = ""
        if "+" in right:
            frac, tz_suffix = right.split("+", 1)
            tz_suffix = "+" + tz_suffix
        elif "-" in right[1:]:
            split_at = right[1:].find("-") + 1
            frac, tz_suffix = right[:split_at], right[split_at:]
        frac = frac[:6].ljust(6, "0")
        normalized = f"{left}.{frac}{tz_suffix}"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, "unparseable"
    if parsed.year <= 1:
        return None, "sentinel"
    return parsed, "ok"


def _session_end_marker_violation(
    field_name: str,
    parsed_fields: dict[str, datetime | None],
) -> str | None:
    """
    Reject session-derived pre-device markers that occur after explicit end markers.

    Input:
        A session field name plus parseable timestamps from one ``Sessions`` row.
    Output:
        The first violated end-marker field name, or ``None`` when the field is
        chronologically plausible.
    Assumptions:
        ``TimePatientSedatedAt`` and ``TimeUaInsertedAt`` are pre/end-of-device
        workflow markers and should never occur after ``TimeUaRemovedAt`` or
        ``TimePatientTransferredAt`` from the same session row.
    """
    if field_name not in _SESSION_PRE_END_FIELDS:
        return None

    field_ts = parsed_fields.get(field_name)
    if field_ts is None:
        return None

    for end_field in _SESSION_END_MARKER_FIELDS:
        end_ts = parsed_fields.get(end_field)
        if end_ts is not None and field_ts > end_ts:
            return end_field

    return None


def derive_session_synthetic_events(
    case_id: str,
    sessions_rows: Iterable[dict[str, Any]],
) -> tuple[list[SyntheticEvent], list[str]]:
    events: list[SyntheticEvent] = []
    warnings: list[str] = []
    rows = list(sessions_rows)

    if not rows:
        return events, warnings

    tracked_fields = [*list(_SESSION_FIELD_TO_EVENT.keys()), *_KNOWN_UNMAPPED_SESSION_FIELDS]
    stats: dict[str, dict[str, int]] = {
        field: {
            "missing": 0,
            "unparseable": 0,
            "sentinel": 0,
            "parseable": 0,
            "missing_column": 0,
            "chronology_invalid": 0,
        }
        for field in tracked_fields
    }

    for row_idx, session_row in enumerate(rows, start=1):
        parsed_fields: dict[str, datetime | None] = {}
        parse_statuses: dict[str, str] = {}
        for field_name in tracked_fields:
            if field_name not in session_row:
                stats[field_name]["missing_column"] += 1
                parse_statuses[field_name] = "missing_column"
                parsed_fields[field_name] = None
                continue

            parsed_ts, status = _parse_optional_datetime(session_row.get(field_name))
            parse_statuses[field_name] = status
            parsed_fields[field_name] = parsed_ts
            if status == "missing":
                stats[field_name]["missing"] += 1
                continue
            if status == "unparseable":
                stats[field_name]["unparseable"] += 1
                warnings.append(
                    f"{case_id}:session_unparseable:{field_name}:row={row_idx}:value={session_row.get(field_name)}"
                )
                continue
            if status == "sentinel":
                stats[field_name]["sentinel"] += 1
                warnings.append(
                    f"{case_id}:ignored_session_sentinel_timestamp:{field_name}:{session_row.get(field_name)}"
                )
                continue

            stats[field_name]["parseable"] += 1
        for field_name in tracked_fields:
            if parse_statuses.get(field_name) != "ok":
                continue

            violated_end_field = _session_end_marker_violation(field_name, parsed_fields)
            if violated_end_field is not None:
                stats[field_name]["parseable"] -= 1
                stats[field_name]["chronology_invalid"] += 1
                warnings.append(
                    f"{case_id}:session_field_after_end_marker:{field_name}:row={row_idx}:"
                    f"end_field={violated_end_field}:value={session_row.get(field_name)}:"
                    f"end_value={session_row.get(violated_end_field)}"
                )
                continue

            if field_name in _SESSION_FIELD_TO_EVENT:
                events.append(
                    SyntheticEvent(
                        case_id=case_id,
                        timestamp=parsed_fields[field_name],
                        event_type=_SESSION_FIELD_TO_EVENT[field_name],
                        segment_id=None,
                        event_kind=None,
                        source="sessions",
                        source_detail=f"Sessions.{field_name}",
                        insertion_rule="session_field_map_v1",
                        raw_payload={
                            "session_row_index": row_idx,
                            "source_field": field_name,
                            "source_value": session_row.get(field_name),
                        },
                    )
                )
            else:
                warnings.append(f"{case_id}:session_field_unmapped:{field_name}:row={row_idx}")

    for field_name in tracked_fields:
        field_stats = stats[field_name]
        if field_stats["missing_column"] == len(rows):
            warnings.append(f"{case_id}:session_missing_column:{field_name}")
        elif field_stats["parseable"] == 0 and (
            field_stats["missing"] > 0
            or field_stats["unparseable"] > 0
            or field_stats["sentinel"] > 0
            or field_stats["chronology_invalid"] > 0
        ):
            warnings.append(
                f"{case_id}:session_field_not_usable:{field_name}:"
                f"missing={field_stats['missing']}:unparseable={field_stats['unparseable']}:"
                f"sentinel={field_stats['sentinel']}:chronology_invalid={field_stats['chronology_invalid']}"
            )

    return events, warnings


def derive_timing_log_synthetic_events(
    entries: Iterable[TimingLogEntry],
) -> tuple[list[SyntheticEvent], list[str]]:
    events: list[SyntheticEvent] = []
    warnings: list[str] = []

    for entry in entries:
        label = entry.label_text
        mapped = _TIMING_LABEL_TO_EVENTS.get(label)
        if mapped is None:
            warnings.append(
                f"{entry.case_id}:timing_log_unmapped_label:{entry.source_file.name}:"
                f"row={entry.row_number}:label={label}"
            )
            continue

        for event_type, time_selector in mapped:
            if time_selector == "start":
                timestamp = entry.time_start
                source_time = entry.time_start_raw
            else:
                timestamp = entry.time_end
                source_time = entry.time_end_raw

            if timestamp is None:
                warnings.append(
                    f"{entry.case_id}:timing_log_missing_mapped_time:{entry.source_file.name}:"
                    f"row={entry.row_number}:label={label}:event={event_type}:selector={time_selector}"
                )
                continue

            events.append(
                SyntheticEvent(
                    case_id=entry.case_id,
                    timestamp=timestamp,
                    event_type=event_type,
                    segment_id=None,
                    event_kind=None,
                    source="timing_log",
                    source_detail=label,
                    insertion_rule="timing_log_label_map_v1",
                    raw_payload={
                        "source_file": str(entry.source_file),
                        "source_row_number": entry.row_number,
                        "label_text": label,
                        "time_selector": time_selector,
                        "source_time_raw": source_time,
                    },
                )
            )

    return events, warnings


def merge_enriched_events(
    normalized_events: Iterable[NormalizedAuditEvent],
    synthetic_events: Iterable[SyntheticEvent],
) -> list[EnrichedEvent]:
    merged: list[EnrichedEvent] = []

    for event in normalized_events:
        merged.append(
            EnrichedEvent(
                case_id=event.case_id,
                timestamp=event.timestamp,
                event_type=event.event_type,
                source=event.source,
                is_synthetic=False,
                source_detail="normalized_audit_event",
                segment_id=event.segment_id,
                event_kind=event.event_kind,
                drop_reason=event.drop_reason,
                insertion_rule=None,
                row_number=event.row_number,
                raw_payload=deepcopy(event.raw_payload),
            )
        )

    for synth in synthetic_events:
        merged.append(
            EnrichedEvent(
                case_id=synth.case_id,
                timestamp=synth.timestamp,
                event_type=synth.event_type,
                source=synth.source,
                is_synthetic=True,
                source_detail=synth.source_detail,
                segment_id=synth.segment_id,
                event_kind=synth.event_kind,
                drop_reason=None,
                insertion_rule=synth.insertion_rule,
                row_number=None,
                raw_payload=deepcopy(synth.raw_payload),
            )
        )

    source_priority = {"sessions": 0, "timing_log": 1}

    def _sort_key(item: EnrichedEvent) -> tuple[Any, ...]:
        raw_first = 0 if not item.is_synthetic else 1
        raw_row = item.row_number if item.row_number is not None else 10**12
        synth_source_rank = source_priority.get(item.source, 99)
        return (
            item.timestamp,
            raw_first,
            raw_row,
            synth_source_rank,
            item.event_type,
            item.source_detail,
        )

    return sorted(merged, key=_sort_key)
