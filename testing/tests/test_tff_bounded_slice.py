# Project: Site Timing Analysis
# File: testing/tests/test_tff_bounded_slice.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-13
# Purpose: Tests tff bounded slice behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from pathlib import Path

import pandas as pd

from site_timing_analysis.tff_bounded import canonicalize_case_id, run_tff_bounded_normalization


def _write_test_workbook(path: Path) -> None:
    sheet1 = pd.DataFrame(
        {
            "Generated Treatment ID": [
                "065_01-001",
                "065-01_002",
                "BADID",
                "065_01-004",
            ],
            "Site Name": [
                "Yale Saint Raphael Hospital Campus",
                "Yale Saint Raphael Hospital Campus",
                "Yale Saint Raphael Hospital Campus",
                "Yale Saint Raphael Hospital Campus",
            ],
            "Timing  Patient enters MRI room": ["11:00", "08:00", "09:00", "23:30"],
            "Timing  Anesthesia starts to prepare the patient": ["1:00", "09:00", "BAD", "11:00"],
            "Timing  Patient is sedated": ["2:00", "10:00", "10:00", "11:30"],
            "Timing  Device Insertion Begins": ["2:30", "10:30", "", "12:00"],
            "Timing  Device Insertion Complete": ["3:00", "11:00", "", "12:30"],
            "Timing  Patient leaves MRI room": ["3:30", "11:30", "", "13:00"],
            "Timing  Patient Transfer to Recovery room": ["4:00", "12:00", "", "13:30"],
        }
    )
    sheet2 = pd.DataFrame(
        {
            "PatientID": [
                "065_01-001",
                "065_01-002",
                "065_01-004",
            ]
        }
    )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sheet1.to_excel(writer, sheet_name="Sheet1", index=False)
        sheet2.to_excel(writer, sheet_name="Sheet2", index=False)


def _write_ambiguous_site_workbook(path: Path) -> None:
    sheet1 = pd.DataFrame(
        {
            "Generated Treatment ID": ["065_01-001", "066_01-001"],
            "Site Name": ["Example Shared Site", "Example Shared Site"],
            "Timing  Patient enters MRI room": ["08:00", "08:30"],
            "Timing  Anesthesia starts to prepare the patient": ["09:00", "09:30"],
            "Timing  Patient is sedated": ["10:00", "10:30"],
            "Timing  Device Insertion Begins": ["10:30", "11:00"],
            "Timing  Device Insertion Complete": ["11:00", "11:30"],
            "Timing  Patient leaves MRI room": ["11:30", "12:00"],
            "Timing  Patient Transfer to Recovery room": ["12:00", "12:30"],
        }
    )
    sheet2 = pd.DataFrame({"PatientID": ["065_01-001", "066_01-001"]})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        sheet1.to_excel(writer, sheet_name="Sheet1", index=False)
        sheet2.to_excel(writer, sheet_name="Sheet2", index=False)


def test_canonicalize_case_id_normalizes_known_variants() -> None:
    assert canonicalize_case_id("065_01-123") == ("065_01-123", "ok_canonical")
    assert canonicalize_case_id("065-01_123") == ("065_01-123", "ok_normalized_variant")
    assert canonicalize_case_id("065-01-123") == ("065_01-123", "ok_normalized_variant")
    assert canonicalize_case_id("") == (None, "missing_case_id")
    assert canonicalize_case_id("BADID") == (None, "unresolved_case_id_format")


def test_bounded_tff_run_exports_and_audits_corrections(tmp_path: Path) -> None:
    workbook = tmp_path / "tff.xlsx"
    _write_test_workbook(workbook)

    output_dir = tmp_path / "tff_out"
    paths = run_tff_bounded_normalization(workbook_path=workbook, output_dir=output_dir)

    required = [
        "normalized_case_table",
        "case_id_alignment_report",
        "site_mapping_report",
        "site_normalization_table",
        "site_normalization_summary",
        "time_correction_audit_report",
        "unresolved_soft_fail_report",
        "timing_column_report",
        "summary",
    ]
    for key in required:
        assert key in paths
        assert paths[key].exists()

    cases = pd.read_csv(paths["normalized_case_table"], dtype={"normalized_site_code": "string"})
    assert len(cases) == 4
    assert cases.loc[cases["generated_treatment_id_raw"] == "065-01_002", "case_id"].iloc[0] == "065_01-002"
    assert bool(cases.loc[cases["generated_treatment_id_raw"] == "BADID", "case_id_soft_fail"].iloc[0]) is True
    assert (cases["mapping_status"] == "mapped").all()
    assert (cases["normalized_site_code"].fillna("").str.zfill(3) == "065").all()

    align = pd.read_csv(paths["case_id_alignment_report"])
    assert bool(align.loc[align["generated_treatment_id_raw"] == "065-01_002", "appears_in_sheet2_patientid"].iloc[0]) is True

    site_map = pd.read_csv(paths["site_mapping_report"], dtype={"normalized_site_code": "string"})
    assert len(site_map) == 1
    assert site_map["mapping_status"].iloc[0] == "mapped"
    assert site_map["normalized_site_code"].fillna("").iloc[0].zfill(3) == "065"

    corrections = pd.read_csv(paths["time_correction_audit_report"])
    plus12 = corrections[corrections["correction_applied"] == "+12h"]
    assert len(plus12) >= 2
    plus24 = corrections[corrections["correction_applied"] == "+24h"]
    assert len(plus24) >= 1

    unresolved = pd.read_csv(paths["unresolved_soft_fail_report"])
    assert (unresolved["issue_type"] == "case_id_soft_fail").any()
    assert (unresolved["issue_type"] == "timing_plus24_used").any()


def test_site_normalization_marks_ambiguous_labels(tmp_path: Path) -> None:
    workbook = tmp_path / "tff_ambiguous.xlsx"
    _write_ambiguous_site_workbook(workbook)
    output_dir = tmp_path / "tff_out"
    paths = run_tff_bounded_normalization(workbook_path=workbook, output_dir=output_dir)

    site_map = pd.read_csv(paths["site_mapping_report"], dtype={"normalized_site_code": "string"})
    assert len(site_map) == 1
    assert site_map["mapping_status"].iloc[0] == "ambiguous"
    assert site_map["normalized_site_code"].fillna("").iloc[0] == ""
    assert site_map["candidate_site_codes"].iloc[0] == "065|066"

    cases = pd.read_csv(paths["normalized_case_table"])
    assert (cases["mapping_status"] == "ambiguous").all()

    unresolved = pd.read_csv(paths["unresolved_soft_fail_report"])
    assert (unresolved["issue_type"] == "site_ambiguous").any()
