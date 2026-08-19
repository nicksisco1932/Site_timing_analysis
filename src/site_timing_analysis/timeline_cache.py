# Project: Site Timing Analysis
# File: src/site_timing_analysis/timeline_cache.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Provides exact read-only analytical-store cache lookup and materialization.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Exact, opt-in cache reads for Timeline Analysis case artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .analytical_store import (
    CACHE_CONTRACT_VERSION,
    AnalyticalStoreError,
    ParserVersion,
    _analysis_artifact_fingerprint,
    _open_database,
    _present_analysis_input,
    _absent_analysis_input,
    _verify_schema,
    analysis_input_fingerprint,
    case_configuration_fingerprint,
    current_parser_version,
    validate_database_path,
)
from .models import (
    DatabaseSourceRecord,
    EnrichedEvent,
    NormalizedAuditEvent,
    StateInterval,
    StateLabeledEvent,
)
from .timing_log import timing_log_source_type


@dataclass(slots=True)
class CachedCaseArtifacts:
    case_analysis_id: int
    normalized_events: list[NormalizedAuditEvent]
    enriched_events: list[EnrichedEvent]
    state_labeled_events: list[StateLabeledEvent]
    state_intervals: list[StateInterval]
    metadata: dict[str, Any]
    input_fingerprint_sha256: str
    case_configuration_fingerprint_sha256: str


@dataclass(slots=True)
class CacheLookupResult:
    status: str
    case_id: str
    duration_seconds: float
    reason: str
    input_fingerprint_sha256: str
    source_sha256: str
    timing_log_sha256: str | None
    artifacts: CachedCaseArtifacts | None = None


def _optional_int(value: Any) -> int | None:
    return None if value is None or str(value) == "" else int(value)


def _event_csv_row(row: sqlite3.Row, case_id: str) -> dict[str, str]:
    return {
        "case_id": case_id,
        "timestamp": str(row["timestamp_iso"]),
        "event_type": str(row["event_type"]),
        "source": str(row["source"]),
        "is_synthetic": "True" if row["is_synthetic"] else "False",
        "segment_id": "" if row["segment_id"] is None else str(row["segment_id"]),
        "event_kind": "" if row["event_kind"] is None else str(row["event_kind"]),
        "state": "" if row["state"] is None else str(row["state"]),
        "state_assignment_rule": ""
        if row["state_assignment_rule"] is None
        else str(row["state_assignment_rule"]),
        "cleanup_rule_applied": ""
        if row["cleanup_rule_applied"] is None
        else str(row["cleanup_rule_applied"]),
        "drop_reason": "" if row["drop_reason"] is None else str(row["drop_reason"]),
        "row_number": ""
        if row["source_row_number"] is None
        else str(row["source_row_number"]),
        "source_detail": str(row["source_detail"]),
        "insertion_rule": ""
        if row["insertion_rule"] is None
        else str(row["insertion_rule"]),
        "raw_payload_json": str(row["raw_payload_json"]),
    }


def _interval_csv_row(row: sqlite3.Row, case_id: str) -> dict[str, str]:
    flags = json.loads(str(row["quality_flags_json"]))
    if not isinstance(flags, list):
        raise AnalyticalStoreError(f"Cached interval quality flags are invalid for {case_id}.")
    return {
        "case_id": case_id,
        "timestamp": str(row["timestamp_iso"]),
        "state": "" if row["state"] is None else str(row["state"]),
        "start_sec": str(row["start_sec"]),
        "duration_sec": str(row["duration_sec"]),
        "rebase_anchor": ""
        if row["rebase_anchor"] is None
        else str(row["rebase_anchor"]),
        "origin_event_type": str(row["origin_event_type"]),
        "source": str(row["source"]),
        "is_synthetic": "True" if row["is_synthetic"] else "False",
        "source_detail": str(row["source_detail"]),
        "row_number": ""
        if row["source_row_number"] is None
        else str(row["source_row_number"]),
        "state_assignment_rule": ""
        if row["state_assignment_rule"] is None
        else str(row["state_assignment_rule"]),
        "cleanup_rule_applied": ""
        if row["cleanup_rule_applied"] is None
        else str(row["cleanup_rule_applied"]),
        "quality_flags": "|".join(str(value) for value in flags),
        "segment_id": "" if row["segment_id"] is None else str(row["segment_id"]),
        "event_kind": "" if row["event_kind"] is None else str(row["event_kind"]),
        "drop_reason": "" if row["drop_reason"] is None else str(row["drop_reason"]),
        "insertion_rule": ""
        if row["insertion_rule"] is None
        else str(row["insertion_rule"]),
        "raw_payload_json": str(row["raw_payload_json"]),
    }


def _materialize_event_models(
    rows: list[dict[str, str]],
) -> tuple[list[NormalizedAuditEvent], list[EnrichedEvent], list[StateLabeledEvent]]:
    normalized: list[NormalizedAuditEvent] = []
    enriched: list[EnrichedEvent] = []
    labeled: list[StateLabeledEvent] = []
    for row in rows:
        timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        payload = json.loads(row["raw_payload_json"])
        is_synthetic = row["is_synthetic"].casefold() == "true"
        row_number = _optional_int(row["row_number"])
        event_kind = _optional_int(row["event_kind"])
        enriched.append(
            EnrichedEvent(
                case_id=row["case_id"],
                timestamp=timestamp,
                event_type=row["event_type"],
                source=row["source"],
                is_synthetic=is_synthetic,
                source_detail=row["source_detail"],
                segment_id=row["segment_id"] or None,
                event_kind=event_kind,
                drop_reason=row["drop_reason"] or None,
                insertion_rule=row["insertion_rule"] or None,
                row_number=row_number,
                raw_payload=payload,
            )
        )
        labeled.append(
            StateLabeledEvent(
                case_id=row["case_id"],
                timestamp=timestamp,
                event_type=row["event_type"],
                segment_id=row["segment_id"] or None,
                event_kind=event_kind,
                source=row["source"],
                is_synthetic=is_synthetic,
                source_detail=row["source_detail"],
                insertion_rule=row["insertion_rule"] or None,
                row_number=row_number,
                state=row["state"] or None,
                state_assignment_rule=row["state_assignment_rule"] or None,
                cleanup_rule_applied=row["cleanup_rule_applied"] or None,
                drop_reason=row["drop_reason"] or None,
                raw_payload=payload,
            )
        )
        if row["source"] == "auditlog" and not is_synthetic:
            normalized.append(
                NormalizedAuditEvent(
                    case_id=row["case_id"],
                    row_number=0 if row_number is None else row_number,
                    timestamp=timestamp,
                    event_type=row["event_type"],
                    segment_id=row["segment_id"] or None,
                    event_kind=event_kind,
                    source=row["source"],
                    raw_payload=payload,
                )
            )
    # Normalization preserves source-query order, represented by the stable
    # AuditLogRecords row number. Canonical enriched events are datetime-sorted,
    # so their audit-log subset must be restored to source order before using
    # the standard normalized-event writer.
    normalized.sort(key=lambda event: event.row_number)
    return normalized, enriched, labeled


def _materialize_intervals(rows: list[dict[str, str]]) -> list[StateInterval]:
    return [
        StateInterval(
            case_id=row["case_id"],
            timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
            state=row["state"] or None,
            start_sec=float(row["start_sec"]),
            duration_sec=float(row["duration_sec"]),
            rebase_anchor=row["rebase_anchor"] or None,
            origin_event_type=row["origin_event_type"],
            source=row["source"],
            is_synthetic=row["is_synthetic"].casefold() == "true",
            source_detail=row["source_detail"],
            row_number=_optional_int(row["row_number"]),
            state_assignment_rule=row["state_assignment_rule"] or None,
            cleanup_rule_applied=row["cleanup_rule_applied"] or None,
            quality_flags=[value for value in row["quality_flags"].split("|") if value],
            segment_id=row["segment_id"] or None,
            event_kind=_optional_int(row["event_kind"]),
            drop_reason=row["drop_reason"] or None,
            insertion_rule=row["insertion_rule"] or None,
            raw_payload=json.loads(row["raw_payload_json"]),
        )
        for row in rows
    ]


class TimelineCacheReader:
    """Validate and query one explicit analytical store without writing it."""

    def __init__(
        self,
        *,
        database: Path,
        site_code: str,
        configuration_fingerprint_sha256: str,
        parser_version: ParserVersion | None = None,
    ) -> None:
        self.database = validate_database_path(database)
        self.site_code = site_code
        self.configuration_fingerprint_sha256 = configuration_fingerprint_sha256
        self.parser_version = parser_version or current_parser_version()
        self.records: list[dict[str, Any]] = []
        if not self.database.is_file():
            raise AnalyticalStoreError(f"Analytical cache database is missing: {self.database}")
        connection = _open_database(self.database, read_only=True)
        try:
            _verify_schema(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AnalyticalStoreError("Analytical cache integrity check failed.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise AnalyticalStoreError("Analytical cache foreign-key check failed.")
        finally:
            connection.close()

    def lookup(
        self,
        *,
        case_id: str,
        source: DatabaseSourceRecord,
        timing_log_path: Path | None,
    ) -> CacheLookupResult:
        started = time.perf_counter()
        inputs = [
            _present_analysis_input(
                role="clinical_database",
                path=source.source_path,
                source_type=source.source_type,
                archive_member=source.selected_zip_member or "",
            )
        ]
        if timing_log_path is None:
            inputs.append(
                _absent_analysis_input(role="timing_log", source_type="timing_log_csv")
            )
        else:
            inputs.append(
                _present_analysis_input(
                    role="timing_log",
                    path=timing_log_path,
                    source_type=timing_log_source_type(timing_log_path),
                )
            )
        input_fingerprint = analysis_input_fingerprint(inputs)
        case_configuration = case_configuration_fingerprint(
            self.configuration_fingerprint_sha256,
            input_fingerprint,
        )
        source_sha = str(inputs[0]["sha256"])
        timing_sha = inputs[1].get("sha256")
        connection = _open_database(self.database, read_only=True)
        try:
            matches = connection.execute(
                """
                SELECT * FROM v_cacheable_case_analyses
                WHERE site_code = ? AND case_id = ?
                  AND parser_fingerprint_sha256 = ?
                  AND cache_contract_version = ?
                  AND input_fingerprint_sha256 = ?
                  AND case_configuration_fingerprint_sha256 = ?
                ORDER BY case_analysis_id
                """,
                (
                    self.site_code,
                    case_id,
                    self.parser_version.source_fingerprint_sha256,
                    CACHE_CONTRACT_VERSION,
                    input_fingerprint,
                    case_configuration,
                ),
            ).fetchall()
            if not matches:
                return self._finish(
                    status="MISS",
                    case_id=case_id,
                    started=started,
                    reason="no_exact_cache_entry",
                    input_fingerprint=input_fingerprint,
                    source_sha=source_sha,
                    timing_sha=timing_sha,
                )
            if len(matches) != 1:
                return self._finish(
                    status="INVALID",
                    case_id=case_id,
                    started=started,
                    reason="multiple_exact_cache_entries",
                    input_fingerprint=input_fingerprint,
                    source_sha=source_sha,
                    timing_sha=timing_sha,
                )
            match = matches[0]
            analysis_id = int(match["case_analysis_id"])
            stored_inputs = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT input_role, input_ordinal, present, source_type,
                           observed_path, archive_member, size_bytes, mtime_ns, sha256
                    FROM case_analysis_inputs
                    WHERE case_analysis_id = ?
                    ORDER BY input_role, input_ordinal
                    """,
                    (analysis_id,),
                ).fetchall()
            ]
            if analysis_input_fingerprint(stored_inputs) != input_fingerprint:
                raise AnalyticalStoreError("stored analysis inputs do not match the cache key")
            event_rows = [
                _event_csv_row(row, case_id)
                for row in connection.execute(
                    "SELECT * FROM canonical_events WHERE case_analysis_id = ? ORDER BY event_ordinal",
                    (analysis_id,),
                ).fetchall()
            ]
            interval_rows = [
                _interval_csv_row(row, case_id)
                for row in connection.execute(
                    "SELECT * FROM state_intervals WHERE case_analysis_id = ? ORDER BY interval_ordinal",
                    (analysis_id,),
                ).fetchall()
            ]
            if not event_rows or not interval_rows:
                raise AnalyticalStoreError("cached canonical events or intervals are empty")
            artifact_fingerprint = _analysis_artifact_fingerprint(
                start_timestamp_iso=str(match["start_timestamp_iso"]),
                end_timestamp_iso=str(match["end_timestamp_iso"]),
                start_provenance_json=str(match["start_provenance_json"]),
                end_provenance_json=str(match["end_provenance_json"]),
                events=event_rows,
                intervals=interval_rows,
            )
            if artifact_fingerprint != str(match["analysis_artifact_fingerprint_sha256"]):
                raise AnalyticalStoreError("cached artifact fingerprint mismatch")
            metadata = json.loads(str(match["case_result_metadata_json"]))
            if not isinstance(metadata, dict):
                raise AnalyticalStoreError("cached case metadata is not an object")
            normalized, enriched, labeled = _materialize_event_models(event_rows)
            artifacts = CachedCaseArtifacts(
                case_analysis_id=analysis_id,
                normalized_events=normalized,
                enriched_events=enriched,
                state_labeled_events=labeled,
                state_intervals=_materialize_intervals(interval_rows),
                metadata=metadata,
                input_fingerprint_sha256=input_fingerprint,
                case_configuration_fingerprint_sha256=case_configuration,
            )
            return self._finish(
                status="HIT",
                case_id=case_id,
                started=started,
                reason="exact_cache_entry_materialized",
                input_fingerprint=input_fingerprint,
                source_sha=source_sha,
                timing_sha=timing_sha,
                artifacts=artifacts,
            )
        except (AnalyticalStoreError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._finish(
                status="INVALID",
                case_id=case_id,
                started=started,
                reason=f"cache_entry_invalid:{type(exc).__name__}:{exc}",
                input_fingerprint=input_fingerprint,
                source_sha=source_sha,
                timing_sha=timing_sha,
            )
        finally:
            connection.close()

    def _finish(
        self,
        *,
        status: str,
        case_id: str,
        started: float,
        reason: str,
        input_fingerprint: str,
        source_sha: str,
        timing_sha: str | None,
        artifacts: CachedCaseArtifacts | None = None,
    ) -> CacheLookupResult:
        duration = max(0.0, time.perf_counter() - started)
        record = {
            "case_id": case_id,
            "status": status,
            "reason": reason,
            "duration_seconds": duration,
            "input_fingerprint_sha256": input_fingerprint,
            "source_sha256": source_sha,
            "timing_log_sha256": timing_sha,
            "case_analysis_id": artifacts.case_analysis_id if artifacts else None,
        }
        self.records.append(record)
        return CacheLookupResult(
            status=status,
            case_id=case_id,
            duration_seconds=duration,
            reason=reason,
            input_fingerprint_sha256=input_fingerprint,
            source_sha256=source_sha,
            timing_log_sha256=timing_sha,
            artifacts=artifacts,
        )

    def summary(self) -> dict[str, Any]:
        counts = {status: 0 for status in ("HIT", "MISS", "INVALID")}
        for record in self.records:
            counts[str(record["status"])] += 1
        return {
            "cache_mode": "read-only",
            "database": str(self.database),
            "cache_contract_version": CACHE_CONTRACT_VERSION,
            "parser_fingerprint_sha256": self.parser_version.source_fingerprint_sha256,
            "configuration_fingerprint_sha256": self.configuration_fingerprint_sha256,
            "counts": counts,
            "cases": list(self.records),
        }
