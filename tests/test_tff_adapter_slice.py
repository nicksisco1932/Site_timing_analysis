from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from site_timing_analysis.first_slice_cli import run_first_slice
from site_timing_analysis.tff_adapter import apply_read_only_tff_adapter


_WORKFLOW_KEYS = (
    "patient_enters_mri",
    "anesthesia_start_prepare",
    "patient_sedated",
    "device_insertion_begins",
    "device_insertion_complete",
    "patient_leaves_mri",
    "patient_transfer_recovery",
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


def _write_tff_normalized_case_table(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["case_id", "case_id_soft_fail", "sheet1_row_number"]
    for key in _WORKFLOW_KEYS:
        fieldnames.extend(
            [
                f"{key}_minute_corrected",
                f"{key}_parse_kind",
                f"{key}_correction",
            ]
        )

    rows: list[dict[str, str]] = []
    base_row = {
        "case_id": "064_01-001",
        "case_id_soft_fail": "False",
        "sheet1_row_number": "10",
    }
    for index, key in enumerate(_WORKFLOW_KEYS):
        base_row[f"{key}_minute_corrected"] = str(600 + (index * 10))
        base_row[f"{key}_parse_kind"] = "clock_24h"
        base_row[f"{key}_correction"] = "none"
    base_row["patient_sedated_correction"] = "+12h"
    rows.append(base_row)

    duplicate_row = dict(base_row)
    duplicate_row["sheet1_row_number"] = "20"
    rows.append(duplicate_row)

    soft_fail_row = dict(base_row)
    soft_fail_row["case_id"] = "064_01-002"
    soft_fail_row["case_id_soft_fail"] = "True"
    soft_fail_row["sheet1_row_number"] = "30"
    rows.append(soft_fail_row)

    unmatched_row = dict(base_row)
    unmatched_row["case_id"] = "064_01-999"
    unmatched_row["sheet1_row_number"] = "40"
    rows.append(unmatched_row)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_tff_adapter_joins_case_results_and_preserves_provenance(tmp_path: Path) -> None:
    tff_table = tmp_path / "tff_audit" / "tff_normalized_case_table.csv"
    _write_tff_normalized_case_table(tff_table)
    case_results = [
        {"case_id": "064_01-001", "status": "processed"},
        {"case_id": "064_01-003", "status": "processed"},
    ]

    updated_results, artifacts, warnings = apply_read_only_tff_adapter(
        case_results=case_results,
        output_dir=tmp_path / "out",
        tff_case_table=tff_table,
    )

    assert len(updated_results) == 2
    assert updated_results[0]["tff_join_status"] == "matched"
    assert updated_results[0]["tff_source_row"] == 10
    assert updated_results[0]["tff_time_corrected"] is True
    assert updated_results[0]["tff_correction_type"] == "+12h"
    assert updated_results[0]["tff_parse_status"] == "ok"
    assert updated_results[0]["tff_patient_enters_mri_minute"] == "600"

    assert updated_results[1]["tff_join_status"] == "no_tff_match"
    assert any("tff_adapter:duplicate_case_id:064_01-001" in warning for warning in warnings)
    assert any("tff_adapter:pipeline_cases_without_tff:1" in warning for warning in warnings)
    assert any("tff_adapter:tff_cases_without_pipeline_match:1" in warning for warning in warnings)

    case_join_path = Path(artifacts["tff_case_join"])
    summary_path = Path(artifacts["tff_integration_summary"])
    assert case_join_path.exists()
    assert summary_path.exists()

    with case_join_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert "tff_source_row" in rows[0]
    assert "tff_time_corrected" in rows[0]
    assert "tff_correction_type" in rows[0]
    assert "tff_parse_status" in rows[0]


def test_cli_default_off_keeps_tff_adapter_disabled(tmp_path: Path) -> None:
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
    assert "tff_case_join" not in manifest.artifact_paths
    assert "tff_integration_summary" not in manifest.artifact_paths
    assert not (output_dir / "tff_adapter" / "tff_case_join.csv").exists()


def test_cli_tff_adapter_enabled_writes_join_artifacts(tmp_path: Path) -> None:
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

    tff_table = tmp_path / "tff_audit" / "tff_normalized_case_table.csv"
    _write_tff_normalized_case_table(tff_table)

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
            "--enable-tff-adapter",
            "--tff-normalized-case-table",
            str(tff_table),
        ]
    )

    assert manifest.cases_processed == 1
    assert "tff_case_join" in manifest.artifact_paths
    assert "tff_integration_summary" in manifest.artifact_paths
    assert Path(manifest.artifact_paths["tff_case_join"]).exists()
    assert Path(manifest.artifact_paths["tff_integration_summary"]).exists()

    processed = [row for row in manifest.case_results if row.get("status") == "processed"]
    assert len(processed) == 1
    assert processed[0]["tff_join_status"] == "matched"
    assert processed[0]["tff_source_row"] == 10
    assert processed[0]["tff_time_corrected"] is True


def test_tff_adapter_known_exclusion_filter_is_optional_and_auditable(tmp_path: Path) -> None:
    tff_table = tmp_path / "tff_audit" / "tff_normalized_case_table.csv"
    _write_tff_normalized_case_table(tff_table)
    case_results = [
        {"case_id": "STA_01-003", "status": "processed"},
        {"case_id": "064_01-001", "status": "processed"},
        {"case_id": "064_01-003", "status": "processed"},
    ]

    updated_results, artifacts, warnings = apply_read_only_tff_adapter(
        case_results=case_results,
        output_dir=tmp_path / "out",
        tff_case_table=tff_table,
        filter_known_exclusions=True,
    )

    by_case = {str(row["case_id"]): row for row in updated_results}
    assert by_case["STA_01-003"]["tff_join_status"] == "filtered_known_exclusion"
    assert by_case["STA_01-003"]["tff_exclusion_class"] == "rct_stanford_sta"
    assert by_case["064_01-001"]["tff_join_status"] == "matched"
    assert by_case["064_01-003"]["tff_join_status"] == "no_tff_match"
    assert any("tff_adapter:known_exclusions_filtered:1" in warning for warning in warnings)
    assert any("tff_adapter:pipeline_cases_without_tff:1" in warning for warning in warnings)

    assert "tff_filtered_known_exclusions" in artifacts
    filtered_path = Path(artifacts["tff_filtered_known_exclusions"])
    assert filtered_path.exists()
    with filtered_path.open("r", encoding="utf-8", newline="") as handle:
        filtered_rows = list(csv.DictReader(handle))
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["case_id"] == "STA_01-003"

    summary_path = Path(artifacts["tff_integration_summary"])
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "filtered known exclusions: `1`" in summary_text
    assert "true unmatched pipeline cases: `1`" in summary_text


def test_cli_tff_known_exclusion_filter_flag_marks_rct_cases(tmp_path: Path) -> None:
    root_dir = tmp_path / "root"
    site_dir = root_dir / "Stanford_064"
    case_dir = site_dir / "STA_01-003"
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

    tff_table = tmp_path / "tff_audit" / "tff_normalized_case_table.csv"
    _write_tff_normalized_case_table(tff_table)

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
            "--enable-tff-adapter",
            "--tff-filter-known-exclusions",
            "--tff-normalized-case-table",
            str(tff_table),
        ]
    )

    processed = [row for row in manifest.case_results if row.get("status") == "processed"]
    assert len(processed) == 1
    assert processed[0]["case_id"] == "STA_01-003"
    assert processed[0]["tff_join_status"] == "filtered_known_exclusion"
    assert processed[0]["tff_exclusion_class"] == "rct_stanford_sta"
    assert "tff_filtered_known_exclusions" in manifest.artifact_paths
    assert Path(manifest.artifact_paths["tff_filtered_known_exclusions"]).exists()
