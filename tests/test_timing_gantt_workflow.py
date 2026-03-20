from __future__ import annotations

from pathlib import Path

import pandas as pd

from site_timing_analysis.tulsa_plot_timing import (
    plot_gantt_from_states,
    prepare_gantt_rows,
)
from site_timing_analysis.tulsa_collect_auditlogs import list_case_folders, resolve_site_root
from site_timing_analysis.tulsa_site_pipeline import (
    build_timing_gantt_output_dir_name,
    default_analysis_root,
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


def test_default_analysis_root_uses_repo_local_timing_output_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert default_analysis_root() == repo_root / "outputs" / "timing_gantt"


def test_resolve_site_root_prefers_explicit_site_path(tmp_path: Path) -> None:
    root_dir = tmp_path / "root"
    explicit_site = tmp_path / "Clinical Science Team - Yale_065"
    fallback_site = root_dir / "Timing Data" / "Yale_065"
    explicit_site.mkdir(parents=True)
    fallback_site.mkdir(parents=True)

    resolved = resolve_site_root(
        "Yale_065",
        str(explicit_site),
        root_dir,
        "Timing Data",
    )

    assert resolved == explicit_site


def test_list_case_folders_skips_noncanonical_prefixes(tmp_path: Path) -> None:
    site_root = tmp_path / "Clinical Science Team - ASUI_122"
    for name in ["122_01-001", "122_01-002", "ASU_01-002"]:
        (site_root / name).mkdir(parents=True)

    case_dirs, skipped = list_case_folders(site_root, "ASUI_122")

    assert [path.name for path in case_dirs] == ["122_01-001", "122_01-002"]
    assert skipped == ["ASU_01-002"]


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
