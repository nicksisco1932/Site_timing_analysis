# Project: Site Timing Analysis
# File: testing/tests/test_timing_gantt_deliverables.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: Unknown
# Purpose: Tests timing gantt deliverables behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
from pathlib import Path

from site_timing_analysis.timing_gantt_deliverables import (
    CANONICAL_RUN_NAME,
    RunAudit,
    assign_chronology_groups,
    balanced_group_sizes,
    build_all_deliverables,
    build_run_deliverables,
)


def _write_interval_file(
    run_dir: Path,
    *,
    case_id: str,
    date_text: str,
    duration_offset: int,
) -> None:
    intervals_dir = run_dir / "state_intervals"
    intervals_dir.mkdir(parents=True, exist_ok=True)
    path = intervals_dir / f"{case_id}_state_intervals.csv"
    fieldnames = [
        "case_id",
        "timestamp",
        "state",
        "start_sec",
        "duration_sec",
        "rebase_anchor",
        "quality_flags",
    ]
    rows = [
        {
            "case_id": case_id,
            "timestamp": f"{date_text}T08:00:00",
            "state": "Room ready",
            "start_sec": "0",
            "duration_sec": str(600 + duration_offset),
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": case_id,
            "timestamp": f"{date_text}T08:10:00",
            "state": "Device insertion",
            "start_sec": "600",
            "duration_sec": "300",
            "rebase_anchor": "Device insertion",
            "quality_flags": "negative_rebased_start",
        },
        {
            "case_id": case_id,
            "timestamp": f"{date_text}T08:15:00",
            "state": "Alignment",
            "start_sec": "900",
            "duration_sec": "1200",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": case_id,
            "timestamp": f"{date_text}T08:35:00",
            "state": "Treating",
            "start_sec": "2100",
            "duration_sec": "1800",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": case_id,
            "timestamp": f"{date_text}T09:05:00",
            "state": "Patient recovery & transfer",
            "start_sec": "3900",
            "duration_sec": "900",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_fragmented_interval_file(run_dir: Path) -> None:
    intervals_dir = run_dir / "state_intervals"
    intervals_dir.mkdir(parents=True, exist_ok=True)
    path = intervals_dir / "122_01-001_state_intervals.csv"
    fieldnames = [
        "case_id",
        "timestamp",
        "state",
        "start_sec",
        "duration_sec",
        "rebase_anchor",
        "quality_flags",
    ]
    rows = [
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:00:00",
            "state": "Room ready",
            "start_sec": "-600",
            "duration_sec": "600",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:10:00",
            "state": "Device insertion",
            "start_sec": "0",
            "duration_sec": "300",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:20:00",
            "state": "Treating",
            "start_sec": "600",
            "duration_sec": "60",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:21:00",
            "state": "Treating",
            "start_sec": "660",
            "duration_sec": "60",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:22:00",
            "state": "Treating",
            "start_sec": "719.99998",
            "duration_sec": "60",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:22:40",
            "state": "Treating",
            "start_sec": "760",
            "duration_sec": "60",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
        {
            "case_id": "122_01-001",
            "timestamp": "2026-02-01T08:25:00",
            "state": "Treating",
            "start_sec": "900",
            "duration_sec": "60",
            "rebase_anchor": "Device insertion",
            "quality_flags": "",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_balanced_group_sizes_match_expected_site_counts() -> None:
    assert balanced_group_sizes(9) == [3, 3, 3]
    assert balanced_group_sizes(29) == [10, 10, 9]
    assert balanced_group_sizes(79) == [26, 26, 27]
    assert balanced_group_sizes(135) == [45, 45, 45]


def test_assign_chronology_groups_uses_case_dates() -> None:
    case_dates = {
        "CASE_003": "2026-01-03",
        "CASE_001": "2026-01-01",
        "CASE_002": "2026-01-02",
        "CASE_005": "2026-01-05",
        "CASE_004": "2026-01-04",
    }

    groups = assign_chronology_groups(list(case_dates), case_dates)

    assert groups["CASE_001"] == "Early"
    assert groups["CASE_002"] == "Early"
    assert groups["CASE_003"] == "Middle"
    assert groups["CASE_004"] == "Middle"
    assert groups["CASE_005"] == "Late"


def test_build_run_deliverables_writes_final_tables_and_plots(tmp_path: Path) -> None:
    run_dir = tmp_path / "2026.03.20_UCSD_109_timing_Gantt"
    for index in range(1, 6):
        _write_interval_file(
            run_dir,
            case_id=f"109_01-{index:03d}",
            date_text=f"2026-01-0{index}",
            duration_offset=index * 60,
        )
    audit = RunAudit(
        run_name=CANONICAL_RUN_NAME,
        run_dir=run_dir,
        site_id="UCSD_109",
        status="canonical",
        reason="test",
        interval_file_count=5,
        case_count=5,
        final_dir=run_dir / "final",
    )

    result = build_run_deliverables(audit, repo_root=tmp_path)

    assert result.group_sizes == [2, 2, 1]
    assert result.workflow_tertiles_png.exists()
    assert result.workflow_tertiles_csv.exists()
    assert result.operational_state_segments_csv.exists()
    assert result.operational_state_summary_by_case_csv.exists()
    assert result.operational_state_summary_by_group_csv.exists()
    assert result.data_dictionary_csv.exists()
    assert result.normalized_timeline_segments_csv.exists()
    assert result.original_hour_timeline_segments_csv.exists()
    assert result.normalized_timeline_case_index_csv.exists()
    assert result.original_hour_timeline_case_index_csv.exists()
    assert result.timeline_legend_csv.exists()
    assert result.normalized_timeline_state_runs_csv.exists()
    assert result.original_hour_timeline_state_runs_csv.exists()
    assert result.normalized_timeline_state_summary_long_csv.exists()
    assert result.original_hour_timeline_state_summary_long_csv.exists()
    assert result.normalized_timeline_state_summary_wide_csv.exists()
    assert result.original_hour_timeline_state_summary_wide_csv.exists()

    with result.operational_state_summary_by_case_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    first = rows[0]
    phase_sum = (
        float(first["pre_op_min"])
        + float(first["device_insertion_min"])
        + float(first["planning_min"])
        + float(first["ablation_min"])
        + float(first["post_op_min"])
    )
    assert float(first["total_time_min"]) == round(phase_sum, 1)

    with result.normalized_timeline_segments_csv.open("r", encoding="utf-8", newline="") as handle:
        normalized_rows = list(csv.DictReader(handle))
    assert normalized_rows
    assert normalized_rows[0]["plot_type"] == "normalized_timeline"
    first_device = next(row for row in normalized_rows if row["operational_state"] == "Device insertion")
    assert float(first_device["start_plot_x"]) == 0.0
    assert float(first_device["duration_plot_units"]) == 5.0

    with result.original_hour_timeline_segments_csv.open("r", encoding="utf-8", newline="") as handle:
        original_rows = list(csv.DictReader(handle))
    assert original_rows
    assert original_rows[0]["plot_type"] == "original_hour_timeline"
    assert float(original_rows[0]["start_plot_x"]) == 480.0

    with result.normalized_timeline_case_index_csv.open("r", encoding="utf-8", newline="") as handle:
        normalized_index = list(csv.DictReader(handle))
    assert len(normalized_index) == 5
    assert [int(row["case_order"]) for row in normalized_index] == list(range(5))

    with result.timeline_legend_csv.open("r", encoding="utf-8", newline="") as handle:
        legend_rows = list(csv.DictReader(handle))
    legend_labels = {row["display_state"] for row in legend_rows}
    assert {"Room ready", "Device insertion", "Alignment", "Treating", "Patient recovery & transfer"}.issubset(
        legend_labels
    )


def test_timeline_state_tables_coalesce_visual_runs_and_sum_from_state_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "2026.03.19_ASUI_122_timing_Gantt"
    _write_fragmented_interval_file(run_dir)
    audit = RunAudit(
        run_name="2026.03.19_ASUI_122_timing_Gantt",
        run_dir=run_dir,
        site_id="ASUI_122",
        status="retained",
        reason="test",
        interval_file_count=1,
        case_count=1,
        final_dir=run_dir / "final",
    )

    result = build_run_deliverables(audit, repo_root=tmp_path)

    with result.normalized_timeline_segments_csv.open("r", encoding="utf-8", newline="") as handle:
        raw_segments = list(csv.DictReader(handle))
    with result.normalized_timeline_state_runs_csv.open("r", encoding="utf-8", newline="") as handle:
        state_runs = list(csv.DictReader(handle))
    with result.normalized_timeline_state_summary_long_csv.open("r", encoding="utf-8", newline="") as handle:
        long_rows = list(csv.DictReader(handle))
    with result.normalized_timeline_state_summary_wide_csv.open("r", encoding="utf-8", newline="") as handle:
        wide_rows = list(csv.DictReader(handle))

    treating_segments = [row for row in raw_segments if row["display_state"] == "Treating"]
    treating_runs = [row for row in state_runs if row["display_state"] == "Treating"]
    treating_long = next(row for row in long_rows if row["display_state"] == "Treating")

    assert len(treating_segments) == 5
    assert len(treating_runs) == 2
    assert treating_runs[0]["segment_count_collapsed"] == "4"
    assert treating_runs[0]["overlap_detected"] == "True"
    assert float(treating_runs[0]["duration_min"]) == round((820 - 600) / 60, 6)
    assert float(treating_runs[1]["duration_min"]) == 1.0
    assert treating_long["state_run_count"] == "2"
    assert treating_long["raw_segment_count"] == "5"
    assert float(treating_long["state_total_duration_min"]) == round((820 - 600) / 60 + 1.0, 6)

    assert len(wide_rows) == 1
    wide = wide_rows[0]
    assert wide["treating_min"] == "4.7"
    state_columns = [
        column
        for column in wide
        if column
        not in {
            "site_id",
            "case_id",
            "case_date",
            "case_order",
            "plot_type",
            "row_label",
            "chronology_group",
            "source_run",
            "total_time_min",
        }
    ]
    assert float(wide["total_time_min"]) == round(sum(float(wide[column]) for column in state_columns), 1)

    overlap_checks = [
        check
        for check in result.validation_checks
        if check["check"] == "normalized_timeline_state_run_overlap_check"
    ]
    assert overlap_checks and overlap_checks[0]["status"] == "WARN"


def test_build_all_deliverables_marks_superseded_ucsd(tmp_path: Path) -> None:
    timing_root = tmp_path / "outputs" / "timing_gantt"
    canonical = timing_root / "2026.03.20_UCSD_109_timing_Gantt"
    superseded = timing_root / "2026.03.19_UCSD_109_timing_Gantt"
    retained = timing_root / "2026.03.19_ASUI_122_timing_Gantt"
    for run_dir, site_prefix in [(canonical, "109"), (superseded, "109"), (retained, "122")]:
        for index in range(1, 4):
            _write_interval_file(
                run_dir,
                case_id=f"{site_prefix}_01-{index:03d}",
                date_text=f"2026-02-0{index}",
                duration_offset=index,
            )

    audits, deliverables = build_all_deliverables(timing_root, repo_root=tmp_path)

    audit_by_run = {audit.run_name: audit for audit in audits}
    assert audit_by_run["2026.03.19_UCSD_109_timing_Gantt"].status == "superseded"
    assert {item.run_name for item in deliverables} == {
        "2026.03.20_UCSD_109_timing_Gantt",
        "2026.03.19_ASUI_122_timing_Gantt",
    }
    assert (timing_root / "final_index.csv").exists()
    assert (timing_root / "audit_report.md").exists()
    assert (timing_root / "validation_summary.md").exists()
    assert (canonical / "final" / "plot_data" / "normalized_timeline_segments.csv").exists()
    assert (retained / "final" / "plot_data" / "original_hour_timeline_segments.csv").exists()
    assert (canonical / "final" / "plot_data" / "normalized_timeline_state_summary_wide.csv").exists()
    assert (retained / "final" / "plot_data" / "original_hour_timeline_state_runs.csv").exists()
    assert not (superseded / "final" / "plot_data").exists()
