from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .errors import ManifestWriteError
from .models import (
    RunManifest,
    CaseDiscoveryRecord,
    NormalizedAuditEvent,
    EnrichedEvent,
    StateLabeledEvent,
    StateInterval,
)
from .output_layout import output_layout


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _ensure_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def write_run_manifest(run_manifest: RunManifest, output_dir: Path) -> Path:
    out_dir = _ensure_output_dir(output_dir)
    out_path = output_layout(out_dir).run_manifest_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = _serialize_value(asdict(run_manifest))
    try:
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        raise ManifestWriteError(f"Failed to write run manifest: {out_path}") from exc
    return out_path


def write_case_manifest(case_records: Iterable[CaseDiscoveryRecord], output_dir: Path) -> Path:
    out_dir = _ensure_output_dir(output_dir)
    out_path = output_layout(out_dir).case_manifest_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "site_code",
        "case_id",
        "case_path",
        "discovery_order",
        "candidate_unzipped_db_paths",
        "candidate_zip_paths",
        "warnings",
    ]

    try:
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in case_records:
                writer.writerow(
                    {
                        "site_code": record.site_code,
                        "case_id": record.case_id,
                        "case_path": str(record.case_path),
                        "discovery_order": record.discovery_order,
                        "candidate_unzipped_db_paths": "|".join(
                            str(path) for path in record.candidate_unzipped_db_paths
                        ),
                        "candidate_zip_paths": "|".join(str(path) for path in record.candidate_zip_paths),
                        "warnings": "|".join(record.warnings),
                    }
                )
    except OSError as exc:
        raise ManifestWriteError(f"Failed to write case manifest: {out_path}") from exc

    return out_path


def write_normalized_events_csv(
    *,
    case_id: str,
    normalized_events: Iterable[NormalizedAuditEvent],
    output_dir: Path,
) -> Path:
    out_dir = output_layout(_ensure_output_dir(output_dir)).normalized_events_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}_normalized_events.csv"

    fieldnames = [
        "case_id",
        "row_number",
        "timestamp",
        "event_type",
        "segment_id",
        "event_kind",
        "source",
        "is_dropped",
        "drop_reason",
        "raw_payload_json",
    ]

    try:
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for event in normalized_events:
                writer.writerow(
                    {
                        "case_id": event.case_id,
                        "row_number": event.row_number,
                        "timestamp": event.timestamp.isoformat(),
                        "event_type": event.event_type,
                        "segment_id": event.segment_id,
                        "event_kind": event.event_kind,
                        "source": event.source,
                        "is_dropped": event.is_dropped,
                        "drop_reason": event.drop_reason or "",
                        "raw_payload_json": json.dumps(_serialize_value(event.raw_payload), sort_keys=True),
                    }
                )
    except OSError as exc:
        raise ManifestWriteError(f"Failed to write normalized events CSV: {out_path}") from exc

    return out_path


def write_enriched_events_csv(
    *,
    case_id: str,
    enriched_events: Iterable[EnrichedEvent],
    output_dir: Path,
) -> Path:
    out_dir = output_layout(_ensure_output_dir(output_dir)).enriched_events_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}_enriched_events.csv"

    fieldnames = [
        "case_id",
        "timestamp",
        "event_type",
        "source",
        "is_synthetic",
        "source_detail",
        "segment_id",
        "event_kind",
        "drop_reason",
        "insertion_rule",
        "row_number",
        "raw_payload_json",
    ]

    try:
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for event in enriched_events:
                writer.writerow(
                    {
                        "case_id": event.case_id,
                        "timestamp": event.timestamp.isoformat(),
                        "event_type": event.event_type,
                        "source": event.source,
                        "is_synthetic": event.is_synthetic,
                        "source_detail": event.source_detail,
                        "segment_id": event.segment_id,
                        "event_kind": event.event_kind,
                        "drop_reason": event.drop_reason or "",
                        "insertion_rule": event.insertion_rule or "",
                        "row_number": event.row_number if event.row_number is not None else "",
                        "raw_payload_json": json.dumps(_serialize_value(event.raw_payload), sort_keys=True),
                    }
                )
    except OSError as exc:
        raise ManifestWriteError(f"Failed to write enriched events CSV: {out_path}") from exc

    return out_path


def write_state_labeled_events_csv(
    *,
    case_id: str,
    state_labeled_events: Iterable[StateLabeledEvent],
    output_dir: Path,
) -> Path:
    out_dir = output_layout(_ensure_output_dir(output_dir)).state_labeled_events_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}_state_labeled_events.csv"

    fieldnames = [
        "case_id",
        "timestamp",
        "event_type",
        "source",
        "is_synthetic",
        "segment_id",
        "event_kind",
        "state",
        "state_assignment_rule",
        "cleanup_rule_applied",
        "drop_reason",
        "row_number",
        "source_detail",
        "insertion_rule",
        "raw_payload_json",
    ]

    try:
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for event in state_labeled_events:
                writer.writerow(
                    {
                        "case_id": event.case_id,
                        "timestamp": event.timestamp.isoformat(),
                        "event_type": event.event_type,
                        "source": event.source,
                        "is_synthetic": event.is_synthetic,
                        "segment_id": event.segment_id,
                        "event_kind": event.event_kind,
                        "state": event.state or "",
                        "state_assignment_rule": event.state_assignment_rule or "",
                        "cleanup_rule_applied": event.cleanup_rule_applied or "",
                        "drop_reason": event.drop_reason or "",
                        "row_number": event.row_number if event.row_number is not None else "",
                        "source_detail": event.source_detail,
                        "insertion_rule": event.insertion_rule or "",
                        "raw_payload_json": json.dumps(_serialize_value(event.raw_payload), sort_keys=True),
                    }
                )
    except OSError as exc:
        raise ManifestWriteError(f"Failed to write state-labeled events CSV: {out_path}") from exc

    return out_path


def write_state_intervals_csv(
    *,
    case_id: str,
    state_intervals: Iterable[StateInterval],
    output_dir: Path,
) -> Path:
    out_dir = output_layout(_ensure_output_dir(output_dir)).state_intervals_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}_state_intervals.csv"

    fieldnames = [
        "case_id",
        "timestamp",
        "state",
        "start_sec",
        "duration_sec",
        "rebase_anchor",
        "origin_event_type",
        "source",
        "is_synthetic",
        "source_detail",
        "row_number",
        "state_assignment_rule",
        "cleanup_rule_applied",
        "quality_flags",
        "segment_id",
        "event_kind",
        "drop_reason",
        "insertion_rule",
        "raw_payload_json",
    ]

    try:
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in state_intervals:
                writer.writerow(
                    {
                        "case_id": row.case_id,
                        "timestamp": row.timestamp.isoformat(),
                        "state": row.state or "",
                        "start_sec": row.start_sec,
                        "duration_sec": row.duration_sec,
                        "rebase_anchor": row.rebase_anchor or "",
                        "origin_event_type": row.origin_event_type,
                        "source": row.source,
                        "is_synthetic": row.is_synthetic,
                        "source_detail": row.source_detail,
                        "row_number": row.row_number if row.row_number is not None else "",
                        "state_assignment_rule": row.state_assignment_rule or "",
                        "cleanup_rule_applied": row.cleanup_rule_applied or "",
                        "quality_flags": "|".join(row.quality_flags),
                        "segment_id": row.segment_id or "",
                        "event_kind": row.event_kind if row.event_kind is not None else "",
                        "drop_reason": row.drop_reason or "",
                        "insertion_rule": row.insertion_rule or "",
                        "raw_payload_json": json.dumps(_serialize_value(row.raw_payload), sort_keys=True),
                    }
                )
    except OSError as exc:
        raise ManifestWriteError(f"Failed to write state-intervals CSV: {out_path}") from exc

    return out_path
