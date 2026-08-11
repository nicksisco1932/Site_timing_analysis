# Project: Site Timing Analysis
# File: testing/tests/test_single_case_acquisition.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Tests safe single-case local.db acquisition without network or clinical data.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import sqlite3
import zipfile

from site_timing_analysis.single_case_acquisition import (
    _configure_logging,
    _safe_exception_text,
    acquire_single_case,
    validate_downloaded_database,
    validate_sync_url,
)


@dataclass
class FakeItem:
    sync_id: int
    name: str
    is_dir: bool
    size: int = 0


class FakeLink:
    root_sync_id = 0

    def __init__(
        self,
        children: dict[int, list[FakeItem]],
        database_source: Path,
        sources: dict[int, Path] | None = None,
    ):
        self.children = children
        self.database_source = database_source
        self.sources = sources or {}
        self.download_calls = 0

    def listdir(self, sync_id: int) -> list[FakeItem]:
        return list(self.children.get(sync_id, []))

    def download(self, item: FakeItem, destination: str) -> int:
        self.download_calls += 1
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.sources.get(item.sync_id, self.database_source), target)
        return target.stat().st_size


def _session_key(name: str) -> str | None:
    return name.split(" ", 1)[0]


def _create_valid_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE Sessions (Id TEXT PRIMARY KEY);
            CREATE TABLE Treatments (Id TEXT PRIMARY KEY, SessionId TEXT);
            CREATE TABLE AuditLogRecords (
                Id INTEGER PRIMARY KEY,
                TreatmentId TEXT,
                TimeStamp TEXT,
                AuditRecordBase_Type TEXT
            );
            INSERT INTO Sessions (Id) VALUES ('session-1');
            INSERT INTO Treatments (Id, SessionId) VALUES ('treatment-1', 'session-1');
            INSERT INTO AuditLogRecords (
                TreatmentId, TimeStamp, AuditRecordBase_Type
            ) VALUES ('treatment-1', '2026-01-01T12:00:00', 'TestRecord');
            """
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _success_tree(database_size: int) -> dict[int, list[FakeItem]]:
    return {
        0: [FakeItem(10, "TDC Sessions", True)],
        10: [FakeItem(20, "122_01-001 TDC Sessions", True)],
        20: [
            FakeItem(30, "applog", True),
            FakeItem(40, "_2025-03-24--10-01-59 105064141", True),
        ],
        40: [
            FakeItem(31, "local.db", False, database_size),
            FakeItem(32, "2025-03-24--10-01-59.zip", False, database_size),
            FakeItem(33, "Raw.zip", False, database_size),
        ],
    }


def test_single_case_success_publishes_valid_database(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    link = FakeLink(_success_tree(source.stat().st_size), source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "success"
    assert result.reason_code == ""
    assert Path(result.saved_path) == (
        tmp_path / "destination" / "122_01-001" / "local.db"
    ).resolve()
    assert Path(result.saved_path).is_file()
    assert result.database_validation["status"] == "PASS"
    assert result.database_validation["row_counts"] == {
        "AuditLogRecords": 1,
        "Sessions": 1,
        "Treatments": 1,
    }
    assert result.remote_case_folder == "122_01-001 TDC Sessions"
    assert result.remote_session_folder == "_2025-03-24--10-01-59 105064141"
    assert result.remote_archive_name == ""
    assert link.download_calls == 1


def test_ambiguous_session_match_is_quarantined_without_download(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = {
        0: [
            FakeItem(10, "TDC Sessions", True),
            FakeItem(11, "TDC Data", True),
        ],
        10: [FakeItem(20, "122_01-001 TDC Sessions", True)],
        11: [FakeItem(21, "122_01-001 TDC Sessions", True)],
    }
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "ambiguous_exact_case_folders"
    assert link.download_calls == 0


def test_multiple_direct_databases_are_quarantined_without_guessing(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[40].append(FakeItem(34, "LOCAL.DB", False, source.stat().st_size))
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "conflicting_direct_local_db"
    assert link.download_calls == 0


def test_missing_session_folder_is_reported_without_download(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    link = FakeLink(
        {
            0: [FakeItem(10, "TDC Sessions", True)],
            10: [FakeItem(20, "122_01-999 TDC Sessions", True)],
        },
        source,
    )

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "missing_exact_case_folder"
    assert link.download_calls == 0


def test_missing_direct_database_is_reported_without_download(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[40] = [
        FakeItem(32, "2025-03-24--10-01-59.zip", False, source.stat().st_size),
        FakeItem(33, "Raw.zip", False, source.stat().st_size),
    ]
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "missing_direct_local_db"
    assert link.download_calls == 0


def test_applog_is_never_inspected_for_local_database(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[40] = []
    tree[30] = [FakeItem(31, "local.db", False, source.stat().st_size)]
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "missing_direct_local_db"
    assert link.download_calls == 0


def test_multiple_timestamped_database_candidates_are_quarantined(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[20].append(FakeItem(41, "_2025-03-24--14-22-03 105064142", True))
    tree[41] = [FakeItem(42, "LOCAL.DB", False, source.stat().st_size)]
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "ambiguous_direct_local_db"
    assert len(result.warnings) == 2
    assert link.download_calls == 0


def test_related_nonexact_case_folder_is_a_conflict(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[10].append(FakeItem(21, "122_01-001 duplicate", True))
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "conflicting_case_folders"
    assert link.download_calls == 0


def test_unexpected_case_subdirectory_is_quarantined(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[20].append(FakeItem(41, "manual backup", True))
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "unexpected_case_subdirectories"
    assert result.warnings == ["manual backup"]
    assert link.download_calls == 0


def test_direct_case_folder_at_share_root_is_supported(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[0] = [FakeItem(20, "122_01-001 TDC Sessions", True)]
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "success"
    assert result.remote_container == "<share-root>"
    assert result.remote_case_folder == "122_01-001 TDC Sessions"


def test_session_export_zip_fallback_extracts_and_validates_database(tmp_path: Path) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    archive = tmp_path / "source" / "2025-03-24--10-01-59.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.write(source, "session/local.db")

    tree = _success_tree(source.stat().st_size)
    tree[40] = [
        FakeItem(32, archive.name, False, archive.stat().st_size),
        FakeItem(33, "Raw.zip", False, 100),
    ]
    link = FakeLink(tree, source, sources={32: archive})

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
        allow_session_zip_fallback=True,
    )

    assert result.status == "success"
    assert result.remote_archive_name == archive.name
    assert result.remote_database_name == "session/local.db"
    assert Path(result.saved_path).is_file()
    assert result.database_validation["status"] == "PASS"
    assert not (
        tmp_path / "destination" / "_staging" / "122_01-001" / "session-export.zip"
    ).exists()
    assert link.download_calls == 1


def test_ambiguous_session_export_zips_are_quarantined_without_download(
    tmp_path: Path,
) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    tree = _success_tree(source.stat().st_size)
    tree[40] = [
        FakeItem(32, "2025-03-24--10-01-59.zip", False, 100),
        FakeItem(34, "2025-03-24--13-26-42.zip", False, 100),
        FakeItem(33, "Raw.zip", False, 100),
    ]
    link = FakeLink(tree, source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
        allow_session_zip_fallback=True,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "ambiguous_session_export_zips"
    assert len(result.warnings) == 2
    assert link.download_calls == 0


def test_invalid_download_is_moved_to_quarantine(tmp_path: Path) -> None:
    source = tmp_path / "source" / "local.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not sqlite")
    link = FakeLink(_success_tree(source.stat().st_size), source)

    result = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=tmp_path / "destination",
        session_key=_session_key,
    )

    assert result.status == "quarantined"
    assert result.reason_code == "invalid_downloaded_database"
    assert Path(result.quarantine_path).is_file()
    assert not (tmp_path / "destination" / "122_01-001" / "local.db").exists()


def test_schema_validation_reports_missing_required_tables(tmp_path: Path) -> None:
    path = tmp_path / "local.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE AuditLogRecords (TreatmentId TEXT)")
        connection.commit()
    finally:
        connection.close()

    validation = validate_downloaded_database(path)

    assert validation["status"] == "FAIL"
    assert validation["missing_required_tables"] == ["Sessions", "Treatments"]


def test_sync_url_rejects_lookalike_host() -> None:
    try:
        validate_sync_url("https://evil-sync.com/dl/id/key")
    except Exception as exc:  # explicit assertion keeps dependencies minimal
        assert "sync.com" in str(exc)
    else:
        raise AssertionError("lookalike host must be rejected")


def test_verbose_logging_suppresses_signed_transport_urls() -> None:
    _configure_logging(verbose=True)

    assert logging.getLogger("urllib3").level == logging.WARNING
    assert logging.getLogger("requests").level == logging.WARNING


def test_default_existing_destination_behavior_remains_quarantined(
    tmp_path: Path,
) -> None:
    source = _create_valid_database(tmp_path / "source" / "local.db")
    link = FakeLink(_success_tree(source.stat().st_size), source)
    destination = tmp_path / "destination"

    first = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=destination,
        session_key=_session_key,
    )
    second = acquire_single_case(
        link=link,
        site="122",
        case_id="122_01-001",
        destination=destination,
        session_key=_session_key,
    )

    assert first.status == "success"
    assert second.status == "quarantined"
    assert second.reason_code == "destination_already_exists"
    assert link.download_calls == 1


def test_exception_text_redacts_urls_and_signed_fields() -> None:
    error = RuntimeError(
        "GET https://ln5.sync.com/path?pltoken=secret&signature=hidden failed"
    )

    sanitized = _safe_exception_text(error)

    assert "https://" not in sanitized
    assert "secret" not in sanitized
    assert "hidden" not in sanitized
    assert "<redacted-url>" in sanitized
