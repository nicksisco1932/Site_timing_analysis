# Project: Site Timing Analysis
# File: testing/tests/test_timing_slice.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Tests timing slice behavior for the Site Timing Analysis workflow.
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

from site_timing_analysis.first_slice_cli import run_first_slice
from site_timing_analysis.manifest import write_state_intervals_csv
from site_timing_analysis.models import StateLabeledEvent
from site_timing_analysis.output_layout import output_layout
from site_timing_analysis.plotting import generate_timeline_plots
from site_timing_analysis.timing import compute_state_intervals


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
    state: str | None = "Room ready",
    source: str = "auditlog",
    is_synthetic: bool = False,
    source_detail: str = "test",
    insertion_rule: str | None = None,
    state_assignment_rule: str | None = "test_rule",
    segment_id: str | None = None,
    event_kind: int | None = None,
) -> StateLabeledEvent:
    return StateLabeledEvent(
        case_id="064_01-001",
        timestamp=datetime.fromisoformat(ts),
        event_type=event_type,
        segment_id=segment_id,
        event_kind=event_kind,
        source=source,
        is_synthetic=is_synthetic,
        source_detail=source_detail,
        insertion_rule=insertion_rule,
        row_number=row,
        state=state,
        state_assignment_rule=state_assignment_rule,
        cleanup_rule_applied="",
        drop_reason=None,
        raw_payload={"event_type": event_type},
    )


def test_row_to_next_row_duration_calculation() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:00:10", event_type="SetupUnlockWorkflowRecord", row=2),
        _event(ts="2025-01-01 09:00:25", event_type="AlignmentWorkflowRecord", row=3),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert warnings
    assert [row.duration_sec for row in intervals] == [10.0, 15.0, 0.0]


def test_last_row_duration_defaults_to_zero() -> None:
    intervals, _ = compute_state_intervals(
        [_event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1)]
    )
    assert len(intervals) == 1
    assert intervals[0].duration_sec == 0.0


def test_non_monotonic_input_emits_warning_and_quality_flag() -> None:
    events = [
        _event(ts="2025-01-01 09:01:00", event_type="SetupUnlockWorkflowRecord", row=2),
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:02:00", event_type="AlignmentWorkflowRecord", row=3),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert any("interval_non_monotonic_input" in warning for warning in warnings)
    assert any("non_monotonic_input" in row.quality_flags for row in intervals)


def test_case_end_detection_clean_case_emits_inferred_not_ambiguous() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1, state="Room ready"),
        _event(ts="2025-01-01 09:05:00", event_type="AlignmentWorkflowRecord", row=2, state="Alignment"),
        _event(
            ts="2025-01-01 09:10:00",
            event_type="TransferWorkflowRecord",
            row=3,
            state="Patient recovery & transfer",
        ),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert [row.duration_sec for row in intervals] == [300.0, 300.0, 0.0]
    assert any("case_end_inferred" in warning for warning in warnings)
    assert not any("case_end_ambiguous" in warning for warning in warnings)


def test_case_end_detection_with_trailing_event_marks_ambiguous_and_clamps_terminal() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1, state="Room ready"),
        _event(
            ts="2025-01-01 10:00:00",
            event_type="TransferWorkflowRecord",
            row=2,
            state="Patient recovery & transfer",
        ),
        _event(ts="2025-01-01 20:00:00", event_type="SessionEventRecord", row=3, state=None),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert any("case_end_ambiguous:trailing_events_after_case_end" in warning for warning in warnings)
    terminal_row = intervals[1]
    assert terminal_row.duration_sec == 0.0
    assert "interval_terminal_state_clamped" in terminal_row.quality_flags
    assert "interval_truncated_large_gap" in terminal_row.quality_flags


def test_large_gap_truncation_policy_clamps_to_threshold_for_sparse_gap() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1, state="Room ready"),
        _event(ts="2025-01-01 09:10:00", event_type="AlignmentWorkflowRecord", row=2, state="Alignment"),
        _event(ts="2025-01-01 16:00:00", event_type="SessionEventRecord", row=3, state=None),
    ]
    intervals, _ = compute_state_intervals(events)

    # 6h50m raw gap should be hardened to threshold window (2h).
    hardened = intervals[1]
    assert hardened.duration_sec == 7200.0
    assert "interval_truncated_large_gap" in hardened.quality_flags


def test_unassigned_state_interval_is_truncated_and_flagged() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SessionEventRecord", row=1, state=None),
        _event(ts="2025-01-01 13:00:00", event_type="AlignmentWorkflowRecord", row=2, state="Alignment"),
        _event(ts="2025-01-01 13:10:00", event_type="CoarseWorkflowRecord", row=3, state="Coarse"),
    ]
    intervals, _ = compute_state_intervals(events)

    unassigned = intervals[0]
    assert unassigned.duration_sec == 7200.0
    assert "interval_unassigned_state_truncated" in unassigned.quality_flags
    assert "interval_truncated_large_gap" in unassigned.quality_flags


def test_session_synthetic_large_gap_is_truncated_and_flagged() -> None:
    events = [
        _event(
            ts="2025-01-01 09:00:00",
            event_type="DeviceInsertionEnds",
            row=None,
            state="Device insertion",
            source="sessions",
            is_synthetic=True,
            source_detail="Sessions.TimeUaInsertedAt",
            insertion_rule="session_field_map_v1",
            state_assignment_rule="map_device_insertion",
        ),
        _event(
            ts="2025-01-06 09:00:00",
            event_type="AlignmentWorkflowRecord",
            row=2,
            state="Alignment",
        ),
    ]
    intervals, warnings = compute_state_intervals(events)

    hardened = intervals[0]
    assert hardened.duration_sec == 7200.0
    assert "interval_session_synthetic_truncated" in hardened.quality_flags
    assert "interval_truncated_large_gap" in hardened.quality_flags
    assert any("interval_session_synthetic_truncated" in warning for warning in warnings)


def test_normal_non_outlier_intervals_are_preserved_without_hardening_flags() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1, state="Room ready"),
        _event(ts="2025-01-01 09:20:00", event_type="AlignmentWorkflowRecord", row=2, state="Alignment"),
        _event(ts="2025-01-01 09:35:00", event_type="CoarseWorkflowRecord", row=3, state="Coarse"),
    ]
    intervals, _ = compute_state_intervals(events)

    assert [row.duration_sec for row in intervals] == [1200.0, 900.0, 0.0]
    assert all(
        "interval_truncated_large_gap" not in row.quality_flags
        and "interval_terminal_state_clamped" not in row.quality_flags
        and "interval_unassigned_state_truncated" not in row.quality_flags
        for row in intervals
    )


def test_plotting_still_works_with_hardened_intervals(tmp_path: Path) -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1, state="Room ready"),
        _event(ts="2025-01-01 09:10:00", event_type="AlignmentWorkflowRecord", row=2, state="Alignment"),
        _event(ts="2025-01-01 16:00:00", event_type="SessionEventRecord", row=3, state=None),
    ]
    intervals, _ = compute_state_intervals(events)
    paths, _ = generate_timeline_plots(intervals, tmp_path)

    assert paths["normalized_timeline"].exists()
    assert paths["original_hour_timeline"].exists()


def test_residual_early_state_long_gap_is_truncated() -> None:
    events = [
        _event(
            ts="2025-01-01 07:00:00",
            event_type="FPumpRecord",
            row=1,
            state="Room ready",
            state_assignment_rule="carry_forward_previous_state",
        ),
        _event(
            ts="2025-01-01 10:00:00",
            event_type="SetupWorkflowRecord",
            row=2,
            state="TULSA QA",
            state_assignment_rule="map_setup_workflow",
        ),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert intervals[0].duration_sec == 7200.0
    assert "interval_early_state_truncated" in intervals[0].quality_flags
    assert "interval_truncated_large_gap" in intervals[0].quality_flags
    assert any("interval_early_state_truncated" in warning for warning in warnings)


def test_plausible_early_state_duration_is_preserved() -> None:
    events = [
        _event(
            ts="2025-01-01 07:00:00",
            event_type="FPumpRecord",
            row=1,
            state="Room ready",
            state_assignment_rule="carry_forward_previous_state",
        ),
        _event(
            ts="2025-01-01 08:15:00",
            event_type="SetupWorkflowRecord",
            row=2,
            state="TULSA QA",
            state_assignment_rule="map_setup_workflow",
        ),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert intervals[0].duration_sec == 4500.0
    assert "interval_early_state_truncated" not in intervals[0].quality_flags
    assert not any("interval_early_state_truncated" in warning for warning in warnings)


def test_anchor_selection_prefers_initial_imaging_when_eligible() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:01:00", event_type="PSTestRecord", row=2),
        _event(ts="2025-01-01 09:02:00", event_type="PSHomingRecord", row=3),
        _event(ts="2025-01-01 09:03:00", event_type="InitialImaging", row=4),
        _event(ts="2025-01-01 09:05:00", event_type="AlignmentWorkflowRecord", row=5),
    ]
    intervals, _ = compute_state_intervals(events)

    assert all(row.rebase_anchor == "InitialImaging" for row in intervals)
    anchor_row = next(row for row in intervals if row.origin_event_type == "InitialImaging")
    assert anchor_row.start_sec == 0.0


def test_anchor_selection_uses_last_uahoming_when_initial_imaging_missing() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:01:00", event_type="PSTestRecord", row=2),
        _event(ts="2025-01-01 09:02:00", event_type="PSHomingRecord", row=3),
        _event(ts="2025-01-01 09:04:00", event_type="AlignmentWorkflowRecord", row=4),
    ]
    intervals, _ = compute_state_intervals(events)

    assert all(row.rebase_anchor == "LastUAHoming" for row in intervals)
    anchor_row = next(row for row in intervals if row.origin_event_type == "PSHomingRecord")
    assert anchor_row.start_sec == 0.0


def test_anchor_fallback_when_alignment_missing_is_explicit() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:02:00", event_type="InitialImaging", row=2),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert all(row.rebase_anchor == "InitialImaging" for row in intervals)
    assert any("rebase_missing_alignment" in warning for warning in warnings)


def test_rebased_start_seconds_and_negative_start_flags() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:02:00", event_type="AlignmentWorkflowRecord", row=2),
        _event(ts="2025-01-01 09:03:00", event_type="CoarseWorkflowRecord", row=3),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert [row.start_sec for row in intervals] == [-120.0, 0.0, 60.0]
    assert "negative_rebased_start" in intervals[0].quality_flags
    assert "negative_rebased_start_expected_pre_anchor" in intervals[0].quality_flags
    assert not any("interval_negative_rebased_start" in warning for warning in warnings)


def test_extreme_negative_rebased_start_still_warns() -> None:
    events = [
        _event(ts="2025-01-01 00:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 08:00:00", event_type="AlignmentWorkflowRecord", row=2),
    ]
    intervals, warnings = compute_state_intervals(events)

    assert intervals[0].start_sec == -28800.0
    assert "negative_rebased_start" in intervals[0].quality_flags
    assert any("interval_negative_rebased_start" in warning for warning in warnings)


def test_state_interval_export_schema_content(tmp_path: Path) -> None:
    intervals, _ = compute_state_intervals(
        [
            _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
            _event(ts="2025-01-01 09:01:00", event_type="AlignmentWorkflowRecord", row=2),
        ]
    )
    out_path = write_state_intervals_csv(
        case_id="064_01-001",
        state_intervals=intervals,
        output_dir=tmp_path,
    )

    with out_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    expected = {
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
        "raw_payload_json",
    }
    assert expected.issubset(set(rows[0].keys()))


def test_interval_computation_input_immutability() -> None:
    events = [
        _event(ts="2025-01-01 09:00:00", event_type="SetupWorkflowRecord", row=1),
        _event(ts="2025-01-01 09:02:00", event_type="AlignmentWorkflowRecord", row=2),
    ]
    snapshot = deepcopy(events)
    compute_state_intervals(events)
    assert events == snapshot


def test_cli_generates_state_intervals_artifact_and_timing_warnings(tmp_path: Path) -> None:
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

    layout = output_layout(output_dir)
    interval_path = layout.state_intervals_dir / "064_01-001_state_intervals.csv"
    assert interval_path.exists()

    processed_cases = [case for case in manifest.case_results if case.get("status") == "processed"]
    assert len(processed_cases) == 1
    case_meta = processed_cases[0]
    assert int(case_meta["state_interval_count"]) >= 1
    assert int(case_meta["timing_warning_count"]) >= 1
    assert any("case_end_inferred" in warning for warning in case_meta["timing_warnings"])
    assert any("case_end_inferred" in warning for warning in manifest.warnings)

    payload = json.loads(layout.run_manifest_path.read_text(encoding="utf-8"))
    payload_processed = [row for row in payload["case_results"] if row.get("status") == "processed"]
    assert len(payload_processed) == 1
    assert "state_interval_export" in payload_processed[0]
