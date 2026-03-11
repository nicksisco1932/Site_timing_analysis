from __future__ import annotations

import csv
import json
import sqlite3
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from site_timing_analysis.first_slice_cli import run_first_slice
from site_timing_analysis.manifest import write_state_labeled_events_csv
from site_timing_analysis.models import EnrichedEvent
from site_timing_analysis.state_machine import assign_states


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


def _event(
    *,
    ts: str,
    event_type: str,
    row: int | None,
    source: str = "auditlog",
    is_synthetic: bool = False,
    segment_id: str | None = None,
    event_kind: int | None = None,
) -> EnrichedEvent:
    return EnrichedEvent(
        case_id="064_01-001",
        timestamp=datetime.fromisoformat(ts),
        event_type=event_type,
        source=source,
        is_synthetic=is_synthetic,
        source_detail="test",
        segment_id=segment_id,
        event_kind=event_kind,
        drop_reason=None,
        insertion_rule=None,
        row_number=row,
        raw_payload={"event_type": event_type},
    )


def test_core_event_to_state_mapping() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:10:00", event_type="SetupUnlockWorkflowRecord", row=2),
        _event(ts="2025-01-01 09:20:00", event_type="AnesthesiaStart", row=3),
        _event(ts="2025-01-01 09:30:00", event_type="DeviceInsertionBegins", row=4),
        _event(ts="2025-01-01 09:40:00", event_type="InitialImaging", row=5),
        _event(ts="2025-01-01 10:00:00", event_type="AlignmentWorkflowRecord", row=6),
        _event(ts="2025-01-01 10:05:00", event_type="CoarseWorkflowRecord", row=7),
        _event(ts="2025-01-01 10:20:00", event_type="DetailedWorkflowRecord", row=8),
        _event(ts="2025-01-01 10:40:00", event_type="PlanReadyWorkflowRecord", row=9),
        _event(ts="2025-01-01 10:45:00", event_type="DeliveryInitializingWorkflowRecord", row=10),
    ]
    state_rows, warnings = assign_states(events)
    assert warnings == []
    assert [row.state for row in state_rows] == [
        "TULSA QA",
        "Room ready",
        "Patient positioning & induction",
        "Device insertion",
        "Device repositioning",
        "Alignment",
        "Coarse",
        "Detailed",
        "Planning start angle",
        "Initialization",
    ]


def test_pause_resume_and_review_post_treatment_transitions() -> None:
    events = [
        _event(ts="2025-01-01 11:00:00", event_type="DeliveryWorkflowRecord", row=1),
        _event(ts="2025-01-01 11:10:00", event_type="DeliveryPausedWorkflowRecord", row=2),
        _event(ts="2025-01-01 11:20:00", event_type="DeliveryResumedWorkflowRecord", row=3),
        _event(ts="2025-01-01 11:30:00", event_type="DeliveryInterruptedWorkflowRecord", row=4),
        _event(ts="2025-01-01 11:40:00", event_type="ReviewWorkflowRecord", row=5),
    ]
    state_rows, warnings = assign_states(events)
    assert warnings == []
    assert [row.state for row in state_rows] == [
        "Treating",
        "Paused",
        "Treating",
        "Review",
        "Post-treatment scans & Device removal",
    ]


def test_unmapped_event_warning_reporting() -> None:
    events = [_event(ts="2025-01-01 08:00:00", event_type="UnknownWorkflowRecord", row=1)]
    state_rows, warnings = assign_states(events)
    assert state_rows[0].state is None
    assert any("state_unmapped_event_type:UnknownWorkflowRecord" in warning for warning in warnings)


def test_duplicate_alignment_cleanup_behavior() -> None:
    events = [
        _event(ts="2025-01-01 10:00:00", event_type="CoarseWorkflowRecord", row=1),
        _event(ts="2025-01-01 10:00:00", event_type="AlignmentWorkflowRecord", row=2),
    ]
    state_rows, warnings = assign_states(events)
    assert state_rows[0].state == "Coarse"
    assert state_rows[1].state is None
    assert state_rows[1].cleanup_rule_applied == "clear_alignment_duplicate_coarse_same_timestamp"
    assert any("cleanup_alignment_duplicate" in warning for warning in warnings)


def test_segment_date_mismatch_state_clearing() -> None:
    events = [
        _event(
            ts="2025-01-01 10:00:00",
            event_type="SetupWorkflowRecord",
            row=1,
            segment_id="2024-12-31_segment",
        )
    ]
    state_rows, warnings = assign_states(events)
    assert state_rows[0].state is None
    assert state_rows[0].cleanup_rule_applied == "clear_segment_date_mismatch"
    assert any("cleanup_segment_date_mismatch" in warning for warning in warnings)


def test_state_labeled_export_schema_content(tmp_path: Path) -> None:
    state_rows, _ = assign_states([_event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1)])
    out_path = write_state_labeled_events_csv(
        case_id="064_01-001",
        state_labeled_events=state_rows,
        output_dir=tmp_path,
    )

    with out_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    expected = {
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
    }
    assert expected.issubset(set(rows[0].keys()))


def test_state_assignment_input_immutability() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:05:00", event_type="SetupUnlockWorkflowRecord", row=2),
    ]
    snapshot = deepcopy(events)
    assign_states(events)
    assert events == snapshot


def test_cli_generates_state_labeled_artifact_and_warning_capture(tmp_path: Path) -> None:
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
            "CREATE TABLE Sessions (Id INTEGER PRIMARY KEY, TimePatientSedatedAt TEXT)",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-01 12:00:00.0000000', 'UnknownWorkflowRecord', 'SEG-1', 1)",
            "INSERT INTO Sessions (TimePatientSedatedAt) VALUES ('2025-01-01 12:05:00')",
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

    state_labeled_path = output_dir / "state_labeled_events" / "064_01-001_state_labeled_events.csv"
    assert state_labeled_path.exists()

    processed_cases = [case for case in manifest.case_results if case.get("status") == "processed"]
    assert len(processed_cases) == 1
    case_meta = processed_cases[0]
    assert int(case_meta["state_labeled_event_count"]) >= 1
    assert int(case_meta["state_assignment_warning_count"]) >= 1
    assert any("state_unmapped_event_type" in warning for warning in case_meta["state_warnings"])
    assert any("state_unmapped_event_type" in warning for warning in manifest.warnings)

    manifest_payload = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    processed_payload_rows = [row for row in manifest_payload["case_results"] if row.get("status") == "processed"]
    assert len(processed_payload_rows) == 1
    assert "state_labeled_export" in processed_payload_rows[0]
