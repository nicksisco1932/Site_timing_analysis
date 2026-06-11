from __future__ import annotations

import csv
import shutil
from pathlib import Path

from site_timing_analysis.output_layout import output_layout
from site_timing_analysis.plot_tables import export_plot_tables


def test_export_plot_tables_matches_plot_row_filtering() -> None:
    run_dir = Path("outputs/_tmp_plot_tables_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    layout = output_layout(run_dir)
    state_intervals_dir = layout.state_intervals_dir
    state_intervals_dir.mkdir(parents=True, exist_ok=True)

    try:
        interval_path = state_intervals_dir / "CASE_001_state_intervals.csv"
        with interval_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
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
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "case_id": "CASE_001",
                    "timestamp": "2025-01-01T09:00:00",
                    "state": "Room ready",
                    "start_sec": "0.0",
                    "duration_sec": "120.0",
                    "rebase_anchor": "Alignment",
                    "origin_event_type": "SetupWorkflowRecord",
                    "source": "auditlog",
                    "is_synthetic": "False",
                    "source_detail": "normalized_audit_event",
                    "row_number": "1",
                    "state_assignment_rule": "test_rule",
                    "cleanup_rule_applied": "",
                    "quality_flags": "",
                    "segment_id": "SEG-1",
                    "event_kind": "1",
                    "drop_reason": "",
                    "insertion_rule": "",
                    "raw_payload_json": "{}",
                }
            )
            writer.writerow(
                {
                    "case_id": "CASE_001",
                    "timestamp": "2025-01-01T09:02:00",
                    "state": "",
                    "start_sec": "120.0",
                    "duration_sec": "60.0",
                    "rebase_anchor": "Alignment",
                    "origin_event_type": "SetupWorkflowRecord",
                    "source": "auditlog",
                    "is_synthetic": "False",
                    "source_detail": "normalized_audit_event",
                    "row_number": "2",
                    "state_assignment_rule": "test_rule",
                    "cleanup_rule_applied": "",
                    "quality_flags": "",
                    "segment_id": "SEG-1",
                    "event_kind": "1",
                    "drop_reason": "",
                    "insertion_rule": "",
                    "raw_payload_json": "{}",
                }
            )
            writer.writerow(
                {
                    "case_id": "CASE_001",
                    "timestamp": "2025-01-01T09:03:00",
                    "state": "Alignment",
                    "start_sec": "180.0",
                    "duration_sec": "0.0",
                    "rebase_anchor": "Alignment",
                    "origin_event_type": "AlignmentWorkflowRecord",
                    "source": "auditlog",
                    "is_synthetic": "False",
                    "source_detail": "normalized_audit_event",
                    "row_number": "3",
                    "state_assignment_rule": "test_rule",
                    "cleanup_rule_applied": "",
                    "quality_flags": "",
                    "segment_id": "SEG-1",
                    "event_kind": "1",
                    "drop_reason": "",
                    "insertion_rule": "",
                    "raw_payload_json": "{}",
                }
            )

        per_segment_path, summary_path = export_plot_tables(run_dir)

        with per_segment_path.open("r", encoding="utf-8", newline="") as handle:
            segment_rows = list(csv.DictReader(handle))
        assert segment_rows == [
            {
                "case_id": "CASE_001",
                "state": "Room ready",
                "start_sec": "0.000000",
                "end_sec": "120.000000",
                "duration_min": "2.000000",
            }
        ]

        with summary_path.open("r", encoding="utf-8", newline="") as handle:
            summary_rows = list(csv.DictReader(handle))
        assert summary_rows == [
            {
                "case_id": "CASE_001",
                "Room ready": "2.000000",
                "total_time": "2.000000",
            }
        ]
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
