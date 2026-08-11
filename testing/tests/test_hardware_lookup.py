# Project: Site Timing Analysis
# File: testing/tests/test_hardware_lookup.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-13
# Purpose: Tests hardware lookup behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
import io
import json
import sqlite3
import shutil
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from site_timing_analysis.hardware_lookup import (
    CaseDbInput,
    ingest_local_dbs,
    main,
    query_ps_cable_serial,
)


def _make_test_dir() -> Path:
    root = Path("testing") / "test_output"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="hardware_lookup_", dir=root))


def _create_source_db(
    path: Path,
    *,
    direct_cable: bool,
    include_treatments: bool = True,
    include_test_results: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE Sessions (Id INTEGER PRIMARY KEY, Uid TEXT, PatientId TEXT, Start TEXT, SessionState TEXT)"
        )
        cur.execute(
            "INSERT INTO Sessions (Id, Uid, PatientId, Start, SessionState) "
            "VALUES (1, 'sess-1', 'pt-001', '2026-01-01T10:00:00', 'Complete')"
        )

        if include_treatments:
            if direct_cable:
                cur.execute(
                    "CREATE TABLE Treatments ("
                    "Id INTEGER PRIMARY KEY, Uid TEXT, SessionId INTEGER, Start TEXT, "
                    "PSSerialNumber TEXT, PSTestDataId INTEGER, UATestDataId INTEGER, "
                    "PSCableSerialNumber TEXT)"
                )
                cur.execute(
                    "INSERT INTO Treatments (Id, Uid, SessionId, Start, PSSerialNumber, PSTestDataId, UATestDataId, PSCableSerialNumber) "
                    "VALUES (101, 'trt-1', 1, '2026-01-01T10:05:00', 'PS-111', 2001, 3001, 'CABLE-999')"
                )
            else:
                cur.execute(
                    "CREATE TABLE Treatments ("
                    "Id INTEGER PRIMARY KEY, Uid TEXT, SessionId INTEGER, Start TEXT, "
                    "PSSerialNumber TEXT, PSTestDataId INTEGER, UATestDataId INTEGER)"
                )
                cur.execute(
                    "INSERT INTO Treatments (Id, Uid, SessionId, Start, PSSerialNumber, PSTestDataId, UATestDataId) "
                    "VALUES (101, 'trt-1', 1, '2026-01-01T10:05:00', 'PS-111', 2001, 3001)"
                )

        if include_test_results:
            cur.execute(
                "CREATE TABLE HardwareTestResults ("
                "Id INTEGER PRIMARY KEY, PSTestDataId INTEGER, UATestDataId INTEGER, "
                "UASerial TEXT, PSSerialNumber TEXT, PsModel TEXT)"
            )
            cur.execute(
                "INSERT INTO HardwareTestResults (Id, PSTestDataId, UATestDataId, UASerial, PSSerialNumber, PsModel) "
                "VALUES (501, 2001, 3001, 'UA-777', 'PS-222', 'MODEL-X')"
            )

        cur.execute(
            "CREATE TABLE HardwareInfoRecords ("
            "Id INTEGER PRIMARY KEY, TreatmentId INTEGER, TimeStamp TEXT, UaPressurePsi REAL, "
            "EcdPressurePsi REAL, AmplifierState INTEGER)"
        )
        cur.execute(
            "INSERT INTO HardwareInfoRecords (Id, TreatmentId, TimeStamp, UaPressurePsi, EcdPressurePsi, AmplifierState) "
            "VALUES (1, 101, '2026-01-01T10:10:00', 11.2, 5.5, 1)"
        )
        cur.execute(
            "INSERT INTO HardwareInfoRecords (Id, TreatmentId, TimeStamp, UaPressurePsi, EcdPressurePsi, AmplifierState) "
            "VALUES (2, 101, '2026-01-01T10:11:00', 12.1, 5.2, 1)"
        )

        cur.execute(
            "CREATE TABLE ElementPowerReflections ("
            "Id INTEGER PRIMARY KEY, IsHighReflection INTEGER, IsHighAmplitude INTEGER, IsNoForwardPower INTEGER)"
        )
        cur.execute(
            "INSERT INTO ElementPowerReflections (Id, IsHighReflection, IsHighAmplitude, IsNoForwardPower) "
            "VALUES (1, 1, 0, 0)"
        )
        conn.commit()
    finally:
        conn.close()


def test_hardware_lookup_ingest_infers_ps_serial_when_no_direct_cable() -> None:
    work_dir = _make_test_dir()
    try:
        source_db = work_dir / "case_064_01-001.db"
        _create_source_db(source_db, direct_cable=False)
        lookup_db = work_dir / "hardware_lookup.sqlite"

        ingest_result = ingest_local_dbs(
            lookup_db_path=lookup_db,
            cases=[CaseDbInput(case_id="064_01-001", db_path=source_db, site_code="064")],
            ingest_batch_id="batch_a",
            output_dir=work_dir / "out",
        )
        assert ingest_result["cases_ingested"] == 1
        assert ingest_result["cases_failed"] == 0

        query_result = query_ps_cable_serial(
            lookup_db_path=lookup_db,
            case_id="064_01-001",
        )
        assert query_result["answer"] == "PS-111"
        assert query_result["answer_type"] == "inferred"
        assert query_result["answer_status"] == "inferred"
        assert query_result["question_type"] == "ps-cable-serial"
        assert (
            query_result["inference_rule"]
            == "fallback_to_ps_serial_field_when_no_direct_ps_cable_serial_exists"
        )
        assert query_result["source_db_path"] == str(source_db.resolve())
        assert query_result["source_table"] == "Treatments"
        assert query_result["source_field"] == "PSSerialNumber"
        assert query_result["raw_source_value"] == "PS-111"
        assert query_result["resolved_session_treatment_linkage"]["session_id"] == "1"
        assert query_result["resolved_session_treatment_linkage"]["treatment_id"] == "101"
        assert "No direct PS cable serial candidates were ingested" in query_result["proof_note"]

        summary_csv = Path(ingest_result["exports"]["summary_csv"])
        assert summary_csv.exists()
        with summary_csv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["answer_type"] == "inferred"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_hardware_lookup_prefers_direct_ps_cable_serial_when_available() -> None:
    work_dir = _make_test_dir()
    try:
        source_db = work_dir / "case_064_01-002.db"
        _create_source_db(source_db, direct_cable=True)
        lookup_db = work_dir / "hardware_lookup.sqlite"

        ingest_local_dbs(
            lookup_db_path=lookup_db,
            cases=[CaseDbInput(case_id="064_01-002", db_path=source_db, site_code="064")],
            ingest_batch_id="batch_b",
            output_dir=work_dir / "out",
        )
        query_result = query_ps_cable_serial(
            lookup_db_path=lookup_db,
            case_id="064_01-002",
        )
        assert query_result["answer"] == "CABLE-999"
        assert query_result["answer_type"] == "direct"
        assert query_result["answer_status"] == "direct"
        assert query_result["inference_rule"] == ""
        assert query_result["source_db_path"] == str(source_db.resolve())
        assert query_result["source_table"] == "Treatments"
        assert query_result["source_field"] == "PSCableSerialNumber"
        assert query_result["resolved_session_treatment_linkage"]["session_id"] == "1"
        assert query_result["resolved_session_treatment_linkage"]["treatment_id"] == "101"
        assert "Returned direct PS cable serial" in query_result["proof_note"]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_hardware_lookup_missing_answer_soft_fails_with_provenance() -> None:
    work_dir = _make_test_dir()
    try:
        source_db = work_dir / "case_064_01-003.db"
        _create_source_db(
            source_db,
            direct_cable=False,
            include_treatments=False,
            include_test_results=False,
        )
        lookup_db = work_dir / "hardware_lookup.sqlite"

        ingest_local_dbs(
            lookup_db_path=lookup_db,
            cases=[CaseDbInput(case_id="064_01-003", db_path=source_db, site_code="064")],
            ingest_batch_id="batch_c",
            output_dir=work_dir / "out",
        )
        query_result = query_ps_cable_serial(
            lookup_db_path=lookup_db,
            case_id="064_01-003",
        )
        assert query_result["answer"] == ""
        assert query_result["answer_type"] == "missing"
        assert query_result["answer_status"] == "unavailable"
        assert query_result["source_db_path"] == str(source_db.resolve())
        assert query_result["resolved_session_treatment_linkage"]["session_id"] == "1"
        assert query_result["resolved_session_treatment_linkage"]["treatment_id"] == ""
        assert "answer unavailable" in query_result["proof_note"]
        assert "no_ps_cable_or_ps_serial_identifier_found" in query_result["note"]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_hardware_lookup_query_cli_writes_proof_artifacts() -> None:
    work_dir = _make_test_dir()
    try:
        source_db = work_dir / "case_064_01-137.db"
        _create_source_db(source_db, direct_cable=False)
        lookup_db = work_dir / "hardware_lookup.sqlite"
        audit_md = work_dir / "proof_report.md"

        ingest_local_dbs(
            lookup_db_path=lookup_db,
            cases=[CaseDbInput(case_id="064_01-137", db_path=source_db, site_code="064")],
            ingest_batch_id="batch_proof",
            output_dir=work_dir / "out",
        )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "query",
                    "--lookup-db",
                    str(lookup_db),
                    "--case-id",
                    "064_01-137",
                    "--audit-output",
                    str(audit_md),
                ]
            )
        assert exit_code == 0

        payload = json.loads(stdout.getvalue())
        proof_csv = Path(payload["proof_csv_output"])
        assert Path(payload["audit_output"]) == audit_md.resolve()
        assert proof_csv == audit_md.resolve().with_suffix(".csv")
        assert proof_csv.exists()

        markdown_text = audit_md.read_text(encoding="utf-8")
        assert "# Hardware Query Proof Report" in markdown_text
        assert "queried_case_id: `064_01-137`" in markdown_text
        assert "question_type: `ps-cable-serial`" in markdown_text
        assert "returned_answer: `PS-111`" in markdown_text
        assert "answer_status: `inferred`" in markdown_text
        assert "source_table: `Treatments`" in markdown_text
        assert "source_field: `PSSerialNumber`" in markdown_text
        assert f"source_db_path: `{source_db.resolve()}`" in markdown_text

        with proof_csv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["case_id"] == "064_01-137"
        assert rows[0]["question_type"] == "ps-cable-serial"
        assert rows[0]["returned_answer"] == "PS-111"
        assert rows[0]["answer_status"] == "inferred"
        assert rows[0]["source_db_path"] == str(source_db.resolve())
        assert rows[0]["source_table"] == "Treatments"
        assert rows[0]["source_field"] == "PSSerialNumber"
        assert rows[0]["source_row_id"] == "101"
        assert rows[0]["raw_source_value"] == "PS-111"
        assert rows[0]["resolved_session_id"] == "1"
        assert rows[0]["resolved_treatment_id"] == "101"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
