# Project: Site Timing Analysis
# File: src/site_timing_analysis/store_relocation.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Safely relocates and verifies the canonical Timeline Analysis SQLite store.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Rollback-safe relocation for the durable Timeline Analysis store.

The migration uses SQLite's backup API rather than copying an open database.
It publishes database and CSV files through same-directory temporary names,
never overwrites an unexpected destination, and only removes explicitly named
source files after every database and export gate passes.

OneDrive remains a synchronization service, not a database coordinator. The
live command therefore requires the operator to stop OneDrive and to keep this
workstation as the sole writer.
"""

from __future__ import annotations

import argparse
import base64
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
from typing import Any, Iterable

from .analytical_store import (
    AnalyticalStoreError,
    REQUESTED_STATES,
    SCHEMA_VERSION,
    WIDE_HEADERS,
    _migration_checksum,
    _open_database,
    _verify_schema,
    export_wide,
    list_runs,
    validate_database_path,
)


LOGGER = logging.getLogger(__name__)
BUSY_TIMEOUT_MS = 30_000
CLOCK_PATTERN = re.compile(r"^(?:[1-9]|1[0-2]):[0-5]\d:[0-5]\d (?:AM|PM)$")
MINUTE_PATTERN = re.compile(r"^\d+\.\d$")
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    size_bytes: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class DatabaseSnapshot:
    file: FileSnapshot
    schema_version: int
    migration_checksum: str
    journal_mode: str
    integrity_check: str
    foreign_key_issue_count: int
    logical_content_sha256: str
    table_counts: dict[str, int]
    runs: list[dict[str, Any]]


@dataclass(frozen=True)
class ExportSnapshot:
    file: FileSnapshot
    headers: tuple[str, ...]
    row_count: int
    case_ids: tuple[str, ...]


@dataclass(frozen=True)
class LocalFileState:
    path: str
    attributes: int
    pinned: bool
    offline: bool
    recall_on_open: bool
    recall_on_data_access: bool
    unpinned: bool
    fully_local: bool


@dataclass
class RelocationResult:
    status: str
    source_database: str
    destination_database: str
    source_export: str
    destination_export: str
    run_id: str
    source_database_before: dict[str, Any]
    destination_database_after: dict[str, Any]
    source_export_before: dict[str, Any]
    destination_export_after: dict[str, Any]
    destination_database_preexisted: bool
    destination_export_preexisted: bool
    source_database_unchanged_before_cleanup: bool
    source_export_unchanged_before_cleanup: bool
    removed_paths: list[str]
    retained_nonempty_directories: list[str]
    destination_local_state: dict[str, dict[str, Any]] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def capture_file_snapshot(path: Path) -> FileSnapshot:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise AnalyticalStoreError(f"Required file is missing: {resolved}")
    before = resolved.stat()
    digest = _sha256_file(resolved)
    after = resolved.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AnalyticalStoreError(f"File changed while hashing: {resolved}")
    return FileSnapshot(
        path=str(resolved),
        size_bytes=after.st_size,
        mtime_ns=after.st_mtime_ns,
        sha256=digest,
    )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _typed_value(value: Any) -> list[str]:
    if value is None:
        return ["null", ""]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        return ["real-ieee754", struct.pack(">d", value).hex().upper()]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        return ["blob-base64", base64.b64encode(payload).decode("ascii")]
    raise AnalyticalStoreError(f"Unsupported SQLite value type: {type(value).__name__}")


def _hash_record(digest: Any, kind: str, payload: Any) -> None:
    encoded = json.dumps(
        [kind, payload], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def logical_database_hash(connection: sqlite3.Connection) -> str:
    """Hash schema and application data independent of SQLite page layout.

    Tables, columns, schema objects, and rows are ordered deterministically.
    Values carry explicit SQLite-compatible type tags; BLOBs use base64 and
    floating-point values use their IEEE-754 representation. SQLite internal
    objects, journaling state, page layout, and filesystem metadata are omitted.
    """
    digest = hashlib.sha256()
    schema_rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    for row in schema_rows:
        _hash_record(digest, "schema", [_typed_value(value) for value in row])

    table_names = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_schema
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]
    for table_name in table_names:
        quoted = _quote_identifier(table_name)
        columns = connection.execute(f"PRAGMA table_xinfo({quoted})").fetchall()
        column_contract = [
            [_typed_value(value) for value in tuple(column)] for column in columns
        ]
        _hash_record(digest, "table", table_name)
        _hash_record(digest, "columns", column_contract)
        encoded_rows: list[bytes] = []
        for row in connection.execute(f"SELECT * FROM {quoted}").fetchall():
            encoded_rows.append(
                json.dumps(
                    [_typed_value(value) for value in tuple(row)],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
        for encoded_row in sorted(encoded_rows):
            digest.update(len(encoded_row).to_bytes(8, "big"))
            digest.update(encoded_row)
    return digest.hexdigest().upper()


def _application_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_schema
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]
    return {
        name: int(connection.execute(f"SELECT COUNT(*) FROM {_quote_identifier(name)}").fetchone()[0])
        for name in names
    }


def capture_database_snapshot(database: Path) -> DatabaseSnapshot:
    target = validate_database_path(database)
    file_snapshot = capture_file_snapshot(target)
    connection = _open_database(target, read_only=True)
    try:
        _verify_schema(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        migration = connection.execute(
            "SELECT checksum_sha256 FROM schema_migrations WHERE version = ?",
            (SCHEMA_VERSION,),
        ).fetchone()
        if migration is None:
            raise AnalyticalStoreError("Schema migration record is missing.")
        snapshot = DatabaseSnapshot(
            file=file_snapshot,
            schema_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
            migration_checksum=str(migration[0]),
            journal_mode=str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
            integrity_check=integrity,
            foreign_key_issue_count=len(foreign_key_issues),
            logical_content_sha256=logical_database_hash(connection),
            table_counts=_application_table_counts(connection),
            runs=[dict(row) for row in connection.execute(
                """
                SELECT ar.run_id, ar.site_code, ar.run_status, ar.started_at_utc,
                       ar.completed_at_utc, vrs.case_count,
                       vrs.published_case_count, vrs.failed_case_count
                FROM analysis_runs ar
                JOIN v_run_status vrs ON vrs.run_id = ar.run_id
                ORDER BY ar.started_at_utc, ar.run_id
                """
            ).fetchall()],
        )
    finally:
        connection.close()
    if snapshot.integrity_check != "ok":
        raise AnalyticalStoreError(
            f"SQLite integrity check failed for {target}: {snapshot.integrity_check}"
        )
    if snapshot.foreign_key_issue_count:
        raise AnalyticalStoreError(
            f"SQLite foreign-key check found {snapshot.foreign_key_issue_count} issue(s): {target}"
        )
    if snapshot.migration_checksum != _migration_checksum():
        raise AnalyticalStoreError(f"Migration checksum mismatch for {target}")
    return snapshot


def _read_export(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            rows = list(reader)
    except OSError as exc:
        raise AnalyticalStoreError(f"Could not read export {path}: {exc}") from exc
    return fields, rows


def capture_export_snapshot(
    path: Path, *, expected_case_ids: Iterable[str] | None = None
) -> ExportSnapshot:
    resolved = path.expanduser().resolve()
    file_snapshot = capture_file_snapshot(resolved)
    fields, rows = _read_export(resolved)
    if fields != WIDE_HEADERS:
        raise AnalyticalStoreError(
            f"Wide export schema mismatch for {resolved}: {fields!r}"
        )
    case_ids = tuple(row.get("PtId", "") for row in rows)
    if not all(case_ids) or len(case_ids) != len(set(case_ids)):
        raise AnalyticalStoreError(f"Wide export has missing or duplicate case IDs: {resolved}")
    if expected_case_ids is not None and case_ids != tuple(expected_case_ids):
        raise AnalyticalStoreError(f"Wide export case ordering mismatch: {resolved}")
    for row in rows:
        if not CLOCK_PATTERN.fullmatch(row.get("starttime", "")):
            raise AnalyticalStoreError(f"Invalid starttime in wide export: {resolved}")
        if not CLOCK_PATTERN.fullmatch(row.get("endtime", "")):
            raise AnalyticalStoreError(f"Invalid endtime in wide export: {resolved}")
        for state in REQUESTED_STATES:
            if not MINUTE_PATTERN.fullmatch(row.get(state, "")):
                raise AnalyticalStoreError(
                    f"Invalid one-decimal state value for {row.get('PtId', '')}/{state}."
                )
    return ExportSnapshot(
        file=file_snapshot,
        headers=fields,
        row_count=len(rows),
        case_ids=case_ids,
    )


def _expected_case_ids(database: Path, run_id: str) -> tuple[str, ...]:
    connection = _open_database(database, read_only=True)
    try:
        _verify_schema(connection)
        return tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT c.case_id
                FROM run_cases rc
                JOIN cases c ON c.case_pk = rc.case_pk
                WHERE rc.run_id = ? AND rc.final_row_included = 1
                ORDER BY rc.case_order, c.case_id
                """,
                (run_id,),
            ).fetchall()
        )
    finally:
        connection.close()


def _sidecar_paths(database: Path) -> tuple[Path, Path]:
    return (Path(str(database) + "-wal"), Path(str(database) + "-shm"))


def _require_absent(paths: Iterable[Path], *, context: str) -> None:
    present = [str(path) for path in paths if path.exists()]
    if present:
        raise AnalyticalStoreError(f"Unexpected {context} path(s): {present}")


def _require_no_sidecars(database: Path) -> None:
    present = [str(path) for path in _sidecar_paths(database) if path.exists()]
    if present:
        raise AnalyticalStoreError(
            f"Persistent SQLite sidecar(s) remain after all connections closed: {present}"
        )


def _database_snapshots_match(source: DatabaseSnapshot, destination: DatabaseSnapshot) -> bool:
    return (
        source.schema_version == destination.schema_version
        and source.migration_checksum == destination.migration_checksum
        and source.logical_content_sha256 == destination.logical_content_sha256
        and source.table_counts == destination.table_counts
        and source.runs == destination.runs
    )


def _exports_match(source: ExportSnapshot, destination: ExportSnapshot) -> bool:
    return (
        source.file.sha256 == destination.file.sha256
        and source.headers == destination.headers
        and source.row_count == destination.row_count
        and source.case_ids == destination.case_ids
    )


def _sqlite_backup(source: Path, destination: Path) -> None:
    source_connection = _open_database(source, read_only=True)
    destination_connection = sqlite3.connect(destination, timeout=30.0)
    try:
        destination_connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    writable = _open_database(destination)
    try:
        _verify_schema(writable)
    finally:
        writable.close()


def onedrive_process_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq OneDrive.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AnalyticalStoreError("Could not verify whether OneDrive is running.")
    return "onedrive.exe" in result.stdout.casefold()


def pin_local(path: Path) -> LocalFileState:
    resolved = path.expanduser().resolve()
    if os.name != "nt":
        raise AnalyticalStoreError("OneDrive pin verification is supported only on Windows.")
    result = subprocess.run(
        ["attrib.exe", "+P", "-U", str(resolved)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AnalyticalStoreError(
            f"Could not pin OneDrive path {resolved}: {result.stderr.strip()}"
        )
    return local_file_state(resolved, require_pinned=True)


def local_file_state(path: Path, *, require_pinned: bool = False) -> LocalFileState:
    resolved = path.expanduser().resolve()
    stat_result = resolved.stat()
    attributes = int(getattr(stat_result, "st_file_attributes", 0))
    state = LocalFileState(
        path=str(resolved),
        attributes=attributes,
        pinned=bool(attributes & FILE_ATTRIBUTE_PINNED),
        offline=bool(attributes & FILE_ATTRIBUTE_OFFLINE),
        recall_on_open=bool(attributes & FILE_ATTRIBUTE_RECALL_ON_OPEN),
        recall_on_data_access=bool(attributes & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS),
        unpinned=bool(attributes & FILE_ATTRIBUTE_UNPINNED),
        fully_local=not bool(
            attributes
            & (
                FILE_ATTRIBUTE_OFFLINE
                | FILE_ATTRIBUTE_RECALL_ON_OPEN
                | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
                | FILE_ATTRIBUTE_UNPINNED
            )
        ),
    )
    if not state.fully_local:
        raise AnalyticalStoreError(f"OneDrive path is not fully local: {resolved}")
    if require_pinned and not state.pinned:
        raise AnalyticalStoreError(f"OneDrive path is not marked as pinned: {resolved}")
    return state


def _remove_explicit_source_paths(
    source_database: Path, source_export: Path
) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    for path in (source_database, *_sidecar_paths(source_database), source_export):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    retained: list[str] = []
    directories = sorted(
        {source_export.parent, source_database.parent},
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        if not directory.exists():
            continue
        try:
            directory.rmdir()
            removed.append(str(directory))
        except OSError:
            retained.append(str(directory))
    return removed, retained


def relocate_store(
    *,
    source_database: Path,
    destination_database: Path,
    source_export: Path,
    destination_export: Path,
    run_id: str,
    confirm_onedrive_stopped: bool,
    cleanup_source: bool,
    pin_destination: bool,
) -> RelocationResult:
    """Relocate one store and export through validated, non-overwriting stages."""
    if not confirm_onedrive_stopped:
        raise AnalyticalStoreError("Explicit OneDrive-stopped confirmation is required.")
    if onedrive_process_running():
        raise AnalyticalStoreError("OneDrive.exe is still running; stop synchronization first.")

    source_db = validate_database_path(source_database)
    destination_db = validate_database_path(destination_database)
    source_csv = source_export.expanduser().resolve()
    destination_csv = destination_export.expanduser().resolve()
    if source_db == destination_db or source_csv == destination_csv:
        raise AnalyticalStoreError("Source and destination paths must be distinct.")
    if not destination_db.parent.is_dir():
        raise AnalyticalStoreError(
            f"Destination database directory must already exist: {destination_db.parent}"
        )
    if pin_destination:
        pin_local(destination_db.parent)

    source_snapshot = capture_database_snapshot(source_db)
    source_export_snapshot = capture_export_snapshot(
        source_csv, expected_case_ids=_expected_case_ids(source_db, run_id)
    )
    migrating_db = destination_db.with_name(f"{destination_db.stem}.migrating{destination_db.suffix}")
    migrating_csv = destination_csv.with_name(
        f"{destination_csv.stem}.migrating{destination_csv.suffix}"
    )
    _require_absent(_sidecar_paths(destination_db), context="destination sidecar")
    destination_preexisted = destination_db.exists()
    if destination_preexisted:
        _require_absent((migrating_db, *_sidecar_paths(migrating_db)), context="migration")
        destination_snapshot = capture_database_snapshot(destination_db)
        if not _database_snapshots_match(source_snapshot, destination_snapshot):
            raise AnalyticalStoreError(
                "Existing destination database is not the intended migration output."
            )
        if destination_snapshot.journal_mode.casefold() != "delete":
            raise AnalyticalStoreError("Existing destination database is not using DELETE journaling.")
        working_database = destination_db
    else:
        _require_absent(
            (migrating_db, *_sidecar_paths(migrating_db)), context="database migration"
        )
        LOGGER.info("Creating consistent SQLite backup: %s", migrating_db)
        _sqlite_backup(source_db, migrating_db)
        destination_snapshot = capture_database_snapshot(migrating_db)
        if not _database_snapshots_match(source_snapshot, destination_snapshot):
            raise AnalyticalStoreError("Migrating database failed logical-content parity.")
        if destination_snapshot.journal_mode.casefold() != "delete":
            raise AnalyticalStoreError("Migrating database is not using DELETE journaling.")
        _require_no_sidecars(migrating_db)
        working_database = migrating_db

    expected_ids = _expected_case_ids(working_database, run_id)
    destination_export_preexisted = destination_csv.exists()
    destination_csv.parent.mkdir(parents=True, exist_ok=True)
    if pin_destination:
        pin_local(destination_csv.parent)
    _require_absent((migrating_csv,), context="export migration")
    export_wide(working_database, run_id, migrating_csv)
    staged_export_snapshot = capture_export_snapshot(
        migrating_csv, expected_case_ids=expected_ids
    )
    if not _exports_match(source_export_snapshot, staged_export_snapshot):
        raise AnalyticalStoreError("Staged export does not match the source export exactly.")
    if destination_export_preexisted:
        existing_export_snapshot = capture_export_snapshot(
            destination_csv, expected_case_ids=expected_ids
        )
        if not _exports_match(source_export_snapshot, existing_export_snapshot):
            raise AnalyticalStoreError(
                "Existing destination export is not the intended migration output."
            )

    # Publish only after both temporary artifacts and every parity gate pass.
    if not destination_preexisted:
        if destination_db.exists():
            raise AnalyticalStoreError(f"Destination appeared during migration: {destination_db}")
        migrating_db.rename(destination_db)
    if destination_export_preexisted:
        migrating_csv.unlink()
        destination_export_snapshot = existing_export_snapshot
    else:
        if destination_csv.exists():
            raise AnalyticalStoreError(f"Destination export appeared during migration: {destination_csv}")
        migrating_csv.rename(destination_csv)
        destination_export_snapshot = capture_export_snapshot(
            destination_csv, expected_case_ids=expected_ids
        )

    if pin_destination:
        destination_local_state = {
            "database_directory": asdict(
                local_file_state(destination_db.parent, require_pinned=True)
            ),
            "database": asdict(pin_local(destination_db)),
            "export_directory": asdict(
                local_file_state(destination_csv.parent, require_pinned=True)
            ),
            "export": asdict(pin_local(destination_csv)),
        }
    else:
        destination_local_state = None

    _require_no_sidecars(destination_db)
    destination_snapshot = capture_database_snapshot(destination_db)
    if not _database_snapshots_match(source_snapshot, destination_snapshot):
        raise AnalyticalStoreError("Published database failed final logical-content parity.")
    source_after = capture_database_snapshot(source_db)
    source_export_after = capture_export_snapshot(
        source_csv, expected_case_ids=_expected_case_ids(source_db, run_id)
    )
    source_database_unchanged = source_after == source_snapshot
    source_export_unchanged = source_export_after == source_export_snapshot
    if not source_database_unchanged or not source_export_unchanged:
        raise AnalyticalStoreError("Source database or export changed during migration.")

    removed_paths: list[str] = []
    retained_directories: list[str] = []
    if cleanup_source:
        removed_paths, retained_directories = _remove_explicit_source_paths(
            source_db, source_csv
        )

    return RelocationResult(
        status="RELOCATED" if not destination_preexisted else "VERIFIED_EXISTING_DESTINATION",
        source_database=str(source_db),
        destination_database=str(destination_db),
        source_export=str(source_csv),
        destination_export=str(destination_csv),
        run_id=run_id,
        source_database_before=asdict(source_snapshot),
        destination_database_after=asdict(destination_snapshot),
        source_export_before=asdict(source_export_snapshot),
        destination_export_after=asdict(destination_export_snapshot),
        destination_database_preexisted=destination_preexisted,
        destination_export_preexisted=destination_export_preexisted,
        source_database_unchanged_before_cleanup=source_database_unchanged,
        source_export_unchanged_before_cleanup=source_export_unchanged,
        removed_paths=removed_paths,
        retained_nonempty_directories=retained_directories,
        destination_local_state=destination_local_state,
    )


def verify_relocated_store(
    *, database: Path, output: Path, run_id: str, require_pinned: bool
) -> dict[str, Any]:
    target = validate_database_path(database)
    snapshot = capture_database_snapshot(target)
    if snapshot.journal_mode.casefold() != "delete":
        raise AnalyticalStoreError("Canonical store is not using DELETE journaling.")
    _require_no_sidecars(target)
    expected_ids = _expected_case_ids(target, run_id)
    export_snapshot = capture_export_snapshot(output, expected_case_ids=expected_ids)
    runs = list_runs(target)
    if not any(row["run_id"] == run_id for row in runs):
        raise AnalyticalStoreError(f"Run ID is missing from canonical store: {run_id}")
    output_path = output.expanduser().resolve()
    local_states = {
        "database_directory": asdict(
            local_file_state(target.parent, require_pinned=require_pinned)
        ),
        "database": asdict(local_file_state(target, require_pinned=require_pinned)),
        "export_directory": asdict(
            local_file_state(output_path.parent, require_pinned=require_pinned)
        ),
        "export": asdict(
            local_file_state(output_path, require_pinned=require_pinned)
        ),
    }
    return {
        "status": "VERIFIED",
        "database": asdict(snapshot),
        "export": asdict(export_snapshot),
        "runs": runs,
        "local_states": local_states,
        "sidecars_present": [],
    }


def _write_json(payload: dict[str, Any], path: Path | None) -> None:
    if path is None:
        return
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Relocate or verify the canonical Timeline Analysis SQLite store."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser("migrate", help="Safely relocate one store and export.")
    migrate.add_argument("--source-database", required=True, type=Path)
    migrate.add_argument("--database", required=True, type=Path)
    migrate.add_argument("--source-export", required=True, type=Path)
    migrate.add_argument("--output", required=True, type=Path)
    migrate.add_argument("--run-id", required=True)
    migrate.add_argument("--confirm-onedrive-stopped", action="store_true")
    migrate.add_argument("--cleanup-source", action="store_true")
    migrate.add_argument("--pin-destination", action="store_true")
    migrate.add_argument("--report-json", type=Path)

    verify = subparsers.add_parser("verify", help="Verify the relocated store and export.")
    verify.add_argument("--database", required=True, type=Path)
    verify.add_argument("--output", required=True, type=Path)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--require-pinned", action="store_true")
    verify.add_argument("--report-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "migrate":
            payload = relocate_store(
                source_database=args.source_database,
                destination_database=args.database,
                source_export=args.source_export,
                destination_export=args.output,
                run_id=args.run_id,
                confirm_onedrive_stopped=args.confirm_onedrive_stopped,
                cleanup_source=args.cleanup_source,
                pin_destination=args.pin_destination,
            ).to_dict()
        else:
            payload = verify_relocated_store(
                database=args.database,
                output=args.output,
                run_id=args.run_id,
                require_pinned=args.require_pinned,
            )
        _write_json(payload, args.report_json)
    except (AnalyticalStoreError, OSError, sqlite3.Error) as exc:
        print(f"Timeline store relocation failed: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
