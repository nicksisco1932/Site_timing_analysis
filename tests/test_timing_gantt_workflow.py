from __future__ import annotations

from pathlib import Path

import pandas as pd

from site_timing_analysis.tulsa_plot_timing import (
    plot_gantt_from_states,
    prepare_gantt_rows,
)
from site_timing_analysis.tulsa_site_pipeline import (
    build_timing_gantt_output_dir_name,
)


def _states_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "PtId": "CASE_A",
                "CurrentState": "Room ready",
                "start_sec": 0.0,
                "duration_sec": 600.0,
            },
            {
                "PtId": "CASE_A",
                "CurrentState": "Device insertion",
                "start_sec": 600.0,
                "duration_sec": 180.0,
            },
            {
                "PtId": "CASE_A",
                "CurrentState": "Alignment",
                "start_sec": 780.0,
                "duration_sec": 120.0,
            },
            {
                "PtId": "CASE_B",
                "CurrentState": "Room ready",
                "start_sec": 0.0,
                "duration_sec": 300.0,
            },
            {
                "PtId": "CASE_B",
                "CurrentState": "Alignment",
                "start_sec": 300.0,
                "duration_sec": 120.0,
            },
        ]
    )


def test_build_timing_gantt_output_dir_name_normalizes_date_formats() -> None:
    expected = "2025.11.19_Stanford_064_timing_Gantt"
    assert build_timing_gantt_output_dir_name("Stanford_064", "20251119") == expected
    assert build_timing_gantt_output_dir_name("Stanford_064", "2025.11.19") == expected


def test_prepare_gantt_rows_rebases_device_insertion_and_skips_missing_cases() -> None:
    prepared = prepare_gantt_rows(_states_df())

    assert prepared.plotted_pts == ["CASE_A"]
    assert prepared.skipped_pts == ["CASE_B"]

    insertion = prepared.rows[prepared.rows["CurrentState"] == "Device insertion"].iloc[0]
    room_ready = prepared.rows[prepared.rows["CurrentState"] == "Room ready"].iloc[0]

    assert insertion["start_min"] == 0.0
    assert room_ready["start_min"] < 0.0


def test_plot_gantt_from_states_saves_plot_and_reports_skipped_cases(
    tmp_path: Path, capsys
) -> None:
    result = plot_gantt_from_states(_states_df(), tmp_path, "TESTSITE")

    assert result == {"plotted_pts": ["CASE_A"], "skipped_pts": ["CASE_B"]}
    assert (tmp_path / "gantt_all_patients.png").exists()

    captured = capsys.readouterr()
    assert "Skipping cases without Device insertion" in captured.out
    assert "CASE_B" in captured.out
    assert "Normalized Gantt cases plotted: CASE_A" in captured.out
