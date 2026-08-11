# Project: Site Timing Analysis
# File: src/site_timing_analysis/ingestion.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Reads required SQLite tables from case local.db sources in read-only analysis mode.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import shutil
import sqlite3
import zipfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .errors import DatabaseReadError, MissingTableError
from .models import DatabaseSourceRecord, RawAuditEvent
from .profiling import PerformanceProfiler


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise DatabaseReadError(db_path, f"Failed to open SQLite database read-only: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _stage_unzipped_db_copy(
    source: DatabaseSourceRecord,
    extraction_root: Path,
) -> Path:
    """
    Copy an unzipped source database into the extraction root for retry reads.

    Input:
        Original unzipped database source plus the configured extraction root.
    Output:
        Repo-local copy path at ``<extraction_root>/<case_id>/local.db``.
    Assumptions:
        Some synced source ``local.db`` files cannot be opened in place even for
        read-only access, while a byte-for-byte repo-local copy remains readable.
    """
    case_extract_root = extraction_root.resolve() / source.case_id
    case_extract_root.mkdir(parents=True, exist_ok=True)
    staged_path = case_extract_root / "local.db"
    try:
        shutil.copyfile(source.source_path, staged_path)
    except OSError as exc:
        raise DatabaseReadError(source.source_path, f"Failed to stage SQLite database copy: {exc}") from exc
    return staged_path


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return sorted([str(row[0]) for row in rows], key=lambda name: name.lower())


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text != "" else None


def _resolve_db_file_path(source: DatabaseSourceRecord, extraction_root: Path | None) -> Path:
    if source.source_type == "unzipped":
        return source.source_path

    if source.selected_zip_member is None:
        raise DatabaseReadError(source.source_path, "selected_zip_member is required for zip_extracted source.")

    target_root = (
        extraction_root.resolve()
        if extraction_root is not None
        else source.case_path.joinpath("_db_extract").resolve()
    )
    case_extract_root = target_root / source.case_id
    case_extract_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(source.source_path, "r") as zip_file:
            extracted_path = Path(zip_file.extract(source.selected_zip_member, path=case_extract_root))
    except (zipfile.BadZipFile, OSError) as exc:
        raise DatabaseReadError(source.source_path, f"Failed to extract local.db from zip: {exc}") from exc

    db_target = case_extract_root / "local.db"
    if extracted_path.resolve() != db_target.resolve():
        db_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(extracted_path, db_target)
    return db_target


def ingest_case_database(
    source: DatabaseSourceRecord,
    *,
    extraction_root: Path | None = None,
    performance_profiler: PerformanceProfiler | None = None,
) -> dict[str, Any]:
    staging_timer = (
        performance_profiler.stage("staging or copying", case_id=source.case_id)
        if performance_profiler is not None
        else nullcontext()
    )
    with staging_timer:
        db_path = _resolve_db_file_path(source, extraction_root)
    try:
        conn = _connect_read_only(db_path)
    except DatabaseReadError:
        if source.source_type != "unzipped" or extraction_root is None:
            raise
        retry_staging_timer = (
            performance_profiler.stage("staging or copying", case_id=source.case_id)
            if performance_profiler is not None
            else nullcontext()
        )
        with retry_staging_timer:
            db_path = _stage_unzipped_db_copy(source, extraction_root)
        conn = _connect_read_only(db_path)
    try:
        tables = _table_names(conn)
        if "AuditLogRecords" not in tables:
            raise MissingTableError(db_path, "AuditLogRecords")

        audit_columns = _table_columns(conn, "AuditLogRecords")
        audit_rows = conn.execute("SELECT * FROM AuditLogRecords").fetchall()

        sessions_rows: list[dict[str, Any]] = []
        sessions_columns: list[str] = []
        if "Sessions" in tables:
            sessions_columns = _table_columns(conn, "Sessions")
            sessions_rows = [dict(row) for row in conn.execute("SELECT * FROM Sessions").fetchall()]

    except sqlite3.Error as exc:
        raise DatabaseReadError(db_path, f"Failed during SQLite read: {exc}") from exc
    finally:
        conn.close()

    raw_events: list[RawAuditEvent] = []
    for row_number, row in enumerate(audit_rows, start=1):
        row_dict = dict(row)
        segment_id = row_dict.get("SegmentId")
        if segment_id is None:
            segment_id = row_dict.get("TreatmentId")
        raw_events.append(
            RawAuditEvent(
                case_id=source.case_id,
                row_number=row_number,
                raw_timestamp=_to_optional_str(row_dict.get("TimeStamp")),
                raw_event_type=_to_optional_str(row_dict.get("AuditRecordBase_Type")),
                raw_segment_id=_to_optional_str(segment_id),
                raw_event_kind=_to_optional_int(row_dict.get("EventKind")),
                raw_payload=row_dict,
            )
        )

    schema_metadata = {
        "database_path": str(db_path),
        "tables": tables,
        "auditlog_columns": audit_columns,
        "sessions_columns": sessions_columns,
        "auditlog_row_count": len(raw_events),
        "sessions_row_count": len(sessions_rows),
    }

    return {
        "db_path": db_path,
        "raw_events": raw_events,
        "sessions_rows": sessions_rows,
        "schema_metadata": schema_metadata,
    }
