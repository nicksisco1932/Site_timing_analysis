# Project: Site Timing Analysis
# File: src/site_timing_analysis/store_upgrade.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Performs validated copy-up migrations of the canonical analytical store.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Rollback-safe copy-up schema migration for the analytical store."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .analytical_store import (
    SCHEMA_VERSION,
    AnalyticalStoreError,
    _apply_schema_migration,
    _open_database,
    _verify_schema,
    validate_database_path,
)
from .store_relocation import local_file_state, onedrive_process_running, pin_local


V1_DATA_TABLES = (
    "analysis_runs",
    "canonical_events",
    "case_analyses",
    "cases",
    "parser_versions",
    "reconciliation_results",
    "run_cases",
    "sites",
    "source_artifacts",
    "source_observations",
    "state_intervals",
    "validation_results",
    "wide_result_snapshots",
)


def _typed(value: Any) -> list[str]:
    if value is None:
        return ["null", ""]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ["blob", bytes(value).hex().upper()]
    raise AnalyticalStoreError(f"Unsupported SQLite migration value: {type(value).__name__}")


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def legacy_content_hash(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for table in V1_DATA_TABLES:
        columns = [
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        ]
        if not columns:
            raise AnalyticalStoreError(f"Required version-1 table is missing: {table}")
        rows = [
            json.dumps(
                [_typed(value) for value in tuple(row)],
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            for row in connection.execute(f"SELECT * FROM {_quote(table)}").fetchall()
        ]
        for payload in (
            json.dumps(["table", table, columns], separators=(",", ":")).encode("utf-8"),
            *sorted(rows),
        ):
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.hexdigest().upper()


def _snapshot(database: Path, *, expected_version: int) -> dict[str, Any]:
    connection = _open_database(database, read_only=True)
    try:
        _verify_schema(connection, expected_version=expected_version)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        counts = {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
            )
            for table in V1_DATA_TABLES
        }
        content_hash = legacy_content_hash(connection)
    finally:
        connection.close()
    if integrity != "ok" or foreign_keys:
        raise AnalyticalStoreError(
            f"Store validation failed: integrity={integrity}, foreign_key_issues={foreign_keys}."
        )
    stat_result = database.stat()
    return {
        "path": str(database),
        "schema_version": expected_version,
        "size_bytes": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "integrity_check": integrity,
        "foreign_key_issue_count": foreign_keys,
        "legacy_content_sha256": content_hash,
        "legacy_table_counts": counts,
    }


def _sidecars(database: Path) -> tuple[Path, Path]:
    return Path(str(database) + "-wal"), Path(str(database) + "-shm")


def _require_absent(paths: tuple[Path, ...], context: str) -> None:
    present = [str(path) for path in paths if path.exists()]
    if present:
        raise AnalyticalStoreError(f"Unexpected {context} path(s): {present}")


def _backup(source: Path, destination: Path) -> None:
    source_connection = _open_database(source, read_only=True)
    destination_connection = sqlite3.connect(destination, timeout=30.0)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def upgrade_database_copy(
    database: Path,
    *,
    confirm_onedrive_stopped: bool,
    cleanup_backup: bool,
    require_pinned: bool,
) -> dict[str, Any]:
    """Upgrade a version-1 store through a validated sibling copy and atomic swap."""
    target = validate_database_path(database)
    if not target.is_file():
        raise AnalyticalStoreError(f"Analytical database is missing: {target}")
    if not confirm_onedrive_stopped:
        raise AnalyticalStoreError("Explicit OneDrive-stopped confirmation is required.")
    if onedrive_process_running():
        raise AnalyticalStoreError("OneDrive.exe is still running; stop synchronization first.")
    if require_pinned:
        local_file_state(target.parent, require_pinned=True)
        local_file_state(target, require_pinned=True)
    _require_absent(_sidecars(target), "canonical SQLite sidecar")
    current_connection = _open_database(target, read_only=True)
    try:
        current_version = int(current_connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        current_connection.close()
    if current_version == SCHEMA_VERSION:
        after = _snapshot(target, expected_version=SCHEMA_VERSION)
        return {
            "status": "ALREADY_CURRENT",
            "database": str(target),
            "before": after,
            "after": after,
            "backup_removed": False,
        }
    if current_version != 1:
        raise AnalyticalStoreError(
            f"Copy-up supports schema version 1 only; found {current_version}."
        )

    temporary = target.with_name(f"{target.stem}.v2.migrating{target.suffix}")
    backup = target.with_name(f"{target.stem}.v1.backup{target.suffix}")
    _require_absent(
        (temporary, *_sidecars(temporary), backup, *_sidecars(backup)),
        "upgrade",
    )
    before = _snapshot(target, expected_version=1)
    _backup(target, temporary)
    connection = _open_database(temporary)
    try:
        _verify_schema(connection, expected_version=1)
        _apply_schema_migration(connection, 2)
        _verify_schema(connection, expected_version=SCHEMA_VERSION)
    finally:
        connection.close()
    _require_absent(_sidecars(temporary), "temporary SQLite sidecar")
    temporary_snapshot = _snapshot(temporary, expected_version=SCHEMA_VERSION)
    if (
        temporary_snapshot["legacy_content_sha256"] != before["legacy_content_sha256"]
        or temporary_snapshot["legacy_table_counts"] != before["legacy_table_counts"]
    ):
        raise AnalyticalStoreError("Version-2 copy changed version-1 application content.")

    target.rename(backup)
    try:
        temporary.rename(target)
        after = _snapshot(target, expected_version=SCHEMA_VERSION)
        if (
            after["legacy_content_sha256"] != before["legacy_content_sha256"]
            or after["legacy_table_counts"] != before["legacy_table_counts"]
        ):
            raise AnalyticalStoreError("Published version-2 store failed content parity.")
        _require_absent(_sidecars(target), "published SQLite sidecar")
        local_state = None
        if require_pinned:
            local_state = {
                "directory": asdict(
                    local_file_state(target.parent, require_pinned=True)
                ),
                "database": asdict(pin_local(target)),
            }
    except Exception:
        failed = target.with_name(f"{target.stem}.v2.failed{target.suffix}")
        if target.exists() and not failed.exists():
            target.rename(failed)
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise

    backup_removed = False
    if cleanup_backup:
        backup.unlink()
        backup_removed = True
    return {
        "status": "UPGRADED",
        "database": str(target),
        "before": before,
        "after": after,
        "backup": str(backup),
        "backup_removed": backup_removed,
        "local_state": local_state,
    }
