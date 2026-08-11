# Project: Site Timing Analysis
# File: testing/tests/test_enrichment_slice.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Tests enrichment slice behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
import json
import sqlite3
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from site_timing_analysis.enrichment import (
    derive_session_synthetic_events,
    derive_timing_log_synthetic_events,
    merge_enriched_events,
)
from site_timing_analysis.first_slice_cli import run_first_slice
from site_timing_analysis.manifest import write_enriched_events_csv
from site_timing_analysis.output_layout import output_layout
from site_timing_analysis.models import NormalizedAuditEvent, SyntheticEvent, TimingLogEntry
from site_timing_analysis.timing_log import find_timing_log, parse_timing_log_csv
from site_timing_analysis.errors import TimingLogParseError


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


def test_session_synthetic_events_from_valid_fields() -> None:
    sessions_rows = [
        {
            "TimePatientSedatedAt": "2025-01-01 09:00:00",
            "TimeUaInsertedAt": "2025-01-01 09:30:00",
            "TimePatientTransferredAt": "2025-01-01 14:00:00",
            "TimeUaRemovedAt": "2025-01-01 13:30:00",
        }
    ]

    events, warnings = derive_session_synthetic_events("064_01-001", sessions_rows)

    assert [event.event_type for event in events] == [
        "Ready4Urology",
        "DeviceInsertionEnds",
        "PatientTransferEnds",
    ]
    assert all(event.source == "sessions" for event in events)
    assert all(event.insertion_rule == "session_field_map_v1" for event in events)
    assert "064_01-001:session_field_unmapped:TimeUaRemovedAt:row=1" in warnings


def test_session_missing_and_unparseable_fields_emit_warnings() -> None:
    sessions_rows = [
        {
            "TimePatientSedatedAt": "not-a-date",
            "TimeUaInsertedAt": "",
            "TimePatientTransferredAt": None,
            "TimeUaRemovedAt": "still-not-a-date",
        }
    ]

    events, warnings = derive_session_synthetic_events("064_01-001", sessions_rows)

    assert events == []
    assert any("session_unparseable:TimePatientSedatedAt" in warning for warning in warnings)
    assert any("session_unparseable:TimeUaRemovedAt" in warning for warning in warnings)
    assert any("session_field_not_usable:TimeUaInsertedAt" in warning for warning in warnings)
    assert any("session_field_not_usable:TimePatientTransferredAt" in warning for warning in warnings)


def test_session_sentinel_timestamps_are_ignored_with_explicit_warning() -> None:
    sessions_rows = [
        {
            "TimePatientSedatedAt": "0001-01-01 00:00:00",
            "TimeUaInsertedAt": "2025-01-01 09:30:00",
            "TimePatientTransferredAt": "0001-01-01T00:00:00.0000000",
            "TimeUaRemovedAt": "0001-01-01 00:00:00",
        }
    ]

    events, warnings = derive_session_synthetic_events("064_01-001", sessions_rows)

    assert [event.event_type for event in events] == ["DeviceInsertionEnds"]
    assert all(event.source == "sessions" for event in events)
    assert any(
        "ignored_session_sentinel_timestamp:TimePatientSedatedAt:0001-01-01 00:00:00" in warning
        for warning in warnings
    )
    assert any(
        "ignored_session_sentinel_timestamp:TimePatientTransferredAt:0001-01-01T00:00:00.0000000"
        in warning
        for warning in warnings
    )
    assert any(
        "ignored_session_sentinel_timestamp:TimeUaRemovedAt:0001-01-01 00:00:00" in warning
        for warning in warnings
    )
    assert any("session_field_not_usable:TimePatientSedatedAt" in warning for warning in warnings)


def test_valid_session_timestamps_still_emit_neighboring_events_with_sentinel_present() -> None:
    sessions_rows = [
        {
            "TimePatientSedatedAt": "0001-01-01 00:00:00",
            "TimeUaInsertedAt": "2025-01-01 09:30:00",
            "TimePatientTransferredAt": "2025-01-01 14:00:00",
            "TimeUaRemovedAt": "2025-01-01 13:30:00",
        }
    ]

    events, warnings = derive_session_synthetic_events("064_01-001", sessions_rows)
    event_types = [event.event_type for event in events]

    assert "Ready4Urology" not in event_types
    assert "DeviceInsertionEnds" in event_types
    assert "PatientTransferEnds" in event_types
    assert any("ignored_session_sentinel_timestamp:TimePatientSedatedAt" in warning for warning in warnings)
    assert "064_01-001:session_field_unmapped:TimeUaRemovedAt:row=1" in warnings


def test_session_pre_device_fields_after_end_markers_are_ignored() -> None:
    sessions_rows = [
        {
            "TimePatientSedatedAt": "2026-01-20 19:58:52.882",
            "TimeUaInsertedAt": "2026-01-20 20:27:53.292",
            "TimeUaRemovedAt": "2026-01-20 12:20:53.292",
            "TimePatientTransferredAt": "2026-01-20 12:40:53.388",
        }
    ]

    events, warnings = derive_session_synthetic_events("109_01-021", sessions_rows)

    assert [event.event_type for event in events] == ["PatientTransferEnds"]
    assert any(
        "session_field_after_end_marker:TimePatientSedatedAt:row=1:end_field=TimeUaRemovedAt"
        in warning
        for warning in warnings
    )
    assert any(
        "session_field_after_end_marker:TimeUaInsertedAt:row=1:end_field=TimeUaRemovedAt"
        in warning
        for warning in warnings
    )
    assert any("session_field_not_usable:TimePatientSedatedAt" in warning for warning in warnings)
    assert any("session_field_not_usable:TimeUaInsertedAt" in warning for warning in warnings)


def test_timing_log_absent_behavior(tmp_path: Path) -> None:
    site_root = tmp_path / "Stanford_064"
    site_root.mkdir()

    found = find_timing_log("064_01-001", site_root)
    assert found is None

    missing_file = site_root / "TimingLogs" / "064_01-001.csv"
    entries, warnings = parse_timing_log_csv(missing_file, "064_01-001")
    assert entries == []
    assert warnings == []


def test_timing_log_parse_explicit_columns_and_mapping() -> None:
    entry = TimingLogEntry(
        case_id="064_01-001",
        source_file=Path("timing.csv"),
        row_number=2,
        label_text="Devices Insertion",
        time_start_raw="2025-01-01 09:30:00",
        time_end_raw="2025-01-01 10:15:00",
        time_start=datetime(2025, 1, 1, 9, 30, 0),
        time_end=datetime(2025, 1, 1, 10, 15, 0),
    )

    events, warnings = derive_timing_log_synthetic_events([entry])
    assert warnings == []
    assert [event.event_type for event in events] == ["DeviceInsertionBegins", "DeviceInsertionEnds"]
    assert all(event.source == "timing_log" for event in events)
    assert all(event.source_detail == "Devices Insertion" for event in events)


def test_timing_log_parsing_and_unmapped_label_warning(tmp_path: Path) -> None:
    timing_dir = tmp_path / "Stanford_064" / "TimingLogs"
    timing_dir.mkdir(parents=True)
    timing_path = timing_dir / "064_01-001.csv"
    timing_path.write_text(
        "Events,TimeSTART,TimeEND\n"
        "Unknown Label,2025-01-01 09:00:00,2025-01-01 09:05:00\n",
        encoding="utf-8",
    )

    entries, parse_warnings = parse_timing_log_csv(timing_path, "064_01-001")
    assert parse_warnings == []
    events, map_warnings = derive_timing_log_synthetic_events(entries)
    assert events == []
    assert any("timing_log_unmapped_label" in warning for warning in map_warnings)


def test_malformed_present_timing_log_fails_loudly(tmp_path: Path) -> None:
    timing_dir = tmp_path / "Stanford_064" / "TimingLogs"
    timing_dir.mkdir(parents=True)
    timing_path = timing_dir / "064_01-001.csv"
    timing_path.write_text("A,B\n1,2\n", encoding="utf-8")

    with pytest.raises(TimingLogParseError):
        parse_timing_log_csv(timing_path, "064_01-001")


def test_merge_ordering_and_raw_event_immutability() -> None:
    ts = datetime(2025, 1, 1, 9, 0, 0)
    raw_payload_1 = {"k": "v1"}
    raw_payload_2 = {"k": "v2"}
    normalized = [
        NormalizedAuditEvent(
            case_id="064_01-001",
            row_number=2,
            timestamp=ts,
            event_type="B",
            segment_id="SEG",
            event_kind=1,
            source="auditlog",
            raw_payload=raw_payload_2,
        ),
        NormalizedAuditEvent(
            case_id="064_01-001",
            row_number=1,
            timestamp=ts,
            event_type="A",
            segment_id="SEG",
            event_kind=1,
            source="auditlog",
            raw_payload=raw_payload_1,
        ),
    ]
    normalized_snapshot = deepcopy(normalized)

    synthetic_events = [
        SyntheticEvent(
            case_id="064_01-001",
            timestamp=ts,
            event_type="Ready4Urology",
            segment_id=None,
            event_kind=None,
            source="timing_log",
            source_detail="Patient is ready for Urology team",
            insertion_rule="timing_log_label_map_v1",
            raw_payload={"label": "Patient is ready for Urology team"},
        ),
        SyntheticEvent(
            case_id="064_01-001",
            timestamp=ts,
            event_type="DeviceInsertionEnds",
            segment_id=None,
            event_kind=None,
            source="sessions",
            source_detail="Sessions.TimeUaInsertedAt",
            insertion_rule="session_field_map_v1",
            raw_payload={"source_field": "TimeUaInsertedAt"},
        ),
    ]

    merged = merge_enriched_events(normalized, synthetic_events)
    assert [event.event_type for event in merged] == ["A", "B", "DeviceInsertionEnds", "Ready4Urology"]
    assert [event.is_synthetic for event in merged] == [False, False, True, True]
    assert [event.source for event in merged] == ["auditlog", "auditlog", "sessions", "timing_log"]
    assert normalized == normalized_snapshot


def test_enriched_export_contains_required_fields(tmp_path: Path) -> None:
    ts = datetime(2025, 1, 1, 9, 0, 0)
    normalized = [
        NormalizedAuditEvent(
            case_id="064_01-001",
            row_number=1,
            timestamp=ts,
            event_type="SetupWorkflowRecord",
            segment_id="SEG-1",
            event_kind=1,
            source="auditlog",
            raw_payload={"Id": 1},
        )
    ]
    merged = merge_enriched_events(normalized, [])
    out_path = write_enriched_events_csv(
        case_id="064_01-001",
        enriched_events=merged,
        output_dir=tmp_path,
    )

    with out_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    required_fields = {
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
    }
    assert required_fields.issubset(set(rows[0].keys()))


def test_cli_enrichment_exports_and_warning_capture(tmp_path: Path) -> None:
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
            "CREATE TABLE Sessions ("
            "Id INTEGER PRIMARY KEY, "
            "TimePatientSedatedAt TEXT, "
            "TimeUaInsertedAt TEXT, "
            "TimeUaRemovedAt TEXT, "
            "TimePatientTransferredAt TEXT"
            ")",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'SetupWorkflowRecord', 'SEG-1', 1)",
            "INSERT INTO Sessions (TimePatientSedatedAt, TimeUaInsertedAt, TimeUaRemovedAt, TimePatientTransferredAt) "
            "VALUES ('2025-01-01 12:05:00', '2025-01-01 12:20:00', '2025-01-01 13:00:00', '2025-01-01 15:00:00')",
        ],
    )

    timing_dir = site_dir / "TimingLogs"
    timing_dir.mkdir(parents=True)
    (timing_dir / "064_01-001.csv").write_text(
        "Events,TimeSTART,TimeEND\n"
        "Unknown Label,2025-01-01 11:00:00,2025-01-01 11:10:00\n",
        encoding="utf-8",
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

    layout = output_layout(output_dir)
    enriched_path = layout.enriched_events_dir / "064_01-001_enriched_events.csv"
    assert enriched_path.exists()

    processed_cases = [case for case in manifest.case_results if case.get("status") == "processed"]
    assert len(processed_cases) == 1
    case_meta = processed_cases[0]
    assert int(case_meta["session_synthetic_count"]) == 3
    assert int(case_meta["timing_log_synthetic_count"]) == 0
    assert int(case_meta["enriched_event_count"]) >= 1
    assert isinstance(case_meta["enrichment_warnings"], list)
    assert any("timing_log_unmapped_label" in warning for warning in case_meta["enrichment_warnings"])
    assert any("timing_log_unmapped_label" in warning for warning in manifest.warnings)

    manifest_path = layout.run_manifest_path
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_results = [row for row in payload["case_results"] if row.get("status") == "processed"]
    assert len(case_results) == 1
    assert isinstance(case_results[0]["enrichment_warnings"], list)
