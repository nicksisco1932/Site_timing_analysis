from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


SourceType = Literal["unzipped", "zip_extracted"]


@dataclass(slots=True)
class RunConfig:
    site_code: str
    year_selection: str
    root_dir: Path
    output_dir: Path
    site_path: Path | None = None
    allow_ambiguous_db: bool = False
    db_candidate_index: int | None = None
    zip_member_index: int | None = None
    timing_log_dir: Path | None = None
    diagnostics: bool = False
    diagnostics_file: Path | None = None


@dataclass(slots=True)
class CaseDiscoveryRecord:
    site_code: str
    case_id: str
    case_path: Path
    discovery_order: int
    candidate_unzipped_db_paths: list[Path] = field(default_factory=list)
    candidate_zip_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DatabaseSourceRecord:
    case_id: str
    case_path: Path
    source_type: SourceType
    source_path: Path
    selected_zip_member: str | None
    resolution_rule: str
    candidate_unzipped_db_paths: list[Path] = field(default_factory=list)
    candidate_zip_paths: list[Path] = field(default_factory=list)
    ambiguous_candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RawAuditEvent:
    case_id: str
    row_number: int
    raw_timestamp: str | None
    raw_event_type: str | None
    raw_segment_id: str | None
    raw_event_kind: int | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class NormalizedAuditEvent:
    case_id: str
    row_number: int
    timestamp: datetime
    event_type: str
    segment_id: str | None
    event_kind: int | None
    source: str
    raw_payload: dict[str, Any]
    is_dropped: bool = False
    drop_reason: str | None = None


@dataclass(slots=True)
class TimingLogEntry:
    case_id: str
    source_file: Path
    row_number: int
    label_text: str
    time_start_raw: str | None
    time_end_raw: str | None
    time_start: datetime | None
    time_end: datetime | None


@dataclass(slots=True)
class SyntheticEvent:
    case_id: str
    timestamp: datetime
    event_type: str
    segment_id: str | None
    event_kind: int | None
    source: str
    source_detail: str
    insertion_rule: str
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class EnrichedEvent:
    case_id: str
    timestamp: datetime
    event_type: str
    source: str
    is_synthetic: bool
    source_detail: str
    segment_id: str | None
    event_kind: int | None
    drop_reason: str | None
    insertion_rule: str | None
    row_number: int | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class StateLabeledEvent:
    case_id: str
    timestamp: datetime
    event_type: str
    segment_id: str | None
    event_kind: int | None
    source: str
    is_synthetic: bool
    source_detail: str
    insertion_rule: str | None
    row_number: int | None
    state: str | None
    state_assignment_rule: str | None
    cleanup_rule_applied: str | None
    drop_reason: str | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class StateInterval:
    case_id: str
    timestamp: datetime
    state: str | None
    start_sec: float
    duration_sec: float
    rebase_anchor: str | None
    origin_event_type: str
    source: str
    is_synthetic: bool
    source_detail: str
    row_number: int | None
    state_assignment_rule: str | None
    cleanup_rule_applied: str | None
    quality_flags: list[str] = field(default_factory=list)
    segment_id: str | None = None
    event_kind: int | None = None
    drop_reason: str | None = None
    insertion_rule: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunManifest:
    run_id: str
    started_at: datetime
    completed_at: datetime | None
    site_code: str
    year_selection: str
    root_dir: Path
    output_dir: Path
    cases_discovered: int
    cases_processed: int
    cases_failed: int
    warnings: list[str] = field(default_factory=list)
    case_results: list[dict[str, Any]] = field(default_factory=list)
    artifact_paths: dict[str, str] = field(default_factory=dict)
