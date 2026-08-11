# Project: Site Timing Analysis
# File: src/site_timing_analysis/analytical_store.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Persists validated Timeline Analysis artifacts in a versioned cross-site SQLite store.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Versioned analytical storage for completed Timeline Analysis runs.

This module imports already-generated run artifacts. It does not alter the live
pipeline, source databases, acquisition workflow, or publication gates. Every
run is validated before the write transaction starts. Detailed state intervals
remain the source of truth; imported wide rows are retained only as parity
snapshots.

The database path is always explicit. Clinical-derived stores are rejected when
placed inside this repository or inside the run being imported.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import io
import json
import logging
import math
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Iterable

from .timing_gantt_deliverables import PHASE_ORDER, PHASE_STATE_MAP


SCHEMA_VERSION = 1
STORE_NAME = "timeline_analysis"
LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
REQUESTED_STATES = (
    "TULSA QA",
    "Room ready",
    "Patient positioning & induction",
    "Device insertion",
    "Device repositioning",
    "Alignment",
    "Coarse",
    "Detailed",
    "Planning start angle",
    "Initialization",
    "Treating",
    "Paused",
    "Review",
    "Post-treatment scans & Device removal",
    "Patient recovery & transfer",
)
WIDE_HEADERS = (
    "Experience",
    "Site",
    "PtId",
    "starttime",
    "endtime",
    *REQUESTED_STATES,
)
EVENT_FIELDS = (
    "case_id",
    "timestamp",
    "event_type",
    "source",
    "is_synthetic",
    "segment_id",
    "event_kind",
    "state",
    "state_assignment_rule",
    "cleanup_rule_applied",
    "drop_reason",
    "row_number",
    "source_detail",
    "insertion_rule",
    "raw_payload_json",
)
INTERVAL_FIELDS = (
    "case_id",
    "timestamp",
    "state",
    "start_sec",
    "duration_sec",
    "rebase_anchor",
    "origin_event_type",
    "source",
    "is_synthetic",
    "source_detail",
    "row_number",
    "state_assignment_rule",
    "cleanup_rule_applied",
    "quality_flags",
    "segment_id",
    "event_kind",
    "drop_reason",
    "insertion_rule",
    "raw_payload_json",
)
PARSER_SOURCE_PATHS = (
    "src/site_timing_analysis/models.py",
    "src/site_timing_analysis/discovery.py",
    "src/site_timing_analysis/db_source.py",
    "src/site_timing_analysis/ingestion.py",
    "src/site_timing_analysis/normalization.py",
    "src/site_timing_analysis/enrichment.py",
    "src/site_timing_analysis/timing_log.py",
    "src/site_timing_analysis/state_machine.py",
    "src/site_timing_analysis/timing.py",
    "src/site_timing_analysis/timing_gantt_deliverables.py",
    "scripts/run_asui_122_timeline_analysis.py",
)


class AnalyticalStoreError(RuntimeError):
    """Raised when store configuration, validation, or persistence fails."""


@dataclass(frozen=True)
class ParserVersion:
    """Deterministic parser provenance recorded with imported analyses."""

    package_version: str
    git_commit: str
    git_dirty: bool
    dirty_fingerprint_sha256: str
    source_fingerprint_sha256: str
    provenance_basis: str


@dataclass
class PreparedCase:
    case_id: str
    case_order: int
    experience: str
    processing_status: str
    final_row_included: bool
    failure_reason: str
    failures_json: str
    source_type: str = ""
    source_path: str = ""
    source_archive_member: str = ""
    source_size_bytes: int = 0
    source_mtime_ns: int = 0
    source_sha256: str = ""
    analysis_artifact_fingerprint_sha256: str = ""
    start_timestamp_iso: str = ""
    end_timestamp_iso: str = ""
    start_provenance_json: str = "{}"
    end_provenance_json: str = "{}"
    events: list[dict[str, str]] | None = None
    intervals: list[dict[str, str]] | None = None
    wide_snapshot: dict[str, str] | None = None
    validation_rows: list[dict[str, str]] | None = None


@dataclass
class PreparedRun:
    run_id: str
    site_code: str
    run_status: str
    started_at_utc: str
    completed_at_utc: str
    run_dir: str
    manifest_sha256: str
    import_fingerprint_sha256: str
    configuration_json: str
    configuration_fingerprint_sha256: str
    parser_version: ParserVersion
    cases: list[PreparedCase]
    reconciliation_rows: list[dict[str, str]]
    global_validation_rows: list[dict[str, str]]


@dataclass
class ImportSummary:
    status: str
    run_id: str
    site_code: str
    run_cases: int
    successful_cases: int
    failed_cases: int
    case_analyses_inserted: int
    case_analyses_reused: int
    events_inserted: int
    intervals_inserted: int
    reconciliation_rows: int
    database: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalyticalStoreError(f"Could not read JSON artifact {path}: {exc}") from exc


def _read_csv(path: Path, expected_fields: Iterable[str] | None = None) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            if expected_fields is not None and fields != tuple(expected_fields):
                raise AnalyticalStoreError(
                    f"CSV schema mismatch for {path}: expected {tuple(expected_fields)!r}, "
                    f"found {fields!r}."
                )
            return [dict(row) for row in reader]
    except OSError as exc:
        raise AnalyticalStoreError(f"Could not read CSV artifact {path}: {exc}") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_database_path(database: Path, *, run_dir: Path | None = None) -> Path:
    """Require an explicit store outside Git and the imported run."""
    target = database.expanduser().resolve()
    if target.suffix.casefold() not in {".sqlite", ".sqlite3", ".db"}:
        raise AnalyticalStoreError(
            "Analytical database must use a .sqlite, .sqlite3, or .db extension."
        )
    if _is_within(target, REPO_ROOT.resolve()):
        raise AnalyticalStoreError(
            f"Analytical database must be outside the repository: {target}"
        )
    if run_dir is not None and _is_within(target, run_dir.expanduser().resolve()):
        raise AnalyticalStoreError(
            f"Analytical database must be outside the imported run directory: {target}"
        )
    return target


def _state_view_columns() -> str:
    columns: list[str] = []
    for state in REQUESTED_STATES:
        literal = state.replace("'", "''")
        identifier = state.replace('"', '""')
        columns.append(
            "COALESCE(SUM(CASE WHEN si.state = "
            f"'{literal}' THEN si.duration_sec ELSE 0 END) / 60.0, 0.0) "
            f'AS "{identifier}"'
        )
    return ",\n            ".join(columns)


def _schema_sql() -> str:
    return f"""
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL
        );

        CREATE TABLE parser_versions (
            parser_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_version TEXT NOT NULL,
            git_commit TEXT NOT NULL,
            git_dirty INTEGER NOT NULL CHECK (git_dirty IN (0, 1)),
            dirty_fingerprint_sha256 TEXT NOT NULL,
            source_fingerprint_sha256 TEXT NOT NULL UNIQUE,
            provenance_basis TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE sites (
            site_code TEXT PRIMARY KEY,
            first_seen_at_utc TEXT NOT NULL
        );

        CREATE TABLE cases (
            case_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            site_code TEXT NOT NULL REFERENCES sites(site_code),
            case_id TEXT NOT NULL,
            first_seen_at_utc TEXT NOT NULL,
            UNIQUE (site_code, case_id)
        );

        CREATE TABLE source_artifacts (
            source_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_pk INTEGER NOT NULL REFERENCES cases(case_pk),
            source_type TEXT NOT NULL,
            archive_member TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            sha256 TEXT NOT NULL,
            first_path TEXT NOT NULL,
            first_mtime_ns INTEGER NOT NULL,
            first_seen_at_utc TEXT NOT NULL,
            UNIQUE (case_pk, sha256)
        );

        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            site_code TEXT NOT NULL REFERENCES sites(site_code),
            run_status TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            completed_at_utc TEXT NOT NULL,
            run_dir TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            import_fingerprint_sha256 TEXT NOT NULL,
            parser_version_id INTEGER NOT NULL REFERENCES parser_versions(parser_version_id),
            configuration_json TEXT NOT NULL,
            configuration_fingerprint_sha256 TEXT NOT NULL,
            imported_at_utc TEXT NOT NULL
        );

        CREATE TABLE case_analyses (
            case_analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_pk INTEGER NOT NULL REFERENCES cases(case_pk),
            source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
            parser_version_id INTEGER NOT NULL REFERENCES parser_versions(parser_version_id),
            configuration_fingerprint_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            start_timestamp_iso TEXT NOT NULL,
            end_timestamp_iso TEXT NOT NULL,
            start_provenance_json TEXT NOT NULL,
            end_provenance_json TEXT NOT NULL,
            analysis_artifact_fingerprint_sha256 TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            UNIQUE (
                source_artifact_id,
                parser_version_id,
                configuration_fingerprint_sha256
            )
        );

        CREATE TABLE run_cases (
            run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
            case_pk INTEGER NOT NULL REFERENCES cases(case_pk),
            case_analysis_id INTEGER REFERENCES case_analyses(case_analysis_id),
            case_order INTEGER NOT NULL,
            experience TEXT NOT NULL,
            processing_status TEXT NOT NULL,
            final_row_included INTEGER NOT NULL CHECK (final_row_included IN (0, 1)),
            start_timestamp_iso TEXT NOT NULL,
            end_timestamp_iso TEXT NOT NULL,
            start_provenance_json TEXT NOT NULL,
            end_provenance_json TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            failures_json TEXT NOT NULL,
            PRIMARY KEY (run_id, case_pk),
            UNIQUE (run_id, case_order)
        );

        CREATE TABLE source_observations (
            run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
            case_pk INTEGER NOT NULL REFERENCES cases(case_pk),
            source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
            observed_path TEXT NOT NULL,
            observed_source_type TEXT NOT NULL,
            observed_archive_member TEXT NOT NULL,
            observed_size_bytes INTEGER NOT NULL,
            observed_mtime_ns INTEGER NOT NULL,
            observed_at_utc TEXT NOT NULL,
            PRIMARY KEY (run_id, case_pk)
        );

        CREATE TABLE canonical_events (
            case_analysis_id INTEGER NOT NULL REFERENCES case_analyses(case_analysis_id) ON DELETE CASCADE,
            event_ordinal INTEGER NOT NULL,
            timestamp_iso TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            is_synthetic INTEGER NOT NULL CHECK (is_synthetic IN (0, 1)),
            segment_id TEXT,
            event_kind INTEGER,
            state TEXT,
            state_assignment_rule TEXT,
            cleanup_rule_applied TEXT,
            drop_reason TEXT,
            source_row_number INTEGER,
            source_detail TEXT NOT NULL,
            insertion_rule TEXT,
            raw_payload_json TEXT NOT NULL,
            PRIMARY KEY (case_analysis_id, event_ordinal)
        );

        CREATE TABLE state_intervals (
            case_analysis_id INTEGER NOT NULL REFERENCES case_analyses(case_analysis_id) ON DELETE CASCADE,
            interval_ordinal INTEGER NOT NULL,
            timestamp_iso TEXT NOT NULL,
            state TEXT,
            start_sec REAL NOT NULL,
            duration_sec REAL NOT NULL CHECK (duration_sec >= 0),
            rebase_anchor TEXT,
            origin_event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            is_synthetic INTEGER NOT NULL CHECK (is_synthetic IN (0, 1)),
            source_detail TEXT NOT NULL,
            source_row_number INTEGER,
            state_assignment_rule TEXT,
            cleanup_rule_applied TEXT,
            quality_flags_json TEXT NOT NULL,
            segment_id TEXT,
            event_kind INTEGER,
            drop_reason TEXT,
            insertion_rule TEXT,
            raw_payload_json TEXT NOT NULL,
            PRIMARY KEY (case_analysis_id, interval_ordinal)
        );

        CREATE TABLE wide_result_snapshots (
            run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
            case_pk INTEGER NOT NULL REFERENCES cases(case_pk),
            row_json TEXT NOT NULL,
            row_sha256 TEXT NOT NULL,
            PRIMARY KEY (run_id, case_pk)
        );

        CREATE TABLE reconciliation_results (
            run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
            case_pk INTEGER NOT NULL REFERENCES cases(case_pk),
            phase TEXT NOT NULL,
            detailed_minutes_unrounded REAL,
            rollup_minutes REAL,
            difference_minutes REAL,
            status TEXT NOT NULL,
            failure_type TEXT NOT NULL,
            details_json TEXT NOT NULL,
            PRIMARY KEY (run_id, case_pk, phase)
        );

        CREATE TABLE validation_results (
            validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
            case_pk INTEGER REFERENCES cases(case_pk),
            check_name TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_type TEXT NOT NULL,
            details_json TEXT NOT NULL
        );

        CREATE INDEX idx_cases_case_id ON cases(case_id);
        CREATE INDEX idx_source_artifacts_sha256 ON source_artifacts(sha256);
        CREATE INDEX idx_case_analyses_case_pk ON case_analyses(case_pk);
        CREATE INDEX idx_events_timestamp ON canonical_events(timestamp_iso);
        CREATE INDEX idx_intervals_state ON state_intervals(state);
        CREATE INDEX idx_run_cases_analysis ON run_cases(case_analysis_id);

        CREATE VIEW v_case_state_seconds AS
        SELECT case_analysis_id, state, SUM(duration_sec) AS duration_sec_unrounded
        FROM state_intervals
        WHERE state IS NOT NULL AND state <> '' AND duration_sec > 0
        GROUP BY case_analysis_id, state;

        CREATE VIEW v_latest_case_analyses AS
        SELECT * FROM (
            SELECT
                ca.*,
                c.site_code,
                c.case_id,
                ROW_NUMBER() OVER (
                    PARTITION BY ca.case_pk
                    ORDER BY ca.created_at_utc DESC, ca.case_analysis_id DESC
                ) AS version_rank
            FROM case_analyses ca
            JOIN cases c ON c.case_pk = ca.case_pk
        )
        WHERE version_rank = 1;

        CREATE VIEW v_run_status AS
        SELECT
            ar.run_id,
            ar.site_code,
            ar.run_status,
            COUNT(rc.case_pk) AS case_count,
            SUM(CASE WHEN rc.final_row_included = 1 THEN 1 ELSE 0 END) AS published_case_count,
            SUM(CASE WHEN rc.processing_status <> 'PASS' THEN 1 ELSE 0 END) AS failed_case_count
        FROM analysis_runs ar
        LEFT JOIN run_cases rc ON rc.run_id = ar.run_id
        GROUP BY ar.run_id, ar.site_code, ar.run_status;

        CREATE VIEW v_run_case_wide AS
        SELECT
            rc.run_id,
            rc.case_order,
            rc.experience,
            c.site_code AS site,
            c.case_id,
            ca.start_timestamp_iso,
            ca.end_timestamp_iso,
            {_state_view_columns()}
        FROM run_cases rc
        JOIN cases c ON c.case_pk = rc.case_pk
        JOIN case_analyses ca ON ca.case_analysis_id = rc.case_analysis_id
        LEFT JOIN state_intervals si ON si.case_analysis_id = ca.case_analysis_id
        WHERE rc.final_row_included = 1
        GROUP BY
            rc.run_id,
            rc.case_order,
            rc.experience,
            c.site_code,
            c.case_id,
            ca.start_timestamp_iso,
            ca.end_timestamp_iso;
    """


def _migration_checksum() -> str:
    return _sha256_bytes(_schema_sql().encode("utf-8"))


def _open_database(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection


def _verify_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        raise AnalyticalStoreError(
            f"Unsupported analytical schema version {version}; expected {SCHEMA_VERSION}."
        )
    row = connection.execute(
        "SELECT checksum_sha256 FROM schema_migrations WHERE version = ?",
        (SCHEMA_VERSION,),
    ).fetchone()
    if row is None or row["checksum_sha256"] != _migration_checksum():
        raise AnalyticalStoreError(
            "Schema migration checksum does not match this application version."
        )
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise AnalyticalStoreError("SQLite foreign-key enforcement is not enabled.")


def initialize_database(database: Path) -> Path:
    """Create schema v1 or verify an existing compatible database."""
    target = validate_database_path(database)
    LOGGER.info("Initializing or verifying analytical store: %s", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    connection = _open_database(target)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == 0 and not existed:
            checksum = _migration_checksum()
            safe_checksum = checksum.replace("'", "''")
            script = (
                "BEGIN IMMEDIATE;\n"
                + _schema_sql()
                + "\nINSERT INTO schema_migrations "
                "(version, name, checksum_sha256, applied_at_utc) VALUES "
                f"(1, 'initial_timeline_store', '{safe_checksum}', '{_utc_now()}');\n"
                "PRAGMA user_version = 1;\nCOMMIT;"
            )
            try:
                connection.executescript(script)
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        elif version == 0 and existed:
            raise AnalyticalStoreError(
                f"Existing file is not an initialized {STORE_NAME} database: {target}"
            )
        elif version != SCHEMA_VERSION:
            raise AnalyticalStoreError(
                f"Unsupported analytical schema version {version}; expected {SCHEMA_VERSION}."
            )
        _verify_schema(connection)
    finally:
        connection.close()
    return target


def _git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _git_bytes(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else b"unavailable"


def current_parser_version() -> ParserVersion:
    """Fingerprint the parser implementation independently of store code."""
    try:
        package_version = importlib.metadata.version("site-timing-analysis")
    except importlib.metadata.PackageNotFoundError:
        package_version = "0.1.0"
    source_digest = hashlib.sha256()
    for relative in sorted(PARSER_SOURCE_PATHS):
        path = REPO_ROOT / relative
        if not path.is_file():
            raise AnalyticalStoreError(f"Parser provenance source is missing: {path}")
        source_digest.update(relative.encode("utf-8"))
        source_digest.update(b"\0")
        source_digest.update(path.read_bytes())
        source_digest.update(b"\0")
    dirty_text = _git_text("status", "--porcelain", "--untracked-files=no")
    dirty_payload = (
        dirty_text.encode("utf-8")
        + b"\0"
        + _git_bytes("diff", "--binary", "HEAD", "--", ".")
    )
    return ParserVersion(
        package_version=package_version,
        git_commit=_git_text("rev-parse", "HEAD"),
        git_dirty=bool(dirty_text and dirty_text != "unavailable"),
        dirty_fingerprint_sha256=_sha256_bytes(dirty_payload),
        source_fingerprint_sha256=source_digest.hexdigest().upper(),
        provenance_basis="import_time_repository_parser_source_fingerprint",
    )


def _parse_iso(value: str, *, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnalyticalStoreError(f"Invalid ISO datetime for {context}: {value!r}") from exc
    return parsed


def _optional_int(value: str | None) -> int | None:
    text = "" if value is None else str(value).strip()
    return None if not text else int(text)


def _optional_float(value: str | None, *, context: str) -> float | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError as exc:
        raise AnalyticalStoreError(f"Invalid numeric value for {context}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise AnalyticalStoreError(f"Non-finite numeric value for {context}: {value!r}")
    return parsed


def _bool_value(value: str, *, context: str) -> int:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return 1
    if normalized in {"false", "0", "no"}:
        return 0
    raise AnalyticalStoreError(f"Invalid boolean for {context}: {value!r}")


def _clock(value: str) -> str:
    parsed = _parse_iso(value, context="wide endpoint")
    return parsed.strftime("%I:%M:%S %p").lstrip("0")


def _snapshot_endpoint_matches(value: str, endpoint_iso: str) -> bool:
    """Accept historical ISO snapshots and the current clock-only contract."""
    return value == endpoint_iso or value == _clock(endpoint_iso)


def _require_unique(rows: list[dict[str, Any]], key: str, *, context: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key, ""))
        if not value or value in indexed:
            raise AnalyticalStoreError(f"Missing or duplicate {key} in {context}: {value!r}")
        indexed[value] = row
    return indexed


def _validate_raw_json(value: str, *, context: str) -> str:
    text = str(value or "{}").strip() or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalyticalStoreError(f"Invalid raw_payload_json for {context}: {exc}") from exc
    return _canonical_json(parsed)


def _canonical_json_text(value: Any, *, context: str) -> str:
    text = str(value or "{}").strip() or "{}"
    try:
        return _canonical_json(json.loads(text))
    except json.JSONDecodeError as exc:
        raise AnalyticalStoreError(f"Invalid JSON for {context}: {exc}") from exc


def _analysis_artifact_fingerprint(
    *,
    start_timestamp_iso: str,
    end_timestamp_iso: str,
    start_provenance_json: str,
    end_provenance_json: str,
    events: list[dict[str, str]],
    intervals: list[dict[str, str]],
) -> str:
    payload = {
        "start_timestamp_iso": start_timestamp_iso,
        "end_timestamp_iso": end_timestamp_iso,
        "start_provenance_json": json.loads(start_provenance_json),
        "end_provenance_json": json.loads(end_provenance_json),
        "events": events,
        "intervals": intervals,
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def _validate_phase_configuration() -> None:
    assignments = {
        state: [phase for phase in PHASE_ORDER if state in PHASE_STATE_MAP.get(phase, ())]
        for state in REQUESTED_STATES
    }
    invalid = {state: phases for state, phases in assignments.items() if len(phases) != 1}
    if invalid:
        raise AnalyticalStoreError(
            "Requested-state phase mapping is incomplete or ambiguous: "
            + _canonical_json(invalid)
        )


def _case_validation_rows(
    execution_case: dict[str, Any], failures: list[Any]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in (
        "pipeline_status",
        "event_status",
        "interval_status",
        "assigned_database_status",
        "identity_status",
    ):
        status = str(execution_case.get(name, ""))
        details: dict[str, Any] = {"recorded_status": status}
        if name == "pipeline_status":
            details.update(
                {
                    "failure_reason": str(execution_case.get("failure_reason", "")),
                    "failures": failures,
                }
            )
        if name == "identity_status":
            details["identity_reason"] = str(execution_case.get("identity_reason", ""))
        rows.append(
            {
                "check_name": name,
                "status": status,
                "failure_type": "" if status == "PASS" else name,
                "details_json": _canonical_json(details),
            }
        )
    return rows


def _validate_case_artifacts(
    *,
    case_id: str,
    site_code: str,
    case_manifest: dict[str, Any],
    execution_case: dict[str, Any],
    wide_row: dict[str, str],
    events: list[dict[str, str]],
    intervals: list[dict[str, str]],
) -> None:
    if not events or not intervals:
        raise AnalyticalStoreError(f"Case {case_id} has empty canonical artifacts.")
    if any(row.get("case_id") != case_id for row in events):
        raise AnalyticalStoreError(f"Canonical event identity mismatch for {case_id}.")
    if any(row.get("case_id") != case_id for row in intervals):
        raise AnalyticalStoreError(f"Interval identity mismatch for {case_id}.")
    if int(case_manifest.get("state_labeled_event_count", -1)) != len(events):
        raise AnalyticalStoreError(f"State-labeled event count mismatch for {case_id}.")
    if int(case_manifest.get("state_interval_count", -1)) != len(intervals):
        raise AnalyticalStoreError(f"State interval count mismatch for {case_id}.")

    start = _parse_iso(str(execution_case.get("starttime", "")), context=f"{case_id} start")
    end = _parse_iso(str(execution_case.get("endtime", "")), context=f"{case_id} end")
    if end < start:
        raise AnalyticalStoreError(f"Case {case_id} has reversed endpoint datetimes.")
    previous_end: datetime | None = None
    totals = {state: 0.0 for state in REQUESTED_STATES}
    for ordinal, row in enumerate(intervals, start=1):
        try:
            start_sec = float(row["start_sec"])
            duration_sec = float(row["duration_sec"])
        except (TypeError, ValueError) as exc:
            raise AnalyticalStoreError(f"Non-numeric interval for {case_id} row {ordinal}.") from exc
        if not math.isfinite(start_sec) or not math.isfinite(duration_sec):
            raise AnalyticalStoreError(f"Non-finite interval for {case_id} row {ordinal}.")
        # ``start_sec`` is relative to the run's rebase anchor.  Valid events
        # before that anchor therefore have a negative offset; duration itself
        # must never be negative.
        if duration_sec < 0:
            raise AnalyticalStoreError(f"Negative duration for {case_id} row {ordinal}.")
        timestamp = _parse_iso(row["timestamp"], context=f"{case_id} interval row {ordinal}")
        interval_end = timestamp + timedelta(seconds=duration_sec)
        if interval_end < timestamp:
            raise AnalyticalStoreError(f"Reversed interval for {case_id} row {ordinal}.")
        if timestamp < start or interval_end > end + timedelta(microseconds=2):
            raise AnalyticalStoreError(
                f"Interval timestamp outside valid event window for {case_id} row {ordinal}."
            )
        if duration_sec > 0 and previous_end is not None and timestamp < previous_end - timedelta(
            microseconds=2
        ):
            raise AnalyticalStoreError(f"Overlapping intervals for {case_id} row {ordinal}.")
        if previous_end is None or interval_end > previous_end:
            previous_end = interval_end
        state = row.get("state", "")
        if state in totals:
            totals[state] += duration_sec / 60.0
        _validate_raw_json(row.get("raw_payload_json", "{}"), context=f"{case_id} interval")
    for ordinal, row in enumerate(events, start=1):
        timestamp = _parse_iso(row["timestamp"], context=f"{case_id} event row {ordinal}")
        if timestamp < start or timestamp > end:
            raise AnalyticalStoreError(
                f"Canonical event outside valid event window for {case_id} row {ordinal}."
            )
        _validate_raw_json(row.get("raw_payload_json", "{}"), context=f"{case_id} event")

    if wide_row.get("Site") != site_code or wide_row.get("PtId") != case_id:
        raise AnalyticalStoreError(f"Wide result identity mismatch for {case_id}.")
    if not _snapshot_endpoint_matches(
        str(wide_row.get("starttime", "")), str(execution_case["starttime"])
    ):
        raise AnalyticalStoreError(f"Wide starttime mismatch for {case_id}.")
    if not _snapshot_endpoint_matches(
        str(wide_row.get("endtime", "")), str(execution_case["endtime"])
    ):
        raise AnalyticalStoreError(f"Wide endtime mismatch for {case_id}.")
    for state, total in totals.items():
        expected = f"{max(0.0, total):.1f}"
        if wide_row.get(state) != expected:
            raise AnalyticalStoreError(
                f"Wide interval-derived value mismatch for {case_id} / {state}: "
                f"expected {expected!r}, found {wide_row.get(state)!r}."
            )


def _artifact_path(path_value: str, *, run_dir: Path, context: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = run_dir / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise AnalyticalStoreError(f"Missing {context} artifact: {resolved}")
    if not _is_within(resolved, run_dir):
        raise AnalyticalStoreError(f"{context} artifact is outside run directory: {resolved}")
    return resolved


def prepare_run_import(
    run_dir: Path,
    *,
    parser_version: ParserVersion | None = None,
) -> PreparedRun:
    """Validate a published run completely before any store transaction."""
    LOGGER.info("Validating Timeline Analysis run artifacts: %s", run_dir)
    _validate_phase_configuration()
    run_root = run_dir.expanduser().resolve()
    if not run_root.is_dir():
        raise AnalyticalStoreError(f"Run directory is missing: {run_root}")
    backend = run_root / "Backend"
    manifest_path = backend / "manifests" / "run_manifest.json"
    execution_path = backend / "reports" / "execution_result.json"
    discovery_path = backend / "reports" / "discovery_selection.json"
    audit_path = backend / "reports" / "database_candidate_audit.json"
    reconciliation_path = backend / "reports" / "phase_reconciliation.csv"
    for required in (
        manifest_path,
        execution_path,
        discovery_path,
        audit_path,
        reconciliation_path,
    ):
        if not required.is_file():
            raise AnalyticalStoreError(f"Required run artifact is missing: {required}")

    manifest = _read_json(manifest_path)
    execution = _read_json(execution_path)
    discovery = _read_json(discovery_path)
    audit = _read_json(audit_path)
    run_id = str(manifest.get("run_id", "")).strip()
    site_code = str(manifest.get("site_code", "")).strip()
    run_status = str(execution.get("status", "")).strip()
    if not run_id or not site_code:
        raise AnalyticalStoreError("Run manifest is missing run_id or site_code.")
    if run_status not in {"PUBLISHED", "PARTIAL_PUBLISHED"}:
        raise AnalyticalStoreError(
            f"Only published or partial-published runs can be imported; found {run_status!r}."
        )
    selected_ids = [str(value) for value in discovery.get("selected_case_ids", [])]
    if not selected_ids or len(selected_ids) != len(set(selected_ids)):
        raise AnalyticalStoreError("Discovery selection must contain unique selected cases.")
    canonical_prefix = str(discovery.get("canonical_prefix", ""))
    if not canonical_prefix or any(not case_id.startswith(canonical_prefix) for case_id in selected_ids):
        raise AnalyticalStoreError("Selected cases do not satisfy the recorded canonical prefix.")
    execution_cases = _require_unique(
        list(execution.get("cases", [])), "case_id", context="execution result"
    )
    manifest_cases = _require_unique(
        list(manifest.get("case_results", [])), "case_id", context="run manifest"
    )
    audit_cases = _require_unique(list(audit.get("cases", [])), "case_id", context="candidate audit")
    if set(execution_cases) != set(selected_ids):
        raise AnalyticalStoreError("Execution cases do not match selected case IDs.")
    if set(manifest_cases) != set(selected_ids) or set(audit_cases) != set(selected_ids):
        raise AnalyticalStoreError("Manifest or database audit cases do not match selected case IDs.")

    slug = "".join(
        character.lower() if character.isalnum() else "_" for character in site_code
    ).strip("_")
    final_csv = run_root / "Report" / f"{slug}_timeline_analysis.csv"
    wide_rows = _read_csv(final_csv, WIDE_HEADERS)
    wide_by_case = _require_unique(wide_rows, "PtId", context="wide result")
    expected_wide_count = int(execution.get("exported_row_count", len(wide_rows)))
    if len(wide_rows) != expected_wide_count:
        raise AnalyticalStoreError("Wide result row count does not match execution result.")

    reconciliation_rows = _read_csv(
        reconciliation_path,
        (
            "case_id",
            "phase",
            "detailed_minutes_unrounded",
            "rollup_minutes",
            "difference_minutes",
            "status",
            "failure_type",
        ),
    )
    cases: list[PreparedCase] = []
    artifact_paths_for_fingerprint = [
        manifest_path,
        execution_path,
        discovery_path,
        audit_path,
        reconciliation_path,
        final_csv,
    ]
    for case_order, case_id in enumerate(selected_ids, start=1):
        execution_case = execution_cases[case_id]
        generated_case_id = str(execution_case.get("generated_case_id", case_id) or case_id)
        if generated_case_id != case_id:
            raise AnalyticalStoreError(f"Generated case identity mismatch for {case_id}.")
        failures = list(execution_case.get("failures", []))
        wide_row = wide_by_case.get(case_id)
        if wide_row is None:
            start_provenance_json = _canonical_json_text(
                execution_case.get("start_provenance", "{}"),
                context=f"{case_id} start provenance",
            )
            end_provenance_json = _canonical_json_text(
                execution_case.get("end_provenance", "{}"),
                context=f"{case_id} end provenance",
            )
            cases.append(
                PreparedCase(
                    case_id=case_id,
                    case_order=case_order,
                    experience="",
                    processing_status="FAIL",
                    final_row_included=False,
                    failure_reason=str(execution_case.get("failure_reason", "")),
                    failures_json=_canonical_json(failures),
                    start_timestamp_iso=str(execution_case.get("starttime", "") or ""),
                    end_timestamp_iso=str(execution_case.get("endtime", "") or ""),
                    start_provenance_json=start_provenance_json,
                    end_provenance_json=end_provenance_json,
                    validation_rows=[
                        {
                            "check_name": "pipeline_case_status",
                            "status": "FAIL",
                            "failure_type": "pipeline_case_failure",
                            "details_json": _canonical_json(failures),
                        }
                    ],
                )
            )
            continue
        if case_id not in manifest_cases or case_id not in audit_cases:
            raise AnalyticalStoreError(f"Successful case {case_id} lacks manifest or audit provenance.")
        manifest_case = manifest_cases[case_id]
        audit_case = audit_cases[case_id]
        usable = [row for row in audit_case.get("candidates", []) if row.get("usable")]
        if len(usable) != 1:
            raise AnalyticalStoreError(f"Successful case {case_id} does not have one usable source.")
        source_path = Path(str(manifest_case.get("source_path", ""))).expanduser().resolve()
        if not source_path.is_file():
            raise AnalyticalStoreError(f"Source database is unavailable for hashing: {source_path}")
        usable_path = Path(str(usable[0].get("candidate_path", ""))).expanduser().resolve()
        if source_path != usable_path:
            raise AnalyticalStoreError(f"Source provenance mismatch for {case_id}.")
        source_stat_before = source_path.stat()
        source_hash = _sha256_file(source_path)
        source_stat_after = source_path.stat()
        if (
            source_stat_before.st_size != source_stat_after.st_size
            or source_stat_before.st_mtime_ns != source_stat_after.st_mtime_ns
        ):
            raise AnalyticalStoreError(f"Source database changed while hashing: {source_path}")
        if int(usable[0].get("source_size_bytes", -1)) != source_stat_after.st_size:
            raise AnalyticalStoreError(f"Source size differs from candidate audit for {case_id}.")
        if int(usable[0].get("source_mtime_ns", -1)) != source_stat_after.st_mtime_ns:
            raise AnalyticalStoreError(f"Source mtime differs from candidate audit for {case_id}.")

        event_path = _artifact_path(
            str(manifest_case.get("state_labeled_export", "")),
            run_dir=run_root,
            context=f"{case_id} state-labeled event",
        )
        interval_path = _artifact_path(
            str(manifest_case.get("state_interval_export", "")),
            run_dir=run_root,
            context=f"{case_id} interval",
        )
        events = _read_csv(event_path, EVENT_FIELDS)
        intervals = _read_csv(interval_path, INTERVAL_FIELDS)
        _validate_case_artifacts(
            case_id=case_id,
            site_code=site_code,
            case_manifest=manifest_case,
            execution_case=execution_case,
            wide_row=wide_row,
            events=events,
            intervals=intervals,
        )
        artifact_paths_for_fingerprint.extend((event_path, interval_path))
        start_provenance_json = _canonical_json_text(
            execution_case.get("start_provenance", "{}"),
            context=f"{case_id} start provenance",
        )
        end_provenance_json = _canonical_json_text(
            execution_case.get("end_provenance", "{}"),
            context=f"{case_id} end provenance",
        )
        start_timestamp_iso = str(execution_case["starttime"])
        end_timestamp_iso = str(execution_case["endtime"])
        cases.append(
            PreparedCase(
                case_id=case_id,
                case_order=case_order,
                experience=str(wide_row.get("Experience", "")),
                processing_status="PASS" if not failures else "FAIL",
                final_row_included=True,
                failure_reason=str(execution_case.get("failure_reason", "")),
                failures_json=_canonical_json(failures),
                source_type=str(manifest_case.get("source_type", "")),
                source_path=str(source_path),
                source_archive_member=str(usable[0].get("zip_member", "") or ""),
                source_size_bytes=source_stat_after.st_size,
                source_mtime_ns=source_stat_after.st_mtime_ns,
                source_sha256=source_hash,
                analysis_artifact_fingerprint_sha256=_analysis_artifact_fingerprint(
                    start_timestamp_iso=start_timestamp_iso,
                    end_timestamp_iso=end_timestamp_iso,
                    start_provenance_json=start_provenance_json,
                    end_provenance_json=end_provenance_json,
                    events=events,
                    intervals=intervals,
                ),
                start_timestamp_iso=start_timestamp_iso,
                end_timestamp_iso=end_timestamp_iso,
                start_provenance_json=start_provenance_json,
                end_provenance_json=end_provenance_json,
                events=events,
                intervals=intervals,
                wide_snapshot=wide_row,
                validation_rows=_case_validation_rows(execution_case, failures),
            )
        )

    if set(wide_by_case) != {case.case_id for case in cases if case.final_row_included}:
        raise AnalyticalStoreError("Wide result contains cases outside the validated run selection.")
    known_cases = set(selected_ids)
    reconciliation_keys: set[tuple[str, str]] = set()
    for row in reconciliation_rows:
        if row["case_id"] not in known_cases:
            raise AnalyticalStoreError("Reconciliation row references an unknown case.")
        if row["phase"] not in PHASE_ORDER:
            raise AnalyticalStoreError("Reconciliation row references an unknown phase.")
        key = (row["case_id"], row["phase"])
        if key in reconciliation_keys:
            raise AnalyticalStoreError(f"Duplicate reconciliation row for {key!r}.")
        reconciliation_keys.add(key)
    expected_reconciliation_keys = {
        (case_id, phase) for case_id in selected_ids for phase in PHASE_ORDER
    }
    if reconciliation_keys != expected_reconciliation_keys:
        raise AnalyticalStoreError(
            "Reconciliation artifact must contain exactly one row per selected case and phase."
        )
    prepared_by_case = {case.case_id: case for case in cases}
    for row in reconciliation_rows:
        case = prepared_by_case[row["case_id"]]
        phase = row["phase"]
        detailed = _optional_float(
            row["detailed_minutes_unrounded"],
            context=f"{case.case_id}/{phase} detailed reconciliation",
        )
        rollup = _optional_float(
            row["rollup_minutes"], context=f"{case.case_id}/{phase} rollup reconciliation"
        )
        difference = _optional_float(
            row["difference_minutes"],
            context=f"{case.case_id}/{phase} reconciliation difference",
        )
        if case.final_row_included:
            expected_detailed = sum(
                float(interval["duration_sec"]) / 60.0
                for interval in case.intervals or []
                if interval.get("state", "") in PHASE_STATE_MAP[phase]
            )
            if detailed is None or abs(detailed - expected_detailed) > 1e-8:
                raise AnalyticalStoreError(
                    f"Detailed reconciliation total differs from intervals for {case.case_id}/{phase}."
                )
        if detailed is not None and rollup is not None:
            expected_difference = detailed - rollup
            if difference is None or abs(difference - expected_difference) > 1e-8:
                raise AnalyticalStoreError(
                    f"Reconciliation difference is inconsistent for {case.case_id}/{phase}."
                )
            if row["status"] == "PASS" and abs(difference) > 0.1 + 1e-9:
                raise AnalyticalStoreError(
                    f"Passing reconciliation exceeds tolerance for {case.case_id}/{phase}."
                )

    configuration = {
        "schema_version": 1,
        "year_selection": str(manifest.get("year_selection", "")),
        "canonical_prefix": str(discovery.get("canonical_prefix", "")),
        "requested_states": list(REQUESTED_STATES),
        "phase_order": list(PHASE_ORDER),
        "phase_state_map": {phase: list(PHASE_STATE_MAP[phase]) for phase in PHASE_ORDER},
    }
    configuration_json = _canonical_json(configuration)
    configuration_fingerprint = _sha256_bytes(configuration_json.encode("utf-8"))
    content_digest = hashlib.sha256()
    for path in sorted(set(artifact_paths_for_fingerprint), key=lambda item: str(item).casefold()):
        relative = str(path.relative_to(run_root)).replace("\\", "/")
        content_digest.update(relative.encode("utf-8"))
        content_digest.update(b"\0")
        content_digest.update(path.read_bytes())
        content_digest.update(b"\0")
    for case in cases:
        if case.final_row_included:
            content_digest.update(case.case_id.encode("utf-8"))
            content_digest.update(b"\0")
            content_digest.update(case.source_sha256.encode("ascii"))
            content_digest.update(b"\0")
    global_validations = [
        {
            "check_name": "run_publication_status",
            "status": "PASS",
            "failure_type": "",
            "details_json": _canonical_json({"run_status": run_status}),
        },
        {
            "check_name": "source_integrity",
            "status": "PASS",
            "failure_type": "",
            "details_json": _canonical_json({"sources_hashed": sum(case.final_row_included for case in cases)}),
        },
    ]
    return PreparedRun(
        run_id=run_id,
        site_code=site_code,
        run_status=run_status,
        started_at_utc=str(manifest.get("started_at", "")),
        completed_at_utc=str(manifest.get("completed_at", "")),
        run_dir=str(run_root),
        manifest_sha256=_sha256_file(manifest_path),
        import_fingerprint_sha256=content_digest.hexdigest().upper(),
        configuration_json=configuration_json,
        configuration_fingerprint_sha256=configuration_fingerprint,
        parser_version=parser_version or current_parser_version(),
        cases=cases,
        reconciliation_rows=reconciliation_rows,
        global_validation_rows=global_validations,
    )


def _get_or_create_parser(connection: sqlite3.Connection, parser: ParserVersion) -> int:
    row = connection.execute(
        "SELECT parser_version_id FROM parser_versions WHERE source_fingerprint_sha256 = ?",
        (parser.source_fingerprint_sha256,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute(
        """
        INSERT INTO parser_versions (
            package_version, git_commit, git_dirty, dirty_fingerprint_sha256,
            source_fingerprint_sha256, provenance_basis, created_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            parser.package_version,
            parser.git_commit,
            int(parser.git_dirty),
            parser.dirty_fingerprint_sha256,
            parser.source_fingerprint_sha256,
            parser.provenance_basis,
            _utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def _get_or_create_case(
    connection: sqlite3.Connection, site_code: str, case_id: str
) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO sites (site_code, first_seen_at_utc) VALUES (?, ?)",
        (site_code, _utc_now()),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO cases (site_code, case_id, first_seen_at_utc)
        VALUES (?, ?, ?)
        """,
        (site_code, case_id, _utc_now()),
    )
    row = connection.execute(
        "SELECT case_pk FROM cases WHERE site_code = ? AND case_id = ?",
        (site_code, case_id),
    ).fetchone()
    if row is None:
        raise AnalyticalStoreError(f"Could not resolve case identity {site_code}/{case_id}.")
    return int(row[0])


def _insert_events(
    connection: sqlite3.Connection, case_analysis_id: int, rows: list[dict[str, str]]
) -> None:
    values = []
    for ordinal, row in enumerate(rows, start=1):
        values.append(
            (
                case_analysis_id,
                ordinal,
                row["timestamp"],
                row["event_type"],
                row["source"],
                _bool_value(row["is_synthetic"], context="event is_synthetic"),
                row["segment_id"] or None,
                _optional_int(row["event_kind"]),
                row["state"] or None,
                row["state_assignment_rule"] or None,
                row["cleanup_rule_applied"] or None,
                row["drop_reason"] or None,
                _optional_int(row["row_number"]),
                row["source_detail"],
                row["insertion_rule"] or None,
                _validate_raw_json(row["raw_payload_json"], context="event insert"),
            )
        )
    connection.executemany(
        """
        INSERT INTO canonical_events (
            case_analysis_id, event_ordinal, timestamp_iso, event_type, source,
            is_synthetic, segment_id, event_kind, state, state_assignment_rule,
            cleanup_rule_applied, drop_reason, source_row_number, source_detail,
            insertion_rule, raw_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )


def _insert_intervals(
    connection: sqlite3.Connection, case_analysis_id: int, rows: list[dict[str, str]]
) -> None:
    values = []
    for ordinal, row in enumerate(rows, start=1):
        flags = [value for value in row["quality_flags"].split("|") if value]
        values.append(
            (
                case_analysis_id,
                ordinal,
                row["timestamp"],
                row["state"] or None,
                float(row["start_sec"]),
                float(row["duration_sec"]),
                row["rebase_anchor"] or None,
                row["origin_event_type"],
                row["source"],
                _bool_value(row["is_synthetic"], context="interval is_synthetic"),
                row["source_detail"],
                _optional_int(row["row_number"]),
                row["state_assignment_rule"] or None,
                row["cleanup_rule_applied"] or None,
                _canonical_json(flags),
                row["segment_id"] or None,
                _optional_int(row["event_kind"]),
                row["drop_reason"] or None,
                row["insertion_rule"] or None,
                _validate_raw_json(row["raw_payload_json"], context="interval insert"),
            )
        )
    connection.executemany(
        """
        INSERT INTO state_intervals (
            case_analysis_id, interval_ordinal, timestamp_iso, state, start_sec,
            duration_sec, rebase_anchor, origin_event_type, source, is_synthetic,
            source_detail, source_row_number, state_assignment_rule,
            cleanup_rule_applied, quality_flags_json, segment_id, event_kind,
            drop_reason, insertion_rule, raw_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )


def import_prepared_run(database: Path, prepared: PreparedRun) -> ImportSummary:
    """Persist one prevalidated run atomically with content-addressed reuse."""
    target = validate_database_path(database, run_dir=Path(prepared.run_dir))
    LOGGER.info("Importing validated run %s into %s", prepared.run_id, target)
    if not target.is_file():
        raise AnalyticalStoreError(
            f"Analytical database is not initialized: {target}. Run the init command first."
        )
    connection = _open_database(target)
    inserted_analyses = reused_analyses = inserted_events = inserted_intervals = 0
    try:
        _verify_schema(connection)
        existing = connection.execute(
            "SELECT import_fingerprint_sha256 FROM analysis_runs WHERE run_id = ?",
            (prepared.run_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] != prepared.import_fingerprint_sha256:
                raise AnalyticalStoreError(
                    f"Run ID {prepared.run_id} already exists with different content."
                )
            counts = connection.execute(
                """
                SELECT COUNT(*) AS run_cases,
                       SUM(final_row_included) AS successful_cases,
                       SUM(CASE WHEN final_row_included = 0 THEN 1 ELSE 0 END) AS failed_cases
                FROM run_cases WHERE run_id = ?
                """,
                (prepared.run_id,),
            ).fetchone()
            return ImportSummary(
                status="NOOP_ALREADY_IMPORTED",
                run_id=prepared.run_id,
                site_code=prepared.site_code,
                run_cases=int(counts["run_cases"] or 0),
                successful_cases=int(counts["successful_cases"] or 0),
                failed_cases=int(counts["failed_cases"] or 0),
                case_analyses_inserted=0,
                case_analyses_reused=int(counts["successful_cases"] or 0),
                events_inserted=0,
                intervals_inserted=0,
                reconciliation_rows=connection.execute(
                    "SELECT COUNT(*) FROM reconciliation_results WHERE run_id = ?",
                    (prepared.run_id,),
                ).fetchone()[0],
                database=str(target),
            )

        connection.execute("BEGIN IMMEDIATE")
        parser_id = _get_or_create_parser(connection, prepared.parser_version)
        connection.execute(
            "INSERT OR IGNORE INTO sites (site_code, first_seen_at_utc) VALUES (?, ?)",
            (prepared.site_code, _utc_now()),
        )
        connection.execute(
            """
            INSERT INTO analysis_runs (
                run_id, site_code, run_status, started_at_utc, completed_at_utc,
                run_dir, manifest_sha256, import_fingerprint_sha256,
                parser_version_id, configuration_json,
                configuration_fingerprint_sha256, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prepared.run_id,
                prepared.site_code,
                prepared.run_status,
                prepared.started_at_utc,
                prepared.completed_at_utc,
                prepared.run_dir,
                prepared.manifest_sha256,
                prepared.import_fingerprint_sha256,
                parser_id,
                prepared.configuration_json,
                prepared.configuration_fingerprint_sha256,
                _utc_now(),
            ),
        )
        case_pks: dict[str, int] = {}
        for case in prepared.cases:
            case_pk = _get_or_create_case(connection, prepared.site_code, case.case_id)
            case_pks[case.case_id] = case_pk
            case_analysis_id: int | None = None
            if case.final_row_included:
                row = connection.execute(
                    """
                    SELECT source_artifact_id FROM source_artifacts
                    WHERE case_pk = ? AND sha256 = ?
                    """,
                    (case_pk, case.source_sha256),
                ).fetchone()
                if row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO source_artifacts (
                            case_pk, source_type, archive_member, size_bytes, sha256,
                            first_path, first_mtime_ns, first_seen_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            case_pk,
                            case.source_type,
                            case.source_archive_member,
                            case.source_size_bytes,
                            case.source_sha256,
                            case.source_path,
                            case.source_mtime_ns,
                            _utc_now(),
                        ),
                    )
                    source_artifact_id = int(cursor.lastrowid)
                else:
                    source_artifact_id = int(row[0])
                row = connection.execute(
                    """
                    SELECT case_analysis_id, analysis_artifact_fingerprint_sha256
                    FROM case_analyses
                    WHERE source_artifact_id = ? AND parser_version_id = ?
                      AND configuration_fingerprint_sha256 = ?
                    """,
                    (
                        source_artifact_id,
                        parser_id,
                        prepared.configuration_fingerprint_sha256,
                    ),
                ).fetchone()
                if row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO case_analyses (
                            case_pk, source_artifact_id, parser_version_id,
                            configuration_fingerprint_sha256, status,
                            start_timestamp_iso, end_timestamp_iso,
                            start_provenance_json, end_provenance_json,
                            analysis_artifact_fingerprint_sha256, created_at_utc
                        ) VALUES (?, ?, ?, ?, 'PASS', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            case_pk,
                            source_artifact_id,
                            parser_id,
                            prepared.configuration_fingerprint_sha256,
                            case.start_timestamp_iso,
                            case.end_timestamp_iso,
                            case.start_provenance_json,
                            case.end_provenance_json,
                            case.analysis_artifact_fingerprint_sha256,
                            _utc_now(),
                        ),
                    )
                    case_analysis_id = int(cursor.lastrowid)
                    _insert_events(connection, case_analysis_id, case.events or [])
                    _insert_intervals(connection, case_analysis_id, case.intervals or [])
                    inserted_analyses += 1
                    inserted_events += len(case.events or [])
                    inserted_intervals += len(case.intervals or [])
                else:
                    case_analysis_id = int(row[0])
                    if row["analysis_artifact_fingerprint_sha256"] != (
                        case.analysis_artifact_fingerprint_sha256
                    ):
                        raise AnalyticalStoreError(
                            "Deterministic case-analysis conflict for "
                            f"{prepared.site_code}/{case.case_id}: identical source, parser, "
                            "and configuration produced different artifacts."
                        )
                    reused_analyses += 1
                connection.execute(
                    """
                    INSERT INTO source_observations (
                        run_id, case_pk, source_artifact_id, observed_path,
                        observed_source_type, observed_archive_member,
                        observed_size_bytes, observed_mtime_ns, observed_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prepared.run_id,
                        case_pk,
                        source_artifact_id,
                        case.source_path,
                        case.source_type,
                        case.source_archive_member,
                        case.source_size_bytes,
                        case.source_mtime_ns,
                        _utc_now(),
                    ),
                )
            connection.execute(
                """
                INSERT INTO run_cases (
                    run_id, case_pk, case_analysis_id, case_order, experience,
                    processing_status, final_row_included, start_timestamp_iso,
                    end_timestamp_iso, start_provenance_json, end_provenance_json,
                    failure_reason, failures_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.run_id,
                    case_pk,
                    case_analysis_id,
                    case.case_order,
                    case.experience,
                    case.processing_status,
                    int(case.final_row_included),
                    case.start_timestamp_iso,
                    case.end_timestamp_iso,
                    case.start_provenance_json,
                    case.end_provenance_json,
                    case.failure_reason,
                    case.failures_json,
                ),
            )
            if case.wide_snapshot is not None:
                row_json = _canonical_json(case.wide_snapshot)
                connection.execute(
                    """
                    INSERT INTO wide_result_snapshots (
                        run_id, case_pk, row_json, row_sha256
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (prepared.run_id, case_pk, row_json, _sha256_bytes(row_json.encode("utf-8"))),
                )
            for validation in case.validation_rows or []:
                connection.execute(
                    """
                    INSERT INTO validation_results (
                        run_id, case_pk, check_name, status, failure_type, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prepared.run_id,
                        case_pk,
                        validation["check_name"],
                        validation["status"],
                        validation["failure_type"],
                        validation["details_json"],
                    ),
                )
        for validation in prepared.global_validation_rows:
            connection.execute(
                """
                INSERT INTO validation_results (
                    run_id, case_pk, check_name, status, failure_type, details_json
                ) VALUES (?, NULL, ?, ?, ?, ?)
                """,
                (
                    prepared.run_id,
                    validation["check_name"],
                    validation["status"],
                    validation["failure_type"],
                    validation["details_json"],
                ),
            )
        for row in prepared.reconciliation_rows:
            case_pk = case_pks[row["case_id"]]
            connection.execute(
                """
                INSERT INTO reconciliation_results (
                    run_id, case_pk, phase, detailed_minutes_unrounded,
                    rollup_minutes, difference_minutes, status, failure_type,
                    details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared.run_id,
                    case_pk,
                    row["phase"],
                    float(row["detailed_minutes_unrounded"])
                    if row["detailed_minutes_unrounded"]
                    else None,
                    float(row["rollup_minutes"]) if row["rollup_minutes"] else None,
                    float(row["difference_minutes"]) if row["difference_minutes"] else None,
                    row["status"],
                    row["failure_type"],
                    _canonical_json(
                        {
                            "comparison_source": "imported_phase_reconciliation_artifact",
                            "detailed_intervals_are_authoritative": True,
                        }
                    ),
                ),
            )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    successful = sum(case.final_row_included for case in prepared.cases)
    return ImportSummary(
        status="IMPORTED",
        run_id=prepared.run_id,
        site_code=prepared.site_code,
        run_cases=len(prepared.cases),
        successful_cases=successful,
        failed_cases=len(prepared.cases) - successful,
        case_analyses_inserted=inserted_analyses,
        case_analyses_reused=reused_analyses,
        events_inserted=inserted_events,
        intervals_inserted=inserted_intervals,
        reconciliation_rows=len(prepared.reconciliation_rows),
        database=str(target),
    )


def import_run(
    database: Path,
    run_dir: Path,
    *,
    parser_version: ParserVersion | None = None,
) -> ImportSummary:
    validate_database_path(database, run_dir=run_dir)
    prepared = prepare_run_import(run_dir, parser_version=parser_version)
    return import_prepared_run(database, prepared)


def _export_row_from_view(row: sqlite3.Row) -> dict[str, str]:
    exported = {
        "Experience": str(row["experience"]),
        "Site": str(row["site"]),
        "PtId": str(row["case_id"]),
        "starttime": _clock(str(row["start_timestamp_iso"])),
        "endtime": _clock(str(row["end_timestamp_iso"])),
    }
    for state in REQUESTED_STATES:
        exported[state] = f"{max(0.0, float(row[state])):.1f}"
    return exported


def _csv_text(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=WIDE_HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def export_wide(database: Path, run_id: str, output: Path) -> dict[str, Any]:
    """Export the public 20-column CSV from SQL interval aggregates."""
    target = validate_database_path(database)
    LOGGER.info("Exporting SQL-backed wide result for run %s", run_id)
    if not target.is_file():
        raise AnalyticalStoreError(f"Analytical database is missing: {target}")
    connection = _open_database(target, read_only=True)
    try:
        _verify_schema(connection)
        run = connection.execute(
            "SELECT run_id, site_code, run_status FROM analysis_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise AnalyticalStoreError(f"Run ID is not present in the store: {run_id}")
        rows = connection.execute(
            "SELECT * FROM v_run_case_wide WHERE run_id = ? ORDER BY case_order, case_id",
            (run_id,),
        ).fetchall()
        exported = [_export_row_from_view(row) for row in rows]
        snapshots = {
            row["case_id"]: json.loads(row["row_json"])
            for row in connection.execute(
                """
                SELECT c.case_id, wrs.row_json
                FROM wide_result_snapshots wrs
                JOIN cases c ON c.case_pk = wrs.case_pk
                WHERE wrs.run_id = ?
                """,
                (run_id,),
            ).fetchall()
        }
        for row in exported:
            snapshot = snapshots.get(row["PtId"])
            comparable = dict(snapshot) if snapshot is not None else None
            if comparable is not None:
                comparable["starttime"] = row["starttime"]
                comparable["endtime"] = row["endtime"]
            if comparable != row:
                raise AnalyticalStoreError(
                    f"SQL-derived export differs from imported snapshot for {row['PtId']}."
                )
    finally:
        connection.close()
    output_path = output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(_csv_text(exported), encoding="utf-8", newline="")
    temporary.replace(output_path)
    return {
        "run_id": run_id,
        "site_code": str(run["site_code"]),
        "run_status": str(run["run_status"]),
        "row_count": len(exported),
        "output": str(output_path),
    }


def list_runs(database: Path) -> list[dict[str, Any]]:
    target = validate_database_path(database)
    if not target.is_file():
        raise AnalyticalStoreError(f"Analytical database is missing: {target}")
    connection = _open_database(target, read_only=True)
    try:
        _verify_schema(connection)
        return [dict(row) for row in connection.execute(
            """
            SELECT ar.run_id, ar.site_code, ar.run_status, ar.started_at_utc,
                   ar.completed_at_utc, ar.imported_at_utc,
                   vrs.case_count, vrs.published_case_count, vrs.failed_case_count
            FROM analysis_runs ar
            JOIN v_run_status vrs ON vrs.run_id = ar.run_id
            ORDER BY ar.started_at_utc, ar.run_id
            """
        ).fetchall()]
    finally:
        connection.close()


def _write_optional_json(payload: Any, path: Path | None) -> None:
    if path is None:
        return
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize, import, inspect, and export the Timeline Analysis SQLite store."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="Create or verify schema v1.")
    init_parser.add_argument("--database", required=True, type=Path)

    import_parser = subparsers.add_parser("import-run", help="Validate and import one published run.")
    import_parser.add_argument("--database", required=True, type=Path)
    import_parser.add_argument("--run-dir", required=True, type=Path)
    import_parser.add_argument("--report-json", type=Path)

    export_parser = subparsers.add_parser("export-wide", help="Export the 20-column CSV from SQL.")
    export_parser.add_argument("--database", required=True, type=Path)
    export_parser.add_argument("--run-id", required=True)
    export_parser.add_argument("--output", required=True, type=Path)

    list_parser = subparsers.add_parser("list-runs", help="List imported historical runs.")
    list_parser.add_argument("--database", required=True, type=Path)
    list_parser.add_argument("--report-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            path = initialize_database(args.database)
            payload = {"status": "READY", "schema_version": SCHEMA_VERSION, "database": str(path)}
        elif args.command == "import-run":
            payload = import_run(args.database, args.run_dir).to_dict()
            _write_optional_json(payload, args.report_json)
        elif args.command == "export-wide":
            payload = export_wide(args.database, args.run_id, args.output)
        elif args.command == "list-runs":
            payload = {"database": str(args.database.expanduser().resolve()), "runs": list_runs(args.database)}
            _write_optional_json(payload, args.report_json)
        else:  # pragma: no cover - argparse enforces a known command
            raise AnalyticalStoreError(f"Unsupported command: {args.command}")
    except (AnalyticalStoreError, OSError, sqlite3.Error) as exc:
        print(f"Timeline analytical store failed: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
