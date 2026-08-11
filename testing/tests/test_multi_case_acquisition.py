# Project: Site Timing Analysis
# File: testing/tests/test_multi_case_acquisition.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Tests explicit five-case local.db acquisition and aggregate reporting.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from site_timing_analysis.multi_case_acquisition import (
    acquire_case_set,
    validate_case_set_selection,
    write_multi_case_reports,
)
from site_timing_analysis.single_case_acquisition import AcquisitionConfigurationError


CASE_IDS = [f"122_01-{index:03d}" for index in range(1, 6)]


@dataclass
class FakeItem:
    sync_id: int
    name: str
    is_dir: bool
    size: int = 0
    usertime: int = 0


class FakeLink:
    root_sync_id = 0

    def __init__(self, children: dict[int, list[FakeItem]], sources: dict[int, Path]):
        self.children = children
        self.sources = sources
        self.download_calls: list[int] = []

    def listdir(self, sync_id: int) -> list[FakeItem]:
        return list(self.children.get(sync_id, []))

    def download(self, item: FakeItem, destination: str) -> int:
        self.download_calls.append(item.sync_id)
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.sources[item.sync_id], target)
        return target.stat().st_size


def _session_key(name: str) -> str | None:
    return name.split(" ", 1)[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_database(path: Path, internal_case_id: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE Sessions (Id TEXT PRIMARY KEY, PatientId TEXT);
            CREATE TABLE Treatments (Id TEXT PRIMARY KEY, SessionId TEXT);
            CREATE TABLE AuditLogRecords (
                Id INTEGER PRIMARY KEY,
                TreatmentId TEXT,
                PatientId TEXT,
                TimeStamp TEXT,
                AuditRecordBase_Type TEXT
            );
            INSERT INTO Treatments (Id, SessionId) VALUES ('treatment-1', 'session-1');
            INSERT INTO AuditLogRecords (
                TreatmentId, TimeStamp, AuditRecordBase_Type
            ) VALUES ('treatment-1', '2026-01-01T12:00:00', 'TestRecord');
            """
        )
        connection.execute(
            "INSERT INTO Sessions (Id, PatientId) VALUES ('session-1', ?)",
            (internal_case_id,),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _build_link(
    tmp_path: Path,
    *,
    identity_overrides: dict[str, str] | None = None,
) -> tuple[FakeLink, dict[str, Path]]:
    overrides = identity_overrides or {}
    children: dict[int, list[FakeItem]] = {0: [FakeItem(10, "TDC Sessions", True)]}
    sources: dict[int, Path] = {}
    source_paths: dict[str, Path] = {}
    case_folders: list[FakeItem] = []

    for offset, case_id in enumerate(CASE_IDS, start=1):
        case_folder_id = 100 + offset
        session_folder_id = 200 + offset
        database_id = 300 + offset
        case_folders.append(FakeItem(case_folder_id, f"{case_id} TDC Sessions", True))
        children[case_folder_id] = [
            FakeItem(400 + offset, "applog", True),
            FakeItem(
                session_folder_id,
                f"_2026-08-{offset:02d}--10-00-00 {900000 + offset}",
                True,
            ),
        ]
        internal_case_id = overrides.get(case_id, case_id.replace("-", "_"))
        source = _create_database(
            tmp_path / "source" / case_id / "local.db",
            internal_case_id,
        )
        source_paths[case_id] = source
        sources[database_id] = source
        children[session_folder_id] = [
            FakeItem(
                database_id,
                "LOCAL.DB" if offset % 2 == 0 else "local.db",
                False,
                source.stat().st_size,
                1_700_000_000 + offset,
            )
        ]
    children[10] = case_folders
    return FakeLink(children, sources), source_paths


def test_five_case_acquisition_writes_unique_valid_outputs_and_reports(
    tmp_path: Path,
) -> None:
    link, sources = _build_link(tmp_path)
    source_hashes = {case_id: _sha256(path) for case_id, path in sources.items()}
    destination = tmp_path / "destination"

    summary = acquire_case_set(
        link=link,
        site="122",
        case_ids=CASE_IDS,
        destination=destination,
        session_key=_session_key,
    )
    json_report, markdown_report = write_multi_case_reports(
        summary,
        json_path=destination / "_reports" / "acquisition_summary.json",
        markdown_path=destination / "_reports" / "acquisition_summary.md",
    )

    assert summary.status == "success"
    assert summary.counts == {
        "requested": 5,
        "success": 5,
        "failed": 0,
        "quarantined": 0,
    }
    assert all(summary.invariants.values())
    assert summary.structure_summary["acquisition_modes"] == {"direct_local_db": 5}
    assert len(link.download_calls) == 5
    assert len(set(link.download_calls)) == 5
    for result in summary.case_results:
        expected = (destination / result.case_id / "local.db").resolve()
        assert Path(result.saved_path) == expected
        assert expected.is_file()
        assert result.database_validation["case_identity"]["status"] == "PASS"
        assert result.remote_artifact_size_bytes == expected.stat().st_size
        assert result.remote_artifact_usertime > 0
        assert (
            destination / "_reports" / "cases" / f"{result.case_id}_acquisition.json"
        ).is_file()
    assert not (destination / "_quarantine").exists()
    assert not any(path.is_file() for path in (destination / "_staging").rglob("*"))
    assert {_sha256(path) for path in sources.values()} == set(source_hashes.values())
    assert all(_sha256(path) == source_hashes[case_id] for case_id, path in sources.items())
    assert json.loads(json_report.read_text(encoding="utf-8"))["status"] == "success"
    assert "| 122_01-005 | success |" in markdown_report.read_text(encoding="utf-8")


def test_identity_mismatch_quarantines_only_that_case_and_continues(
    tmp_path: Path,
) -> None:
    link, _sources = _build_link(
        tmp_path,
        identity_overrides={"122_01-003": "122_01_999"},
    )
    destination = tmp_path / "destination"

    summary = acquire_case_set(
        link=link,
        site="122",
        case_ids=CASE_IDS,
        destination=destination,
        session_key=_session_key,
    )

    assert summary.status == "incomplete"
    assert summary.counts["success"] == 4
    assert summary.counts["quarantined"] == 1
    mismatch = next(result for result in summary.case_results if result.case_id == "122_01-003")
    assert mismatch.reason_code == "invalid_downloaded_database"
    assert "case_identity_mismatch" in mismatch.database_validation["error"]
    assert Path(mismatch.quarantine_path).is_file()
    assert not (destination / "122_01-003" / "local.db").exists()
    assert (destination / "122_01-004" / "local.db").is_file()


def test_ambiguous_case_is_quarantined_without_stopping_remaining_cases(
    tmp_path: Path,
) -> None:
    link, sources = _build_link(tmp_path)
    case_folder = link.children[10][1]
    second_session_id = 999
    second_database_id = 998
    link.children[case_folder.sync_id].append(
        FakeItem(second_session_id, "_2026-08-10--11-00-00 999999", True)
    )
    second_source = sources[CASE_IDS[1]]
    link.sources[second_database_id] = second_source
    link.children[second_session_id] = [
        FakeItem(second_database_id, "local.db", False, second_source.stat().st_size)
    ]

    summary = acquire_case_set(
        link=link,
        site="122",
        case_ids=CASE_IDS,
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert summary.counts["success"] == 4
    assert summary.counts["quarantined"] == 1
    ambiguous = next(result for result in summary.case_results if result.case_id == CASE_IDS[1])
    assert ambiguous.reason_code == "ambiguous_direct_local_db"
    assert len(link.download_calls) == 4
    assert summary.case_results[-1].status == "success"


@pytest.mark.parametrize(
    ("site", "case_ids", "message"),
    [
        ("122", CASE_IDS[:4], "At least 5"),
        ("122", CASE_IDS[:4] + [CASE_IDS[0].upper()], "must be unique"),
        ("122", CASE_IDS[:4] + ["064_01-005"], "site prefix"),
    ],
)
def test_case_set_selection_rejects_unsafe_manifests(
    site: str,
    case_ids: list[str],
    message: str,
) -> None:
    with pytest.raises(AcquisitionConfigurationError, match=message):
        validate_case_set_selection(site, case_ids)
