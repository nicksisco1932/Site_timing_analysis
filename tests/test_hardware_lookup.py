from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from site_timing_analysis.hardware_lookup import CaseDbInput, ingest_local_dbs, query_ps_cable_serial


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


def test_hardware_lookup_ingest_infers_ps_serial_when_no_direct_cable(tmp_path: Path) -> None:
    source_db = tmp_path / "case_064_01-001.db"
    _create_source_db(source_db, direct_cable=False)
    lookup_db = tmp_path / "hardware_lookup.sqlite"

    ingest_result = ingest_local_dbs(
        lookup_db_path=lookup_db,
        cases=[CaseDbInput(case_id="064_01-001", db_path=source_db, site_code="064")],
        ingest_batch_id="batch_a",
        output_dir=tmp_path / "out",
    )
    assert ingest_result["cases_ingested"] == 1
    assert ingest_result["cases_failed"] == 0

    query_result = query_ps_cable_serial(
        lookup_db_path=lookup_db,
        case_id="064_01-001",
    )
    assert query_result["answer"] == "PS-111"
    assert query_result["answer_type"] == "inferred"
    assert query_result["source_table"] == "Treatments"
    assert query_result["source_field"] == "PSSerialNumber"

    summary_csv = Path(ingest_result["exports"]["summary_csv"])
    assert summary_csv.exists()
    with summary_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["answer_type"] == "inferred"


def test_hardware_lookup_prefers_direct_ps_cable_serial_when_available(tmp_path: Path) -> None:
    source_db = tmp_path / "case_064_01-002.db"
    _create_source_db(source_db, direct_cable=True)
    lookup_db = tmp_path / "hardware_lookup.sqlite"

    ingest_local_dbs(
        lookup_db_path=lookup_db,
        cases=[CaseDbInput(case_id="064_01-002", db_path=source_db, site_code="064")],
        ingest_batch_id="batch_b",
        output_dir=tmp_path / "out",
    )
    query_result = query_ps_cable_serial(
        lookup_db_path=lookup_db,
        case_id="064_01-002",
    )
    assert query_result["answer"] == "CABLE-999"
    assert query_result["answer_type"] == "direct"
    assert query_result["source_table"] == "Treatments"
    assert query_result["source_field"] == "PSCableSerialNumber"


def test_hardware_lookup_missing_answer_soft_fails_with_provenance(tmp_path: Path) -> None:
    source_db = tmp_path / "case_064_01-003.db"
    _create_source_db(
        source_db,
        direct_cable=False,
        include_treatments=False,
        include_test_results=False,
    )
    lookup_db = tmp_path / "hardware_lookup.sqlite"

    ingest_local_dbs(
        lookup_db_path=lookup_db,
        cases=[CaseDbInput(case_id="064_01-003", db_path=source_db, site_code="064")],
        ingest_batch_id="batch_c",
        output_dir=tmp_path / "out",
    )
    query_result = query_ps_cable_serial(
        lookup_db_path=lookup_db,
        case_id="064_01-003",
    )
    assert query_result["answer"] == ""
    assert query_result["answer_type"] == "missing"
    assert "no_ps_cable_or_ps_serial_identifier_found" in query_result["note"]
