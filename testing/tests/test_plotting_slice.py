# Project: Site Timing Analysis
# File: testing/tests/test_plotting_slice.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Tests plotting slice behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import json
import shutil
import sqlite3
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from site_timing_analysis.first_slice_cli import run_first_slice
from site_timing_analysis.models import StateInterval
from site_timing_analysis.output_layout import output_layout
from site_timing_analysis.plotting import (
    STATE_COLOR_MAP,
    STATE_DISPLAY_ORDER,
    choose_tick_spacing_minutes,
    compute_normalized_axis_window_seconds,
    generate_timeline_plots,
    get_plot_output_paths,
    minutes_to_hhmm_label,
    minutes_since_midnight,
    prepare_device_insertion_normalized_rows,
    prepare_plot_rows,
    seconds_to_minutes,
)


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
    case_id: str = "064_01-001",
    ts: str,
    state: str | None,
    start_sec: float,
    duration_sec: float,
    row: int,
    quality_flags: list[str] | None = None,
) -> StateInterval:
    return StateInterval(
        case_id=case_id,
        timestamp=datetime.fromisoformat(ts),
        state=state,
        start_sec=start_sec,
        duration_sec=duration_sec,
        rebase_anchor="Alignment",
        origin_event_type="SetupWorkflowRecord",
        source="auditlog",
        is_synthetic=False,
        source_detail="normalized_audit_event",
        row_number=row,
        state_assignment_rule="test_rule",
        cleanup_rule_applied="",
        quality_flags=list(quality_flags or []),
    )


def test_normalized_plot_artifact_generation(tmp_path: Path) -> None:
    intervals = [
        _interval(ts="2025-01-01 09:00:00", state="Room ready", start_sec=0.0, duration_sec=60.0, row=1),
        _interval(ts="2025-01-01 09:01:00", state="Alignment", start_sec=60.0, duration_sec=120.0, row=2),
    ]

    paths, warnings = generate_timeline_plots(intervals, tmp_path)
    assert paths["normalized_timeline"].exists()
    assert "plot:no_plottable_rows" not in warnings


def test_original_hour_plot_artifact_generation(tmp_path: Path) -> None:
    intervals = [
        _interval(ts="2025-01-01 10:00:00", state="Room ready", start_sec=0.0, duration_sec=300.0, row=1),
        _interval(ts="2025-01-01 10:05:00", state="Alignment", start_sec=300.0, duration_sec=60.0, row=2),
    ]

    paths, _ = generate_timeline_plots(intervals, tmp_path)
    assert paths["original_hour_timeline"].exists()


def test_canonical_state_order_appends_unknown_state_with_warning() -> None:
    intervals = [
        _interval(ts="2025-01-01 09:00:00", state="Treating", start_sec=0.0, duration_sec=30.0, row=1),
        _interval(ts="2025-01-01 09:01:00", state="CustomStateX", start_sec=30.0, duration_sec=30.0, row=2),
    ]
    prepared = prepare_plot_rows(intervals)

    assert prepared.state_order[-1] == "CustomStateX"
    assert "Treating" in prepared.state_order
    assert any("plot_unknown_state_appended:CustomStateX" in warning for warning in prepared.warnings)


def test_canonical_color_map_covers_required_states() -> None:
    required = set(STATE_DISPLAY_ORDER)
    assert required.issubset(set(STATE_COLOR_MAP.keys()))


def test_seconds_to_minutes_conversion() -> None:
    assert seconds_to_minutes(0.0) == 0.0
    assert seconds_to_minutes(60.0) == 1.0
    assert seconds_to_minutes(150.0) == 2.5


def test_minutes_since_midnight_conversion() -> None:
    ts = datetime.fromisoformat("2025-01-01 10:05:30")
    assert minutes_since_midnight(ts) == 605.5


def test_minutes_to_hhmm_label_conversion() -> None:
    assert minutes_to_hhmm_label(0) == "00:00"
    assert minutes_to_hhmm_label(30) == "00:30"
    assert minutes_to_hhmm_label(65) == "01:05"
    assert minutes_to_hhmm_label(1445) == "00:05"


def test_choose_tick_spacing_minutes() -> None:
    assert choose_tick_spacing_minutes(0, 180) == 30
    assert choose_tick_spacing_minutes(0, 720) == 60


def test_empty_state_rows_are_excluded_with_warning() -> None:
    intervals = [
        _interval(ts="2025-01-01 09:00:00", state="", start_sec=0.0, duration_sec=10.0, row=1),
        _interval(ts="2025-01-01 09:00:10", state=None, start_sec=10.0, duration_sec=10.0, row=2),
        _interval(ts="2025-01-01 09:00:20", state="Coarse", start_sec=20.0, duration_sec=10.0, row=3),
    ]
    prepared = prepare_plot_rows(intervals)

    assert len(prepared.rows) == 1
    assert prepared.rows[0].state == "Coarse"
    assert sum("plot_excluded_empty_state" in warning for warning in prepared.warnings) == 2


def test_zero_duration_rows_are_excluded_with_warning() -> None:
    intervals = [
        _interval(ts="2025-01-01 09:00:00", state="Coarse", start_sec=0.0, duration_sec=0.0, row=1),
        _interval(ts="2025-01-01 09:00:30", state="Detailed", start_sec=30.0, duration_sec=15.0, row=2),
    ]
    prepared = prepare_plot_rows(intervals)

    assert len(prepared.rows) == 1
    assert prepared.rows[0].state == "Detailed"
    assert any("plot_excluded_nonpositive_duration" in warning for warning in prepared.warnings)


def test_device_insertion_normalized_rows_preserve_device_insertion_anchor() -> None:
    intervals = [
        _interval(case_id="064_01-001", ts="2025-01-01 09:00:00", state="Room ready", start_sec=-120.0, duration_sec=60.0, row=1),
        _interval(case_id="064_01-001", ts="2025-01-01 09:02:00", state="Device insertion", start_sec=-60.0, duration_sec=30.0, row=2),
        _interval(case_id="064_01-001", ts="2025-01-01 09:03:00", state="Alignment", start_sec=0.0, duration_sec=45.0, row=3),
        _interval(case_id="064_01-002", ts="2025-01-01 10:00:00", state="Room ready", start_sec=0.0, duration_sec=30.0, row=4),
    ]

    prepared = prepare_plot_rows(intervals)
    normalized_rows, normalized_case_order, warnings = prepare_device_insertion_normalized_rows(prepared)

    assert normalized_case_order == ["064_01-001"]
    assert any("064_01-001:plot_normalized_anchor_used:Device insertion" in warning for warning in warnings)
    assert any("064_01-002:plot_skipped_missing_normalized_anchor" == warning for warning in warnings)

    insertion = [row for row in normalized_rows if row.state == "Device insertion"]
    room_ready = [row for row in normalized_rows if row.state == "Room ready"]
    assert len(insertion) == 1
    assert insertion[0].start_sec == 0.0
    assert room_ready[0].start_sec < 0.0


def test_device_insertion_normalized_rows_fallback_to_alignment_when_insertion_is_implausible() -> None:
    intervals = [
        _interval(case_id="109_01-021", ts="2026-01-20 08:56:39", state="Alignment", start_sec=1390.128311, duration_sec=300.0, row=1),
        _interval(case_id="109_01-021", ts="2026-01-20 09:25:00", state="Coarse", start_sec=3100.0, duration_sec=300.0, row=2),
        _interval(case_id="109_01-021", ts="2026-01-20 10:30:00", state="Treating", start_sec=7000.0, duration_sec=600.0, row=3),
        _interval(
            case_id="109_01-021",
            ts="2026-01-20 11:45:00",
            state="Post-treatment scans & Device removal",
            start_sec=11500.0,
            duration_sec=600.0,
            row=4,
        ),
        _interval(
            case_id="109_01-021",
            ts="2026-01-20 20:27:53",
            state="Device insertion",
            start_sec=42864.0624,
            duration_sec=7200.0,
            row=5,
        ),
    ]

    prepared = prepare_plot_rows(intervals)
    normalized_rows, normalized_case_order, warnings = prepare_device_insertion_normalized_rows(prepared)

    assert normalized_case_order == ["109_01-021"]
    assert any(
        "109_01-021:plot_normalized_anchor_rejected:Device insertion:reason=after_end_marker"
        in warning
        for warning in warnings
    )
    assert any("109_01-021:plot_normalized_anchor_used:Alignment" in warning for warning in warnings)

    alignment = [row for row in normalized_rows if row.state == "Alignment"][0]
    coarse = [row for row in normalized_rows if row.state == "Coarse"][0]
    assert alignment.start_sec == 0.0
    assert coarse.start_sec > 0.0


def test_device_insertion_normalized_rows_keep_primary_anchor_for_nearby_normal_cases() -> None:
    intervals = [
        _interval(case_id="109_01-020", ts="2025-12-19 12:40:00", state="Room ready", start_sec=-900.0, duration_sec=60.0, row=1),
        _interval(case_id="109_01-020", ts="2025-12-19 12:50:29", state="Device insertion", start_sec=-637.779617, duration_sec=505.767, row=2),
        _interval(case_id="109_01-020", ts="2025-12-19 13:01:06", state="Alignment", start_sec=0.0, duration_sec=120.0, row=3),
        _interval(case_id="109_01-022", ts="2026-01-20 13:30:00", state="Room ready", start_sec=-900.0, duration_sec=60.0, row=4),
        _interval(case_id="109_01-022", ts="2026-01-20 13:40:53", state="Device insertion", start_sec=-607.727122, duration_sec=607.727, row=5),
        _interval(case_id="109_01-022", ts="2026-01-20 13:51:00", state="Alignment", start_sec=0.0, duration_sec=120.0, row=6),
    ]

    prepared = prepare_plot_rows(intervals)
    normalized_rows, normalized_case_order, warnings = prepare_device_insertion_normalized_rows(prepared)

    assert normalized_case_order == ["109_01-020", "109_01-022"]
    assert sum("plot_normalized_anchor_used:Device insertion" in warning for warning in warnings) == 2

    for case_id in normalized_case_order:
        insertion_rows = [row for row in normalized_rows if row.case_id == case_id and row.state == "Device insertion"]
        assert len(insertion_rows) == 1
        assert insertion_rows[0].start_sec == 0.0


def test_midnight_crossing_emits_original_hour_warning(tmp_path: Path) -> None:
    intervals = [
        _interval(ts="2025-01-01 23:50:00", state="Room ready", start_sec=0.0, duration_sec=1200.0, row=1),
        _interval(ts="2025-01-02 00:10:00", state="Alignment", start_sec=1200.0, duration_sec=60.0, row=2),
    ]
    _, warnings = generate_timeline_plots(intervals, tmp_path)
    assert any("plot_original_hour_crosses_midnight" in warning for warning in warnings)


def test_plot_output_paths_are_deterministic(tmp_path: Path) -> None:
    first = get_plot_output_paths(tmp_path)
    second = get_plot_output_paths(tmp_path)
    assert first == second
    assert first["normalized_timeline"].name == "normalized_timeline.png"
    assert first["original_hour_timeline"].name == "original_hour_timeline.png"


def test_plot_generation_does_not_mutate_intervals(tmp_path: Path) -> None:
    intervals = [
        _interval(
            ts="2025-01-01 09:00:00",
            state="Coarse",
            start_sec=0.0,
            duration_sec=60.0,
            row=1,
            quality_flags=["non_monotonic_input"],
        )
    ]
    snapshot = deepcopy(intervals)
    generate_timeline_plots(intervals, tmp_path)
    assert intervals == snapshot


def test_normalized_axis_window_uses_percentiles_and_margin() -> None:
    intervals = [
        _interval(
            ts=f"2025-01-01 09:00:{idx % 60:02d}",
            state="Room ready",
            start_sec=float(idx),
            duration_sec=10.0,
            row=idx + 1,
        )
        for idx in range(200)
    ]
    intervals.append(
        _interval(
            ts="2025-01-01 10:00:00",
            state="Room ready",
            start_sec=1_000_000.0,
            duration_sec=100.0,
            row=9999,
        )
    )

    prepared = prepare_plot_rows(intervals)
    axis_window = compute_normalized_axis_window_seconds(prepared.rows)
    assert axis_window is not None
    min_sec, max_sec = axis_window

    # The 1st/99th percentile window should not expand to the extreme outlier.
    assert max_sec < 10_000.0
    assert min_sec < 0.0


def test_normalized_axis_window_is_deterministic() -> None:
    intervals = [
        _interval(ts="2025-01-01 09:00:00", state="Room ready", start_sec=0.0, duration_sec=30.0, row=1),
        _interval(ts="2025-01-01 09:01:00", state="Alignment", start_sec=60.0, duration_sec=45.0, row=2),
        _interval(ts="2025-01-01 09:02:00", state="Coarse", start_sec=120.0, duration_sec=30.0, row=3),
    ]
    prepared = prepare_plot_rows(intervals)
    first = compute_normalized_axis_window_seconds(prepared.rows)
    second = compute_normalized_axis_window_seconds(prepared.rows)
    assert first == second


def test_cli_generates_plot_artifacts_and_captures_plot_warnings(tmp_path: Path) -> None:
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
            "VALUES ('2025-01-01 23:50:00.0000000', 'SetupWorkflowRecord', 'SEG-1', 1)",
            "INSERT INTO AuditLogRecords (TimeStamp, AuditRecordBase_Type, SegmentId, EventKind) "
            "VALUES ('2025-01-02 00:10:00.0000000', 'AlignmentWorkflowRecord', 'SEG-1', 1)",
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
    normalized_plot = layout.timeline_plots_dir / "normalized_timeline.png"
    original_plot = layout.timeline_plots_dir / "original_hour_timeline.png"
    assert normalized_plot.exists()
    assert original_plot.exists()

    processed_cases = [case for case in manifest.case_results if case.get("status") == "processed"]
    assert len(processed_cases) == 1
    case_meta = processed_cases[0]
    assert int(case_meta["plot_warning_count"]) >= 1
    assert any("plot_original_hour_crosses_midnight" in warning for warning in case_meta["plot_warnings"])
    assert any("plot_original_hour_crosses_midnight" in warning for warning in manifest.warnings)

    payload = json.loads(layout.run_manifest_path.read_text(encoding="utf-8"))
    payload_processed = [row for row in payload["case_results"] if row.get("status") == "processed"]
    assert len(payload_processed) == 1
    assert "normalized_timeline_plot" in payload_processed[0]
    assert "original_hour_timeline_plot" in payload_processed[0]


def test_normalized_plot_warnings_include_fallback_anchor_usage() -> None:
    intervals = [
        _interval(case_id="064_01-001", ts="2025-01-01 09:00:00", state="Device insertion", start_sec=0.0, duration_sec=30.0, row=1),
        _interval(case_id="064_01-002", ts="2025-01-01 09:00:00", state="Alignment", start_sec=0.0, duration_sec=30.0, row=2),
    ]

    output_dir = Path("outputs/_tmp_plot_fallback_warning_test")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        _, warnings = generate_timeline_plots(intervals, output_dir)
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)

    assert any("064_01-001:plot_normalized_anchor_used:Device insertion" in warning for warning in warnings)
    assert any("064_01-002:plot_normalized_anchor_used:Alignment" in warning for warning in warnings)
    assert not any("064_01-002:plot_skipped_missing_normalized_anchor" == warning for warning in warnings)
