from __future__ import annotations

import csv
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from site_timing_analysis.config import build_run_config
from site_timing_analysis.db_source import resolve_database_source
from site_timing_analysis.discovery import discover_cases
from site_timing_analysis.errors import (
    AmbiguousDatabaseSourceError,
    MissingTableError,
    NormalizationError,
)
from site_timing_analysis.first_slice_cli import build_run_diagnostics, run_first_slice
from site_timing_analysis.ingestion import ingest_case_database
from site_timing_analysis.manifest import (
    write_case_manifest,
    write_normalized_events_csv,
    write_run_manifest,
)
from site_timing_analysis.models import (
    CaseDiscoveryRecord,
    DatabaseSourceRecord,
    NormalizedAuditEvent,
    RawAuditEvent,
    RunManifest,
    StateInterval,
)
from site_timing_analysis.normalization import normalize_audit_events


def _create_sqlite(path: Path, sql: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        for statement in sql:
            cur.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _interval(
    *,
    case_id: str,
    ts: str,
    duration_sec: float,
    flags: list[str] | None = None,
) -> StateInterval:
    return StateInterval(
        case_id=case_id,
        timestamp=datetime.fromisoformat(ts),
        state="Room ready",
        start_sec=0.0,
        duration_sec=duration_sec,
        rebase_anchor="Alignment",
        origin_event_type="SetupWorkflowRecord",
        source="auditlog",
        is_synthetic=False,
        source_detail="test",
        row_number=1,
        state_assignment_rule="test_rule",
        cleanup_rule_applied="",
        quality_flags=list(flags or []),
    )


def test_discovery_ordering_is_stable(tmp_path: Path) -> None:
    site_root = tmp_path / "Stanford_064"
    (site_root / "064_01-010").mkdir(parents=True)
    (site_root / "064_01-002").mkdir(parents=True)
    (site_root / "064_01-001").mkdir(parents=True)

    config = build_run_config(
        site_code="Stanford_064",
        year_selection="All",
        root_dir=tmp_path,
        output_dir=tmp_path / "out",
    )
    records = discover_cases(config)

    assert [record.case_id for record in records] == ["064_01-001", "064_01-002", "064_01-010"]
    assert [record.discovery_order for record in records] == [1, 2, 3]
    assert all("no_database_candidates_found" in record.warnings for record in records)


def test_db_source_precedence_prefers_unzipped_over_zip(tmp_path: Path) -> None:
    case_path = tmp_path / "064_01-001"
    case_path.mkdir()
    unzipped_db = case_path / "local.db"
    unzipped_db.write_text("", encoding="utf-8")

    zip_path = case_path / "Session123.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("nested/local.db", "placeholder")

    record = CaseDiscoveryRecord(
        site_code="Stanford_064",
        case_id="064_01-001",
        case_path=case_path,
        discovery_order=1,
        candidate_unzipped_db_paths=[unzipped_db],
        candidate_zip_paths=[zip_path],
    )
    source = resolve_database_source(record)

    assert source.source_type == "unzipped"
    assert source.source_path == unzipped_db
    assert source.selected_zip_member is None


def test_ambiguous_unzipped_db_raises_typed_error(tmp_path: Path) -> None:
    case_path = tmp_path / "064_01-001"
    case_path.mkdir()
    db1 = case_path / "a" / "_x" / "local.db"
    db2 = case_path / "b" / "_x" / "local.db"
    db1.parent.mkdir(parents=True)
    db2.parent.mkdir(parents=True)
    db1.write_text("", encoding="utf-8")
    db2.write_text("", encoding="utf-8")

    record = CaseDiscoveryRecord(
        site_code="Stanford_064",
        case_id="064_01-001",
        case_path=case_path,
        discovery_order=1,
        candidate_unzipped_db_paths=[db1, db2],
        candidate_zip_paths=[],
    )

    with pytest.raises(AmbiguousDatabaseSourceError):
        resolve_database_source(record)


def test_ingestion_raises_when_auditlogrecords_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "missing_audit.db"
    _create_sqlite(
        db_path,
        [
            "CREATE TABLE Sessions (Id INTEGER PRIMARY KEY, TdcVersion TEXT)",
            "INSERT INTO Sessions (TdcVersion) VALUES ('2.10')",
        ],
    )

    source = DatabaseSourceRecord(
        case_id="064_01-001",
        case_path=tmp_path,
        source_type="unzipped",
        source_path=db_path,
        selected_zip_member=None,
        resolution_rule="test",
    )

    with pytest.raises(MissingTableError):
        ingest_case_database(source)


def test_normalization_required_fields() -> None:
    raw_events = [
        RawAuditEvent(
            case_id="064_01-001",
            row_number=1,
            raw_timestamp=None,
            raw_event_type="SetupWorkflowRecord",
            raw_segment_id=None,
            raw_event_kind=None,
            raw_payload={},
        )
    ]
    with pytest.raises(NormalizationError):
        normalize_audit_events(raw_events)


def test_signalrecord_filtering_has_explicit_drop_reason() -> None:
    raw_events = [
        RawAuditEvent(
            case_id="064_01-001",
            row_number=1,
            raw_timestamp="2025-01-01 12:00:00.0000000",
            raw_event_type="SignalRecord",
            raw_segment_id=None,
            raw_event_kind=0,
            raw_payload={"AuditRecordBase_Type": "SignalRecord"},
        ),
        RawAuditEvent(
            case_id="064_01-001",
            row_number=2,
            raw_timestamp="2025-01-01 12:01:00.0000000",
            raw_event_type="SetupWorkflowRecord",
            raw_segment_id=None,
            raw_event_kind=1,
            raw_payload={"AuditRecordBase_Type": "SetupWorkflowRecord"},
        ),
    ]

    kept, dropped = normalize_audit_events(raw_events)
    assert len(kept) == 1
    assert len(dropped) == 1
    assert dropped[0].drop_reason == "filtered_signal_record"
    assert dropped[0].is_dropped is True


def test_treatmentid_is_canonicalized_to_segment_id(tmp_path: Path) -> None:
    db_path = tmp_path / "with_treatment_id.db"
    _create_sqlite(
        db_path,
        [
            "CREATE TABLE AuditLogRecords ("
            "Id INTEGER PRIMARY KEY, "
            "TimeStamp TEXT, "
            "AuditRecordBase_Type TEXT, "
            "TreatmentId TEXT, "
            "EventKind INTEGER"
            ")",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, TreatmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'SetupWorkflowRecord', 'SEG-123', 2)",
        ],
    )

    source = DatabaseSourceRecord(
        case_id="064_01-001",
        case_path=tmp_path,
        source_type="unzipped",
        source_path=db_path,
        selected_zip_member=None,
        resolution_rule="test",
    )
    result = ingest_case_database(source)
    raw_events = result["raw_events"]
    assert len(raw_events) == 1
    assert raw_events[0].raw_segment_id == "SEG-123"

    kept, dropped = normalize_audit_events(raw_events)
    assert len(dropped) == 0
    assert kept[0].segment_id == "SEG-123"


def test_manifest_and_normalized_event_exports(tmp_path: Path) -> None:
    now = datetime(2026, 3, 10, 12, 0, 0)
    manifest = RunManifest(
        run_id="run-001",
        started_at=now,
        completed_at=now,
        site_code="Stanford_064",
        year_selection="All",
        root_dir=tmp_path,
        output_dir=tmp_path / "out",
        cases_discovered=1,
        cases_processed=1,
        cases_failed=0,
        warnings=[],
        case_results=[{"case_id": "064_01-001", "status": "ok"}],
        artifact_paths={},
    )
    case_record = CaseDiscoveryRecord(
        site_code="Stanford_064",
        case_id="064_01-001",
        case_path=tmp_path / "Stanford_064" / "064_01-001",
        discovery_order=1,
        candidate_unzipped_db_paths=[tmp_path / "Stanford_064" / "064_01-001" / "local.db"],
        candidate_zip_paths=[],
        warnings=[],
    )
    normalized = [
        NormalizedAuditEvent(
            case_id="064_01-001",
            row_number=1,
            timestamp=now,
            event_type="SetupWorkflowRecord",
            segment_id="SEG-1",
            event_kind=1,
            source="auditlog",
            raw_payload={"AuditRecordBase_Type": "SetupWorkflowRecord"},
            is_dropped=False,
            drop_reason=None,
        )
    ]

    out_dir = tmp_path / "exports"
    run_manifest_path = write_run_manifest(manifest, out_dir)
    case_manifest_path = write_case_manifest([case_record], out_dir)
    events_path = write_normalized_events_csv(
        case_id="064_01-001",
        normalized_events=normalized,
        output_dir=out_dir,
    )

    assert run_manifest_path.exists()
    assert case_manifest_path.exists()
    assert events_path.exists()

    payload = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-001"

    with case_manifest_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "064_01-001"


def test_first_slice_cli_writes_required_exports(tmp_path: Path) -> None:
    root_dir = tmp_path / "root"
    site_dir = root_dir / "Stanford_064"
    case_dir = site_dir / "064_01-001"
    case_dir.mkdir(parents=True)

    db_path = case_dir / "local.db"
    _create_sqlite(
        db_path,
        [
            "CREATE TABLE AuditLogRecords ("
            "Id INTEGER PRIMARY KEY, "
            "TimeStamp TEXT, "
            "AuditRecordBase_Type TEXT, "
            "SegmentId TEXT, "
            "EventKind INTEGER"
            ")",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'SignalRecord', 'SEG-1', 0)",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:01:00.0000000', 'SetupWorkflowRecord', 'SEG-1', 1)",
        ],
    )

    output_dir = tmp_path / "out"
    manifest = run_first_slice(
        [
            "--site",
            "Stanford_064",
            "--years",
            "2025",
            "--root",
            str(root_dir),
            "--output",
            str(output_dir),
        ]
    )

    assert manifest.cases_discovered == 1
    assert manifest.cases_processed == 1
    assert (output_dir / "run_manifest.json").exists()
    assert (output_dir / "case_manifest.csv").exists()

    normalized_path = output_dir / "normalized_events" / "064_01-001_normalized_events.csv"
    assert normalized_path.exists()

    with normalized_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["event_type"] == "SetupWorkflowRecord"


def test_diagnostics_option_writes_default_summary_file(tmp_path: Path) -> None:
    root_dir = tmp_path / "root"
    site_dir = root_dir / "Stanford_064"
    case_dir = site_dir / "064_01-001"
    case_dir.mkdir(parents=True)

    db_path = case_dir / "local.db"
    _create_sqlite(
        db_path,
        [
            "CREATE TABLE AuditLogRecords ("
            "Id INTEGER PRIMARY KEY, "
            "TimeStamp TEXT, "
            "AuditRecordBase_Type TEXT, "
            "SegmentId TEXT, "
            "EventKind INTEGER"
            ")",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'SetupWorkflowRecord', 'SEG-1', 1)",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:30:00.0000000', 'AlignmentWorkflowRecord', 'SEG-1', 1)",
        ],
    )

    output_dir = tmp_path / "out"
    manifest = run_first_slice(
        [
            "--site",
            "Stanford_064",
            "--years",
            "2025",
            "--root",
            str(root_dir),
            "--output",
            str(output_dir),
            "--diagnostics",
        ]
    )

    diagnostics_path = output_dir / "diagnostics_summary.md"
    assert diagnostics_path.exists()
    assert manifest.artifact_paths.get("diagnostics_summary") == str(diagnostics_path)
    text = diagnostics_path.read_text(encoding="utf-8")
    assert "## Run Summary" in text
    assert "## Interval Sanity" in text
    assert "## Quality-Flag Counts" in text
    assert "## Warning Summary" in text
    assert "## Artifact Summary" in text


def test_diagnostics_file_override_is_respected(tmp_path: Path) -> None:
    root_dir = tmp_path / "root"
    site_dir = root_dir / "Stanford_064"
    case_dir = site_dir / "064_01-001"
    case_dir.mkdir(parents=True)

    db_path = case_dir / "local.db"
    _create_sqlite(
        db_path,
        [
            "CREATE TABLE AuditLogRecords ("
            "Id INTEGER PRIMARY KEY, "
            "TimeStamp TEXT, "
            "AuditRecordBase_Type TEXT, "
            "SegmentId TEXT, "
            "EventKind INTEGER"
            ")",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'SetupWorkflowRecord', 'SEG-1', 1)",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:30:00.0000000', 'AlignmentWorkflowRecord', 'SEG-1', 1)",
        ],
    )

    output_dir = tmp_path / "out"
    custom_path = tmp_path / "custom" / "my_diag.md"
    manifest = run_first_slice(
        [
            "--site",
            "Stanford_064",
            "--years",
            "2025",
            "--root",
            str(root_dir),
            "--output",
            str(output_dir),
            "--diagnostics",
            "--diagnostics-file",
            str(custom_path),
        ]
    )

    assert custom_path.exists()
    assert not (output_dir / "diagnostics_summary.md").exists()
    assert manifest.artifact_paths.get("diagnostics_summary") == str(custom_path)


def test_build_run_diagnostics_counts_thresholds_and_quality_flags(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
    (out_dir / "case_manifest.csv").write_text("case_id\n064_01-001\n", encoding="utf-8")
    plots_dir = out_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    (plots_dir / "normalized_timeline.png").write_text("x", encoding="utf-8")
    (plots_dir / "original_hour_timeline.png").write_text("x", encoding="utf-8")

    run_manifest = RunManifest(
        run_id="run-001",
        started_at=datetime(2026, 3, 11, 12, 0, 0),
        completed_at=datetime(2026, 3, 11, 12, 1, 0),
        site_code="064",
        year_selection="All",
        root_dir=tmp_path,
        output_dir=out_dir,
        cases_discovered=2,
        cases_processed=2,
        cases_failed=0,
        warnings=[
            "064_01-001:interval_truncated_large_gap:row=1",
            "064_01-001:interval_early_state_truncated:row=2",
            "064_01-002:interval_negative_rebased_start:row=3",
        ],
        case_results=[],
        artifact_paths={
            "normalized_timeline": str(plots_dir / "normalized_timeline.png"),
            "original_hour_timeline": str(plots_dir / "original_hour_timeline.png"),
        },
    )
    intervals = [
        _interval(case_id="064_01-001", ts="2025-01-01 10:00:00", duration_sec=100.0, flags=[]),
        _interval(
            case_id="064_01-001",
            ts="2025-01-01 10:02:00",
            duration_sec=8001.0,
            flags=["interval_truncated_large_gap", "negative_rebased_start"],
        ),
        _interval(
            case_id="064_01-002",
            ts="2025-01-01 10:05:00",
            duration_sec=16000.0,
            flags=["interval_terminal_state_clamped", "interval_early_state_truncated"],
        ),
        _interval(
            case_id="064_01-002",
            ts="2025-01-01 10:10:00",
            duration_sec=40000.0,
            flags=["interval_unassigned_state_truncated"],
        ),
    ]

    summary = build_run_diagnostics(
        run_manifest=run_manifest,
        state_intervals=intervals,
        output_dir=out_dir,
    )

    interval = summary["interval_sanity"]
    assert interval["duration_count_gt_7200"] == 3
    assert interval["duration_count_gt_14400"] == 2
    assert interval["duration_count_gt_28800"] == 1
    assert interval["max_duration_sec"] == 40000.0

    flags = summary["quality_flag_counts"]
    assert flags["interval_truncated_large_gap"] == 1
    assert flags["interval_terminal_state_clamped"] == 1
    assert flags["interval_early_state_truncated"] == 1
    assert flags["interval_unassigned_state_truncated"] == 1
    assert flags["negative_rebased_start"] == 1


def test_cli_behavior_unchanged_without_diagnostics(tmp_path: Path) -> None:
    root_dir = tmp_path / "root"
    site_dir = root_dir / "Stanford_064"
    case_dir = site_dir / "064_01-001"
    case_dir.mkdir(parents=True)

    db_path = case_dir / "local.db"
    _create_sqlite(
        db_path,
        [
            "CREATE TABLE AuditLogRecords ("
            "Id INTEGER PRIMARY KEY, "
            "TimeStamp TEXT, "
            "AuditRecordBase_Type TEXT, "
            "SegmentId TEXT, "
            "EventKind INTEGER"
            ")",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'SetupWorkflowRecord', 'SEG-1', 1)",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:30:00.0000000', 'AlignmentWorkflowRecord', 'SEG-1', 1)",
        ],
    )

    output_dir = tmp_path / "out"
    manifest = run_first_slice(
        [
            "--site",
            "Stanford_064",
            "--years",
            "2025",
            "--root",
            str(root_dir),
            "--output",
            str(output_dir),
        ]
    )

    assert manifest.cases_processed == 1
    assert "diagnostics_summary" not in manifest.artifact_paths
    assert not (output_dir / "diagnostics_summary.md").exists()
