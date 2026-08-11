# Project: Site Timing Analysis
# File: testing/tests/test_bulk_acquisition.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Tests explicit resumable bulk local.db acquisition and durable inventory behavior.
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

from site_timing_analysis.bulk_acquisition import (
    DestinationLock,
    _inventory_paths,
    load_case_manifest,
    load_inventory,
    main,
    new_inventory,
    resolve_case_selection,
    run_bulk_acquisition,
    validate_backend_separation,
    validate_bulk_selection,
    write_run_reports,
)
from site_timing_analysis.single_case_acquisition import AcquisitionConfigurationError


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
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


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


def _case_ids(count: int) -> list[str]:
    return [f"122_01-{index:03d}" for index in range(1, count + 1)]


def _build_link(tmp_path: Path, case_ids: list[str]) -> tuple[FakeLink, dict[str, Path]]:
    children: dict[int, list[FakeItem]] = {0: [FakeItem(10, "TDC Sessions", True)]}
    sources: dict[int, Path] = {}
    source_paths: dict[str, Path] = {}
    case_folders: list[FakeItem] = []
    for offset, case_id in enumerate(case_ids, start=1):
        case_folder_id = 1_000 + offset
        session_folder_id = 2_000 + offset
        database_id = 3_000 + offset
        case_folders.append(FakeItem(case_folder_id, f"{case_id} TDC Sessions", True))
        children[case_folder_id] = [
            FakeItem(4_000 + offset, "applog", True),
            FakeItem(
                session_folder_id,
                f"_2026-08-{((offset - 1) % 28) + 1:02d}--10-00-00 {900000 + offset}",
                True,
            ),
        ]
        source = _create_database(
            tmp_path / "source" / case_id / "local.db",
            case_id.replace("-", "_"),
        )
        sources[database_id] = source
        source_paths[case_id] = source
        children[session_folder_id] = [
            FakeItem(
                database_id,
                "local.db",
                False,
                source.stat().st_size,
                1_700_000_000 + offset,
            )
        ]
    children[10] = case_folders
    return FakeLink(children, sources), source_paths


def _run(
    *,
    link: FakeLink,
    case_ids: list[str],
    destination: Path,
    inventory: dict,
    run_id: str,
    verify_and_adopt_existing: bool = False,
):
    backend_root = destination.parent / f"{destination.name}_backend"
    inventory_json, inventory_csv = _inventory_paths(backend_root)
    return run_bulk_acquisition(
        link=link,
        site="122",
        case_ids=case_ids,
        destination=destination,
        backend_root=backend_root,
        session_key=_session_key,
        inventory=inventory,
        inventory_json_path=inventory_json,
        inventory_csv_path=inventory_csv,
        run_id=run_id,
        verify_and_adopt_existing=verify_and_adopt_existing,
    )


def test_large_manifest_downloads_once_and_rerun_reuses_inventory(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(25)
    link, sources = _build_link(tmp_path, case_ids)
    source_hashes = {case_id: _sha256(path) for case_id, path in sources.items()}
    destination = tmp_path / "destination"
    backend_root = destination.parent / f"{destination.name}_backend"
    inventory_json, inventory_csv = _inventory_paths(backend_root)
    inventory = new_inventory("122", destination)

    first = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=inventory,
        run_id="run-001",
    )
    first_reports = write_run_reports(
        first,
        backend_root / "_acquisition" / "runs" / first.run_id,
    )
    loaded = load_inventory(inventory_json, site="122", destination=destination)
    second = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=loaded,
        run_id="run-002",
    )
    second_reports = write_run_reports(
        second,
        backend_root / "_acquisition" / "runs" / second.run_id,
    )

    assert first.status == "success"
    assert first.counts["downloaded"] == 25
    assert first.counts["reused_existing"] == 0
    assert second.status == "success"
    assert second.counts["downloaded"] == 0
    assert second.counts["reused_existing"] == 25
    assert len(link.download_calls) == 25
    assert len(set(link.download_calls)) == 25
    assert all(first.invariants.values())
    assert all(second.invariants.values())
    assert inventory_json.is_file() and inventory_csv.is_file()
    assert "last_reason" in inventory_csv.read_text(encoding="utf-8").splitlines()[0]
    reloaded = load_inventory(inventory_json, site="122", destination=destination)
    assert len(reloaded["cases"]) == 25
    assert len(reloaded["runs"]) == 2
    assert all(record["attempt_count"] == 2 for record in reloaded["cases"].values())
    assert all(path.is_file() for path in first_reports + second_reports)
    for case_id, source in sources.items():
        assert _sha256(source) == source_hashes[case_id]
        assert (destination / case_id / "local.db").is_file()


def test_existing_valid_database_without_inventory_is_reported_and_skipped(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, sources = _build_link(tmp_path, case_ids)
    destination = tmp_path / "destination"
    existing = destination / case_ids[0] / "local.db"
    existing.parent.mkdir(parents=True)
    shutil.copyfile(sources[case_ids[0]], existing)
    before = _sha256(existing)

    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-no-inventory",
    )

    assert summary.status == "success"
    assert summary.counts["skipped_existing"] == 1
    assert summary.outcomes[0].action == "skipped_existing"
    assert summary.outcomes[0].result.reason_code == "existing_detected_and_skipped"
    assert "remote_content_not_compared" in summary.outcomes[0].result.warnings
    assert not link.download_calls
    assert _sha256(existing) == before


def test_existing_database_without_patient_id_is_skipped_but_not_promoted(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, sources = _build_link(tmp_path, case_ids)
    source = sources[case_ids[0]]
    connection = sqlite3.connect(source)
    try:
        connection.execute("UPDATE Sessions SET PatientId=NULL")
        connection.commit()
    finally:
        connection.close()
    destination = tmp_path / "destination"
    existing = destination / case_ids[0] / "local.db"
    existing.parent.mkdir(parents=True)
    shutil.copyfile(source, existing)
    inventory = new_inventory("122", destination)

    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=inventory,
        run_id="run-skip-no-patient-id",
    )

    result = summary.outcomes[0].result
    assert summary.status == "success"
    assert result.reason_code == "existing_detected_and_skipped"
    assert result.database_validation["case_identity"]["status"] == "NOT_AVAILABLE"
    assert inventory["cases"][case_ids[0]]["artifact"] is None
    assert not link.download_calls


def test_existing_database_can_be_adopted_only_after_exact_remote_verification(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, sources = _build_link(tmp_path, case_ids)
    destination = tmp_path / "destination"
    existing = destination / case_ids[0] / "local.db"
    existing.parent.mkdir(parents=True)
    shutil.copyfile(sources[case_ids[0]], existing)
    before = _sha256(existing)

    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-adopt-existing",
        verify_and_adopt_existing=True,
    )

    result = summary.outcomes[0].result
    assert summary.status == "success"
    assert summary.counts["adopted_existing"] == 1
    assert summary.outcomes[0].action == "adopted_existing"
    assert result.reason_code == "existing_verified_and_adopted"
    assert len(link.download_calls) == 1
    assert _sha256(existing) == before
    backend_root = destination.parent / f"{destination.name}_backend"
    assert not (backend_root / "_staging" / case_ids[0] / "local.db").exists()


def test_existing_database_adoption_quarantines_remote_mismatch_without_overwrite(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, sources = _build_link(tmp_path, case_ids)
    destination = tmp_path / "destination"
    existing = destination / case_ids[0] / "local.db"
    existing.parent.mkdir(parents=True)
    shutil.copyfile(sources[case_ids[0]], existing)
    connection = sqlite3.connect(existing)
    try:
        connection.execute("CREATE TABLE ExistingOnlyChange (Id INTEGER)")
        connection.commit()
    finally:
        connection.close()
    before = _sha256(existing)

    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-adopt-mismatch",
        verify_and_adopt_existing=True,
    )

    result = summary.outcomes[0].result
    assert summary.status == "partial"
    assert result.reason_code == "existing_destination_remote_content_mismatch"
    assert result.quarantine_path
    assert Path(result.quarantine_path).is_file()
    assert _sha256(existing) == before
    assert "existing_destination_preserved" in result.warnings


def test_missing_patient_id_uses_exact_session_start_identity_fallback(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, sources = _build_link(tmp_path, case_ids)
    source = sources[case_ids[0]]
    connection = sqlite3.connect(source)
    try:
        connection.execute("ALTER TABLE Sessions ADD COLUMN Start TEXT")
        connection.execute(
            "UPDATE Sessions SET PatientId=NULL, Start='2026-08-01T10:00:00.500'"
        )
        connection.commit()
    finally:
        connection.close()
    database_item = next(
        item
        for items in link.children.values()
        for item in items
        if not item.is_dir and item.name == "local.db"
    )
    database_item.size = source.stat().st_size

    destination = tmp_path / "destination"
    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-session-start-fallback",
    )

    identity = summary.outcomes[0].result.database_validation["case_identity"]
    assert summary.status == "success"
    assert identity["status"] == "PASS"
    assert identity["identity_method"] == "exact_case_folder_and_session_start"
    assert identity["matching_session_start_rows"] == 1


def test_missing_patient_id_with_session_start_mismatch_is_quarantined(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, sources = _build_link(tmp_path, case_ids)
    source = sources[case_ids[0]]
    connection = sqlite3.connect(source)
    try:
        connection.execute("ALTER TABLE Sessions ADD COLUMN Start TEXT")
        connection.execute(
            "UPDATE Sessions SET PatientId=NULL, Start='2026-07-01T10:00:00'"
        )
        connection.commit()
    finally:
        connection.close()
    database_item = next(
        item
        for items in link.children.values()
        for item in items
        if not item.is_dir and item.name == "local.db"
    )
    database_item.size = source.stat().st_size

    destination = tmp_path / "destination"
    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-session-start-mismatch",
    )

    result = summary.outcomes[0].result
    identity = result.database_validation["case_identity"]
    assert summary.status == "partial"
    assert result.reason_code == "invalid_downloaded_database"
    assert identity["status"] == "FAIL"
    assert identity["identity_method"] == "session_start_mismatch"


def test_modified_valid_existing_database_is_quarantined_logically(
    tmp_path: Path,
) -> None:
    case_ids = _case_ids(1)
    link, _sources = _build_link(tmp_path, case_ids)
    destination = tmp_path / "destination"
    inventory = new_inventory("122", destination)
    first = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=inventory,
        run_id="run-before-modification",
    )
    assert first.status == "success"
    existing = destination / case_ids[0] / "local.db"
    connection = sqlite3.connect(existing)
    try:
        connection.execute("CREATE TABLE LocalOnlyChange (Id INTEGER)")
        connection.commit()
    finally:
        connection.close()
    changed_hash = _sha256(existing)

    second = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=inventory,
        run_id="run-after-modification",
    )

    result = second.outcomes[0].result
    assert second.status == "partial"
    assert result.reason_code == "existing_destination_inventory_or_source_mismatch"
    assert "mismatched_field:sha256" in result.warnings
    assert len(link.download_calls) == 1
    assert _sha256(existing) == changed_hash


def test_changed_remote_metadata_prevents_existing_reuse(tmp_path: Path) -> None:
    case_ids = _case_ids(1)
    link, _sources = _build_link(tmp_path, case_ids)
    destination = tmp_path / "destination"
    inventory = new_inventory("122", destination)
    first = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=inventory,
        run_id="run-before-remote-change",
    )
    assert first.status == "success"
    database_item = next(
        item
        for items in link.children.values()
        for item in items
        if not item.is_dir and item.name == "local.db"
    )
    database_item.usertime += 1

    second = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=inventory,
        run_id="run-after-remote-change",
    )

    result = second.outcomes[0].result
    assert result.reason_code == "existing_destination_inventory_or_source_mismatch"
    assert "mismatched_field:remote_artifact_usertime" in result.warnings
    assert len(link.download_calls) == 1


def test_stale_staging_is_recovered_before_download(tmp_path: Path) -> None:
    case_ids = _case_ids(1)
    link, _sources = _build_link(tmp_path, case_ids)
    destination = tmp_path / "destination"
    backend_root = destination.parent / f"{destination.name}_backend"
    stale = backend_root / "_staging" / case_ids[0] / "local.db.part"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"interrupted")

    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-recovery",
    )

    assert summary.status == "success"
    assert summary.counts["recovered_staging_files"] == 1
    recovered = Path(summary.outcomes[0].recovered_staging_paths[0])
    assert recovered.is_file()
    assert recovered.read_bytes() == b"interrupted"
    assert not stale.exists()


def test_case_failure_is_isolated_and_later_case_continues(tmp_path: Path) -> None:
    case_ids = _case_ids(3)
    link, _sources = _build_link(tmp_path, case_ids)
    middle_case_folder = link.children[10][1]
    middle_session = next(
        item for item in link.children[middle_case_folder.sync_id] if item.name != "applog"
    )
    link.children[middle_session.sync_id] = []
    destination = tmp_path / "destination"

    summary = _run(
        link=link,
        case_ids=case_ids,
        destination=destination,
        inventory=new_inventory("122", destination),
        run_id="run-partial",
    )

    assert summary.status == "partial"
    assert summary.counts["success"] == 2
    assert summary.counts["quarantined"] == 1
    assert summary.outcomes[1].result.reason_code == "missing_direct_local_db"
    assert summary.outcomes[2].result.status == "success"
    assert (destination / case_ids[2] / "local.db").is_file()


def test_manifest_and_selection_validation_are_explicit(tmp_path: Path) -> None:
    manifest = tmp_path / "cases.txt"
    manifest.write_text(
        "# selected cases\n122_01-001\n\n122_01-002\n",
        encoding="utf-8",
    )

    assert load_case_manifest(manifest) == ["122_01-001", "122_01-002"]
    assert resolve_case_selection(
        site="122", case_ids=None, case_manifest=manifest
    ) == ["122_01-001", "122_01-002"]
    with pytest.raises(AcquisitionConfigurationError, match="exactly one"):
        resolve_case_selection(
            site="122", case_ids=["122_01-001"], case_manifest=manifest
        )
    with pytest.raises(AcquisitionConfigurationError, match="must be unique"):
        validate_bulk_selection("122", ["122_01-001", "122_01-001"])
    with pytest.raises(AcquisitionConfigurationError, match="site prefix"):
        validate_bulk_selection("122", ["064_01-001"])


def test_inventory_binding_and_destination_lock_reject_conflicts(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    inventory_json, _inventory_csv = _inventory_paths(destination)
    inventory_json.parent.mkdir(parents=True)
    inventory_json.write_text(
        json.dumps(new_inventory("122", destination)) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AcquisitionConfigurationError, match="site"):
        load_inventory(inventory_json, site="064", destination=destination)
    with DestinationLock(destination / "_acquisition" / "acquisition.lock", "one"):
        with pytest.raises(AcquisitionConfigurationError, match="holds"):
            with DestinationLock(
                destination / "_acquisition" / "acquisition.lock", "two"
            ):
                raise AssertionError("second lock must not be acquired")


def test_backend_must_be_outside_clean_destination(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    with pytest.raises(AcquisitionConfigurationError, match="outside"):
        validate_backend_separation(destination, destination)
    with pytest.raises(AcquisitionConfigurationError, match="outside"):
        validate_backend_separation(destination, destination / "Backend")

    resolved_destination, resolved_backend = validate_backend_separation(
        destination,
        tmp_path / "backend",
    )
    assert resolved_destination == destination.resolve()
    assert resolved_backend == (tmp_path / "backend").resolve()


def test_cli_configuration_failure_is_concise(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--site",
            "122",
            "--case-id",
            "064_01-001",
            "--sites-file",
            str(tmp_path / "missing-sites.json"),
            "--destination",
            str(tmp_path / "destination"),
            "--backend-dir",
            str(tmp_path / "backend"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Status: failed" in captured.out
    assert "site prefix" in captured.out
    assert "Traceback" not in captured.out
