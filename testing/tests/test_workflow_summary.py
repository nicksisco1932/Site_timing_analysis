# Project: Site Timing Analysis
# File: testing/tests/test_workflow_summary.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-06-11
# Purpose: Tests workflow summary behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
import shutil
from pathlib import Path

from site_timing_analysis.workflow_summary import (
    compute_workflow_by_year,
    compute_workflow_summary,
    compute_workflow_tertiles,
    export_workflow_by_year,
    export_workflow_summary,
    export_workflow_tertiles,
)


PER_CASE_SUMMARY_FIELDNAMES = [
    "case_id",
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
    "Treating",
    "Paused",
    "Review",
    "Post-treatment scans & Device removal",
    "Patient recovery & transfer",
    "total_time",
]


def _write_per_case_summary(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PER_CASE_SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_case_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "site_code",
                "case_id",
                "case_path",
                "discovery_order",
                "candidate_unzipped_db_paths",
                "candidate_zip_paths",
                "warnings",
                "case_date",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_minimal_state_interval(path: Path, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp"])
        writer.writeheader()
        writer.writerow({"timestamp": timestamp})


def test_compute_workflow_summary_rolls_states_into_phase_medians() -> None:
    run_dir = Path("outputs/_tmp_workflow_summary_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    try:
        summary_path = tables_dir / "per_case_summary.csv"
        _write_per_case_summary(
            summary_path,
            [
                {
                    "case_id": "CASE_001",
                    "TULSA QA": "10",
                    "Room ready": "20",
                    "Patient positioning & induction": "30",
                    "Device insertion": "35",
                    "Device repositioning": "5",
                    "Alignment": "5",
                    "Coarse": "10",
                    "Detailed": "15",
                    "Planning start angle": "20",
                    "Initialization": "5",
                    "Treating": "30",
                    "Paused": "10",
                    "Review": "5",
                    "Post-treatment scans & Device removal": "20",
                    "Patient recovery & transfer": "10",
                    "total_time": "230",
                },
                {
                    "case_id": "CASE_002",
                    "TULSA QA": "5",
                    "Room ready": "10",
                    "Patient positioning & induction": "15",
                    "Device insertion": "15",
                    "Device repositioning": "5",
                    "Alignment": "10",
                    "Coarse": "10",
                    "Detailed": "10",
                    "Planning start angle": "10",
                    "Initialization": "10",
                    "Treating": "35",
                    "Paused": "10",
                    "Review": "5",
                    "Post-treatment scans & Device removal": "5",
                    "Patient recovery & transfer": "5",
                    "total_time": "160",
                },
                {
                    "case_id": "CASE_003",
                    "TULSA QA": "20",
                    "Room ready": "30",
                    "Patient positioning & induction": "40",
                    "Device insertion": "5",
                    "Device repositioning": "5",
                    "Alignment": "5",
                    "Coarse": "10",
                    "Detailed": "10",
                    "Planning start angle": "5",
                    "Initialization": "15",
                    "Treating": "40",
                    "Paused": "10",
                    "Review": "5",
                    "Post-treatment scans & Device removal": "10",
                    "Patient recovery & transfer": "10",
                    "total_time": "220",
                },
            ],
        )

        summary, per_case_phase_rows = compute_workflow_summary(run_dir, "UCSD_109")

        assert len(per_case_phase_rows) == 3
        assert summary.site_id == "UCSD_109"
        assert summary.case_count == 3
        assert summary.phase_minutes == {
            "Pre-op": 60.0,
            "Device insertion": 20.0,
            "Planning": 40.0,
            "Ablation": 60.0,
            "Post-op": 20.0,
        }
        assert summary.total_time == 200.0
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_export_workflow_summary_writes_csv_and_png() -> None:
    run_dir = Path("outputs/_tmp_workflow_summary_export_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    try:
        summary_path = tables_dir / "per_case_summary.csv"
        _write_per_case_summary(
            summary_path,
            [
                {
                    "case_id": "CASE_A",
                    "TULSA QA": "10",
                    "Room ready": "10",
                    "Patient positioning & induction": "10",
                    "Device insertion": "20",
                    "Device repositioning": "0",
                    "Alignment": "10",
                    "Coarse": "10",
                    "Detailed": "10",
                    "Planning start angle": "10",
                    "Initialization": "5",
                    "Treating": "20",
                    "Paused": "5",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "10",
                    "Patient recovery & transfer": "10",
                    "total_time": "140",
                },
                {
                    "case_id": "CASE_B",
                    "TULSA QA": "20",
                    "Room ready": "10",
                    "Patient positioning & induction": "0",
                    "Device insertion": "10",
                    "Device repositioning": "5",
                    "Alignment": "5",
                    "Coarse": "5",
                    "Detailed": "10",
                    "Planning start angle": "5",
                    "Initialization": "10",
                    "Treating": "15",
                    "Paused": "5",
                    "Review": "5",
                    "Post-treatment scans & Device removal": "5",
                    "Patient recovery & transfer": "10",
                    "total_time": "120",
                },
            ],
        )

        summary_csv, summary_png, summary, _ = export_workflow_summary(run_dir, "UCSD_109")

        assert summary_csv.exists()
        assert summary_png.exists()
        assert summary_png.stat().st_size > 0
        assert summary.total_time == sum(summary.phase_minutes.values())

        with summary_csv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows == [
            {
                "site_id": "UCSD_109",
                "case_count": "2",
                "Pre-op": "30.000000",
                "Device insertion": "17.500000",
                "Planning": "32.500000",
                "Ablation": "32.500000",
                "Post-op": "17.500000",
                "total_time": "130.000000",
            }
        ]
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_compute_workflow_tertiles_prefers_case_date_and_uses_10_10_9_groups() -> None:
    run_dir = Path("outputs/_tmp_workflow_tertiles_compute_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    try:
        rows: list[dict[str, str]] = []
        for case_number in range(1, 30):
            pre_op_value = 30 - case_number
            rows.append(
                {
                    "case_id": f"CASE_{case_number:02d}",
                    "TULSA QA": str(pre_op_value),
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": str(pre_op_value),
                }
            )
        _write_per_case_summary(tables_dir / "per_case_summary.csv", rows)

        with (run_dir / "case_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "site_code",
                    "case_id",
                    "case_path",
                    "discovery_order",
                    "candidate_unzipped_db_paths",
                    "candidate_zip_paths",
                    "warnings",
                    "case_date",
                ],
            )
            writer.writeheader()
            for case_number in range(1, 30):
                writer.writerow(
                    {
                        "site_code": "UCSD_109",
                        "case_id": f"CASE_{case_number:02d}",
                        "case_path": "",
                        "discovery_order": str(case_number),
                        "candidate_unzipped_db_paths": "",
                        "candidate_zip_paths": "",
                        "warnings": "",
                        "case_date": f"2025-01-{30 - case_number:02d}",
                    }
                )

        groups, ordered_rows = compute_workflow_tertiles(run_dir, "UCSD_109")

        assert [group.case_count for group in groups] == [10, 10, 9]
        assert ordered_rows[0]["case_id"] == "CASE_29"
        assert ordered_rows[-1]["case_id"] == "CASE_01"
        assert [group.group_label for group in groups] == ["Early", "Mid", "Late"]
        assert [group.phase_minutes["Pre-op"] for group in groups] == [5.5, 15.5, 25.0]
        assert [group.total_time for group in groups] == [5.5, 15.5, 25.0]
        assert all(group.phase_minutes["Device insertion"] == 0.0 for group in groups)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_export_workflow_tertiles_writes_csv_and_png() -> None:
    run_dir = Path("outputs/_tmp_workflow_tertiles_export_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    try:
        rows: list[dict[str, str]] = []
        for case_number in range(1, 30):
            pre_op_value = case_number
            rows.append(
                {
                    "case_id": f"CASE_{case_number:02d}",
                    "TULSA QA": str(pre_op_value),
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": str(pre_op_value),
                }
            )
        _write_per_case_summary(tables_dir / "per_case_summary.csv", rows)

        tertile_csv, tertile_png, groups, _ = export_workflow_tertiles(run_dir, "UCSD_109")

        assert tertile_csv.exists()
        assert tertile_png.exists()
        assert tertile_png.stat().st_size > 0
        assert [group.case_count for group in groups] == [10, 10, 9]
        assert all(group.total_time == sum(group.phase_minutes.values()) for group in groups)

        with tertile_csv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows == [
            {
                "site_id": "UCSD_109",
                "group_label": "Early",
                "case_count": "10",
                "case_ids": "CASE_01|CASE_02|CASE_03|CASE_04|CASE_05|CASE_06|CASE_07|CASE_08|CASE_09|CASE_10",
                "first_case_date": "",
                "last_case_date": "",
                "Pre-op": "5.500000",
                "Device insertion": "0.000000",
                "Planning": "0.000000",
                "Ablation": "0.000000",
                "Post-op": "0.000000",
                "total_time": "5.500000",
            },
            {
                "site_id": "UCSD_109",
                "group_label": "Mid",
                "case_count": "10",
                "case_ids": "CASE_11|CASE_12|CASE_13|CASE_14|CASE_15|CASE_16|CASE_17|CASE_18|CASE_19|CASE_20",
                "first_case_date": "",
                "last_case_date": "",
                "Pre-op": "15.500000",
                "Device insertion": "0.000000",
                "Planning": "0.000000",
                "Ablation": "0.000000",
                "Post-op": "0.000000",
                "total_time": "15.500000",
            },
            {
                "site_id": "UCSD_109",
                "group_label": "Late",
                "case_count": "9",
                "case_ids": "CASE_21|CASE_22|CASE_23|CASE_24|CASE_25|CASE_26|CASE_27|CASE_28|CASE_29",
                "first_case_date": "",
                "last_case_date": "",
                "Pre-op": "25.000000",
                "Device insertion": "0.000000",
                "Planning": "0.000000",
                "Ablation": "0.000000",
                "Post-op": "0.000000",
                "total_time": "25.000000",
            },
        ]
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_compute_workflow_by_year_prefers_case_date_and_computes_year_medians() -> None:
    run_dir = Path("outputs/_tmp_workflow_by_year_compute_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    try:
        _write_per_case_summary(
            tables_dir / "per_case_summary.csv",
            [
                {
                    "case_id": "CASE_A",
                    "TULSA QA": "10",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "10",
                },
                {
                    "case_id": "CASE_B",
                    "TULSA QA": "20",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "20",
                },
                {
                    "case_id": "CASE_C",
                    "TULSA QA": "30",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "30",
                },
                {
                    "case_id": "CASE_D",
                    "TULSA QA": "40",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "40",
                },
                {
                    "case_id": "CASE_E",
                    "TULSA QA": "50",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "50",
                },
            ],
        )
        _write_case_manifest(
            run_dir / "case_manifest.csv",
            [
                {
                    "site_code": "Stanford_064",
                    "case_id": "CASE_A",
                    "case_path": "",
                    "discovery_order": "1",
                    "candidate_unzipped_db_paths": "",
                    "candidate_zip_paths": "",
                    "warnings": "",
                    "case_date": "2021-05-10",
                },
                {
                    "site_code": "Stanford_064",
                    "case_id": "CASE_B",
                    "case_path": "",
                    "discovery_order": "2",
                    "candidate_unzipped_db_paths": "",
                    "candidate_zip_paths": "",
                    "warnings": "",
                    "case_date": "2021-08-01",
                },
                {
                    "site_code": "Stanford_064",
                    "case_id": "CASE_C",
                    "case_path": "",
                    "discovery_order": "3",
                    "candidate_unzipped_db_paths": "",
                    "candidate_zip_paths": "",
                    "warnings": "",
                    "case_date": "2022-01-15",
                },
                {
                    "site_code": "Stanford_064",
                    "case_id": "CASE_D",
                    "case_path": "",
                    "discovery_order": "4",
                    "candidate_unzipped_db_paths": "",
                    "candidate_zip_paths": "",
                    "warnings": "",
                    "case_date": "2022-02-18",
                },
                {
                    "site_code": "Stanford_064",
                    "case_id": "CASE_E",
                    "case_path": "",
                    "discovery_order": "5",
                    "candidate_unzipped_db_paths": "",
                    "candidate_zip_paths": "",
                    "warnings": "",
                    "case_date": "2022-09-30",
                },
            ],
        )

        groups, per_case_rows = compute_workflow_by_year(run_dir, "Stanford")

        assert len(per_case_rows) == 5
        assert [group.group_label for group in groups] == ["2021", "2022"]
        assert [group.case_count for group in groups] == [2, 3]
        assert [group.row_label for group in groups] == ["Stanford 2021 (n=2)", "Stanford 2022 (n=3)"]
        assert [group.phase_minutes["Pre-op"] for group in groups] == [15.0, 40.0]
        assert [group.total_time for group in groups] == [15.0, 40.0]
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_export_workflow_by_year_writes_csv_and_png_using_interval_timestamp_fallback() -> None:
    run_dir = Path("outputs/_tmp_workflow_by_year_export_test")
    shutil.rmtree(run_dir, ignore_errors=True)
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    try:
        _write_per_case_summary(
            tables_dir / "per_case_summary.csv",
            [
                {
                    "case_id": "CASE_001",
                    "TULSA QA": "10",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "10",
                },
                {
                    "case_id": "CASE_002",
                    "TULSA QA": "20",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "20",
                },
                {
                    "case_id": "CASE_003",
                    "TULSA QA": "30",
                    "Room ready": "0",
                    "Patient positioning & induction": "0",
                    "Device insertion": "0",
                    "Device repositioning": "0",
                    "Alignment": "0",
                    "Coarse": "0",
                    "Detailed": "0",
                    "Planning start angle": "0",
                    "Initialization": "0",
                    "Treating": "0",
                    "Paused": "0",
                    "Review": "0",
                    "Post-treatment scans & Device removal": "0",
                    "Patient recovery & transfer": "0",
                    "total_time": "30",
                },
            ],
        )
        _write_minimal_state_interval(
            run_dir / "state_intervals" / "CASE_001_state_intervals.csv",
            "2021-06-01T09:00:00",
        )
        _write_minimal_state_interval(
            run_dir / "state_intervals" / "CASE_002_state_intervals.csv",
            "2022-01-05T10:00:00",
        )
        _write_minimal_state_interval(
            run_dir / "state_intervals" / "CASE_003_state_intervals.csv",
            "2022-07-12T11:30:00",
        )

        year_csv, year_png, groups, _ = export_workflow_by_year(run_dir, "Stanford")

        assert year_csv.exists()
        assert year_png.exists()
        assert year_png.stat().st_size > 0
        assert [group.case_count for group in groups] == [1, 2]
        assert all(group.total_time == sum(group.phase_minutes.values()) for group in groups)

        with year_csv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows == [
            {
                "site_id": "Stanford",
                "group_label": "2021",
                "case_count": "1",
                "case_ids": "CASE_001",
                "first_case_date": "2021-06-01",
                "last_case_date": "2021-06-01",
                "Pre-op": "10.000000",
                "Device insertion": "0.000000",
                "Planning": "0.000000",
                "Ablation": "0.000000",
                "Post-op": "0.000000",
                "total_time": "10.000000",
            },
            {
                "site_id": "Stanford",
                "group_label": "2022",
                "case_count": "2",
                "case_ids": "CASE_002|CASE_003",
                "first_case_date": "2022-01-05",
                "last_case_date": "2022-07-12",
                "Pre-op": "25.000000",
                "Device insertion": "0.000000",
                "Planning": "0.000000",
                "Ablation": "0.000000",
                "Post-op": "0.000000",
                "total_time": "25.000000",
            },
        ]
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
