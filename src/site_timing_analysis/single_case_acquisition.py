# Project: Site Timing Analysis
# File: src/site_timing_analysis/single_case_acquisition.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Safely acquires and validates one explicitly selected local.db from a commercial Sync.com share.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Single-case, read-only ``local.db`` acquisition validation.

This module deliberately does not modify or import the existing application-log
planner. The live CLI loads the separately maintained ``sync-tdc-logs`` client
only as a transport, then matches one exact case folder and selects one
``local.db`` from its timestamped session-folder children.

Inputs
------
An explicit three-digit site ID, explicit case ID, external ``sites.json``,
destination root, and the separately maintained Sync client package.

Outputs
-------
On success, ``<destination>/<case_id>/local.db`` and a JSON result report. A
download is promoted from staging only after read-only SQLite validation.

Assumptions and limitations
---------------------------
Direct ``local.db`` files are preferred. Optional session-export ZIP fallback is
available only when no direct database exists. Scalable bulk acquisition remains
deferred. Remote ambiguity is quarantined logically; invalid downloaded bytes
are moved beneath ``<destination>/_quarantine`` and are never published as a
valid database.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib
import json
import logging
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from typing import Any, Callable
from urllib.parse import urlparse
import zipfile


LOGGER = logging.getLogger(__name__)

SESSION_ROOT_DIRS = ("TDC Data", "TDC Sessions", "TDC Session")
REQUIRED_TABLES = ("AuditLogRecords", "Sessions", "Treatments")
REQUIRED_COLUMNS = {
    "AuditLogRecords": ("TreatmentId",),
    "Treatments": ("Id", "SessionId"),
    "Sessions": ("Id",),
}
_SITE_ID_RE = re.compile(r"^\d{3}$")
_SAFE_CASE_ID_RE = re.compile(r"^[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*$")
_TIMESTAMPED_SESSION_DIR_RE = re.compile(
    r"^_?(?P<timestamp>\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2})(?:\s+\d+)?$"
)


class AcquisitionConfigurationError(RuntimeError):
    """Raised when explicit acquisition configuration is missing or unsafe."""


@dataclass
class AcquisitionResult:
    """Machine-readable outcome for one requested case acquisition."""

    status: str
    reason_code: str
    reason: str
    site: str
    case_id: str
    started_at_utc: str
    completed_at_utc: str
    source_access_mode: str = "read_only"
    remote_container: str = ""
    remote_case_folder: str = ""
    remote_session_folder: str = ""
    remote_archive_name: str = ""
    remote_database_name: str = ""
    remote_artifact_size_bytes: int = 0
    remote_artifact_usertime: int = 0
    saved_path: str = ""
    quarantine_path: str = ""
    size_bytes: int = 0
    sha256: str = ""
    database_validation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable report representation."""
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_explicit_selection(site: str, case_id: str) -> None:
    """Reject unsafe or non-explicit identifiers before any network access."""
    if not _SITE_ID_RE.fullmatch(site):
        raise AcquisitionConfigurationError(
            f"Site must be one explicit three-digit ID; received {site!r}."
        )
    if not _SAFE_CASE_ID_RE.fullmatch(case_id):
        raise AcquisitionConfigurationError(
            "Case ID may contain only letters, numbers, underscores, and hyphens; "
            f"received {case_id!r}."
        )


def validate_sync_url(url: str) -> str:
    """Validate and return one HTTPS Sync.com share URL without exposing it."""
    parsed = urlparse(str(url).strip())
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    allowed_host = hostname == "sync.com" or hostname.endswith(".sync.com")
    if parsed.scheme.casefold() != "https" or not allowed_host:
        raise AcquisitionConfigurationError(
            "The configured site URL must use HTTPS on sync.com or a sync.com subdomain."
        )
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise AcquisitionConfigurationError(
            "The configured Sync.com URL contains unsupported authority components."
        )
    if not re.search(r"/(?:\d+(?:\.\d+)*/)?dl/", parsed.path, flags=re.IGNORECASE):
        raise AcquisitionConfigurationError(
            "The configured site URL is not a recognized Sync.com /dl/ share link."
        )
    return str(url).strip()


def load_site_entry(sites_file: Path, site: str) -> dict[str, Any]:
    """Load exactly one configured site from a credential-bearing JSON file."""
    path = sites_file.expanduser().resolve()
    if not path.is_file():
        raise AcquisitionConfigurationError(f"Sites configuration not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionConfigurationError(
            f"Could not read sites configuration {path}: {exc}"
        ) from exc
    sites = payload.get("sites")
    if not isinstance(sites, dict) or site not in sites:
        raise AcquisitionConfigurationError(
            f"Explicit site {site!r} is not present in {path}."
        )
    entry = sites[site]
    if not isinstance(entry, dict):
        raise AcquisitionConfigurationError(
            f"Configuration for site {site!r} must be a JSON object."
        )
    result = dict(entry)
    result["url"] = validate_sync_url(str(result.get("url", "")))
    return result


def _sync_tool_zip_import_path(tool_zip: Path) -> str:
    """Return the package-parent import path for one ProfoundTools ZIP."""
    archive_path = tool_zip.expanduser().resolve()
    if not archive_path.is_file():
        raise AcquisitionConfigurationError(f"Sync tool ZIP not found: {archive_path}")
    suffix = "sync_tdc_logs/synclink.py"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                name
                for name in archive.namelist()
                if name.replace("\\", "/").endswith(suffix)
            ]
    except (OSError, zipfile.BadZipFile) as exc:
        raise AcquisitionConfigurationError(
            f"Could not inspect Sync tool ZIP {archive_path}: {exc}"
        ) from exc
    if len(matches) != 1:
        raise AcquisitionConfigurationError(
            "Expected exactly one sync_tdc_logs/synclink.py in the Sync tool ZIP; "
            f"found {len(matches)}."
        )
    normalized = matches[0].replace("\\", "/")
    package_parent = normalized[: -len(suffix)].rstrip("/")
    return f"{archive_path}/{package_parent}"


def _load_sync_client(
    tool_root: Path | None,
    tool_zip: Path | None,
) -> tuple[Any, Callable[[], str], Callable[[str], str | None]]:
    """Load the separately maintained Sync client and credential provider.

    ``tool_root`` must be the directory containing ``sync_tdc_logs``. The import
    is lazy so normal Timeline Analysis and unit tests do not require the
    optional network/cryptography dependencies.
    """
    if tool_root is not None and tool_zip is not None:
        raise AcquisitionConfigurationError(
            "Pass only one of --sync-tool-root or --sync-tool-zip."
        )
    if tool_root is not None:
        resolved = tool_root.expanduser().resolve()
        if not (resolved / "sync_tdc_logs" / "synclink.py").is_file():
            raise AcquisitionConfigurationError(
                "--sync-tool-root must contain sync_tdc_logs/synclink.py; "
                f"received {resolved}."
            )
        root_text = str(resolved)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
    elif tool_zip is not None:
        zip_import_path = _sync_tool_zip_import_path(tool_zip)
        if zip_import_path not in sys.path:
            sys.path.insert(0, zip_import_path)
    try:
        synclink = importlib.import_module("sync_tdc_logs.synclink")
        credentials = importlib.import_module("sync_tdc_logs.credentials")
        sessions = importlib.import_module("sync_tdc_logs.sessions")
    except (ImportError, ModuleNotFoundError) as exc:
        raise AcquisitionConfigurationError(
            "Could not load sync-tdc-logs or its optional dependencies. Install "
            "the acquisition dependency group and pass --sync-tool-root. "
            f"Original error: {exc}"
        ) from exc
    return synclink.SyncLink, credentials.load, sessions.session_key


def _result(
    *,
    status: str,
    reason_code: str,
    reason: str,
    site: str,
    case_id: str,
    started_at_utc: str,
    **kwargs: Any,
) -> AcquisitionResult:
    return AcquisitionResult(
        status=status,
        reason_code=reason_code,
        reason=reason,
        site=site,
        case_id=case_id,
        started_at_utc=started_at_utc,
        completed_at_utc=_utc_now(),
        **kwargs,
    )


def _safe_exception_text(exc: Exception) -> str:
    """Return an exception description with URLs and signed fields redacted."""
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"https?://[^\s)\]}]+", "<redacted-url>", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\b(password|pltoken|datakey|signature|cachekey)=([^\s&]+)",
        r"\1=<redacted>",
        text,
    )
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _quoted_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalized_case_identity(value: str) -> str:
    """Normalize case-ID separators without exposing an internal patient value."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_").casefold()


def _validate_database_case_identity(
    connection: sqlite3.Connection,
    tables: set[str],
    columns_by_table: dict[str, set[str]],
    expected_case_id: str,
) -> dict[str, Any]:
    """Compare nonempty database case identifiers without reporting raw values.

    The commercial databases commonly encode the case ID in ``PatientId`` with
    different punctuation from the source-folder convention. Comparison is
    therefore case-insensitive and separator-insensitive, but otherwise exact.
    Missing identity values are reported as unavailable rather than fabricated.
    """
    checked_fields: list[str] = []
    normalized_values: set[str] = set()
    nonempty_rows = 0
    for table in ("Sessions", "AuditLogRecords"):
        if table not in tables or "PatientId" not in columns_by_table.get(table, set()):
            continue
        checked_fields.append(f"{table}.PatientId")
        for row in connection.execute(
            f"SELECT PatientId FROM {_quoted_identifier(table)} "
            "WHERE PatientId IS NOT NULL AND TRIM(PatientId) <> ''"
        ):
            nonempty_rows += 1
            normalized = _normalized_case_identity(str(row[0]))
            if normalized:
                normalized_values.add(normalized)

    expected_normalized = _normalized_case_identity(expected_case_id)
    if not normalized_values:
        status = "NOT_AVAILABLE"
        reason = "No nonempty PatientId value is available in the checked tables."
    elif len(normalized_values) != 1:
        status = "FAIL"
        reason = "Database PatientId fields contain multiple normalized identities."
    elif normalized_values != {expected_normalized}:
        status = "FAIL"
        reason = "Database PatientId does not match the selected case ID."
    else:
        status = "PASS"
        reason = "Database PatientId matches the selected case ID after separator normalization."

    return {
        "status": status,
        "reason": reason,
        "comparison_rule": "case-insensitive exact match after separator normalization",
        "expected_case_id": expected_case_id,
        "fields_checked": checked_fields,
        "nonempty_rows": nonempty_rows,
        "distinct_normalized_values": len(normalized_values),
    }


def validate_downloaded_database(
    path: Path,
    *,
    expected_case_id: str | None = None,
    require_case_identity: bool = False,
) -> dict[str, Any]:
    """Validate a downloaded database read-only and return identity/schema facts."""
    validation: dict[str, Any] = {
        "status": "FAIL",
        "sqlite_header_valid": False,
        "integrity_check": "",
        "tables": [],
        "missing_required_tables": [],
        "missing_required_columns": {},
        "row_counts": {},
        "auditlog_treatment_orphans": None,
        "treatment_session_orphans": None,
        "case_identity": {},
        "error": "",
    }
    try:
        with path.open("rb") as handle:
            validation["sqlite_header_valid"] = handle.read(16) == b"SQLite format 3\x00"
    except OSError as exc:
        validation["error"] = f"database_read_failed:{exc}"
        return validation
    if not validation["sqlite_header_valid"]:
        validation["error"] = "invalid_sqlite_header"
        return validation

    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        validation["error"] = f"database_open_failed:{exc}"
        return validation

    try:
        connection.execute("PRAGMA query_only = ON")
        validation["integrity_check"] = str(
            connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        tables = sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        )
        validation["tables"] = tables
        missing_tables = sorted(set(REQUIRED_TABLES).difference(tables))
        validation["missing_required_tables"] = missing_tables

        missing_columns: dict[str, list[str]] = {}
        columns_by_table: dict[str, set[str]] = {}
        for table, required_columns in REQUIRED_COLUMNS.items():
            if table not in tables:
                continue
            columns = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({_quoted_identifier(table)})"
                )
            }
            columns_by_table[table] = columns
            missing = sorted(set(required_columns).difference(columns))
            if missing:
                missing_columns[table] = missing
        validation["missing_required_columns"] = missing_columns

        if not missing_tables and not missing_columns:
            validation["row_counts"] = {
                table: int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {_quoted_identifier(table)}"
                    ).fetchone()[0]
                )
                for table in REQUIRED_TABLES
            }
            validation["auditlog_treatment_orphans"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM AuditLogRecords a "
                    "LEFT JOIN Treatments t ON a.TreatmentId=t.Id "
                    "WHERE a.TreatmentId IS NOT NULL AND t.Id IS NULL"
                ).fetchone()[0]
            )
            validation["treatment_session_orphans"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM Treatments t "
                    "LEFT JOIN Sessions s ON t.SessionId=s.Id "
                    "WHERE t.SessionId IS NOT NULL AND s.Id IS NULL"
                ).fetchone()[0]
            )
        if expected_case_id is not None:
            validation["case_identity"] = _validate_database_case_identity(
                connection,
                set(tables),
                columns_by_table,
                expected_case_id,
            )
    except sqlite3.Error as exc:
        validation["error"] = f"database_validation_failed:{exc}"
        return validation
    finally:
        connection.close()

    failures: list[str] = []
    if validation["integrity_check"].casefold() != "ok":
        failures.append("integrity_check_failed")
    if validation["missing_required_tables"]:
        failures.append("missing_required_tables")
    if validation["missing_required_columns"]:
        failures.append("missing_required_columns")
    if validation["auditlog_treatment_orphans"]:
        failures.append("auditlog_treatment_orphans")
    if validation["treatment_session_orphans"]:
        failures.append("treatment_session_orphans")
    if validation["case_identity"].get("status") == "FAIL":
        failures.append("case_identity_mismatch")
    elif require_case_identity and validation["case_identity"].get("status") != "PASS":
        failures.append("case_identity_unverified")
    validation["error"] = ";".join(failures)
    validation["status"] = "PASS" if not failures else "FAIL"
    return validation


def _move_to_quarantine(source: Path, quarantine_root: Path) -> Path:
    """Move one invalid staged artifact without overwriting prior evidence."""
    quarantine_root.mkdir(parents=True, exist_ok=True)
    target = quarantine_root / source.name
    index = 1
    while target.exists():
        target = quarantine_root / f"{source.stem}_{index}{source.suffix}"
        index += 1
    source.replace(target)
    return target.resolve()


def _timestamp_token(folder_name: str) -> str | None:
    """Return a validated session timestamp token from one remote folder name."""
    match = _TIMESTAMPED_SESSION_DIR_RE.fullmatch(folder_name.strip())
    if match is None:
        return None
    token = match.group("timestamp")
    try:
        datetime.strptime(token, "%Y-%m-%d--%H-%M-%S")
    except ValueError:
        return None
    return token


def _extract_single_local_db(archive_path: Path, target_path: Path) -> tuple[str, int]:
    """Extract exactly one case-insensitive ``local.db`` member to a fixed path.

    No archive-provided path is used for output, which prevents path traversal.
    The caller owns quarantine handling for a malformed or ambiguous archive.
    """
    with zipfile.ZipFile(archive_path) as archive:
        matches = [
            item
            for item in archive.infolist()
            if not item.is_dir()
            and item.filename.replace("\\", "/").rsplit("/", 1)[-1].casefold()
            == "local.db"
        ]
        if len(matches) != 1:
            raise AcquisitionConfigurationError(
                "Expected exactly one local.db member in session-export ZIP; "
                f"found {len(matches)}."
            )
        member = matches[0]
        if member.file_size <= 0:
            raise AcquisitionConfigurationError(
                f"Session-export ZIP member {member.filename!r} is empty."
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member, "r") as source, target_path.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        actual_size = target_path.stat().st_size
        if actual_size != member.file_size:
            raise AcquisitionConfigurationError(
                "Extracted local.db size does not match the session-export ZIP "
                f"metadata: expected {member.file_size}, got {actual_size}."
            )
        return member.filename, actual_size


def acquire_single_case(
    *,
    link: Any,
    site: str,
    case_id: str,
    destination: Path,
    session_key: Callable[[str], str | None],
    allow_session_zip_fallback: bool = False,
    require_case_identity: bool = False,
) -> AcquisitionResult:
    """Acquire one ``local.db`` from one exact case and timestamped session.

    The supplied ``link`` is an already authenticated read-only Sync client. No
    source mutation method is called. Domain failures return explicit result
    records so the CLI can always write a diagnostic report. Session-export ZIP
    fallback is opt-in and is considered only when no direct database exists.
    """
    started = _utc_now()
    _validate_explicit_selection(site, case_id)
    destination = destination.expanduser().resolve()
    final_path = destination / case_id / "local.db"
    staging_path = destination / "_staging" / case_id / "local.db"
    staging_archive_path = destination / "_staging" / case_id / "session-export.zip"
    quarantine_root = destination / "_quarantine" / case_id

    if final_path.exists():
        return _result(
            status="quarantined",
            reason_code="destination_already_exists",
            reason=f"Refusing to overwrite existing destination: {final_path}",
            site=site,
            case_id=case_id,
            started_at_utc=started,
        )
    staging_artifacts = (
        staging_path,
        Path(str(staging_path) + ".part"),
        staging_archive_path,
        Path(str(staging_archive_path) + ".part"),
    )
    existing_staging = [path for path in staging_artifacts if path.exists()]
    if existing_staging:
        return _result(
            status="quarantined",
            reason_code="staging_artifact_already_exists",
            reason=f"Refusing to reuse existing staging artifact beneath {staging_path.parent}",
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=[str(path) for path in existing_staging],
        )

    try:
        root_items = link.listdir(link.root_sync_id)
        wanted = {name.casefold() for name in SESSION_ROOT_DIRS}
        containers = sorted(
            [
                item
                for item in root_items
                if item.is_dir and item.name.strip().casefold() in wanted
            ],
            key=lambda item: item.name.casefold(),
        )
    except Exception as exc:  # noqa: BLE001 - external transport boundary
        return _result(
            status="failed",
            reason_code="remote_root_listing_failed",
            reason=_safe_exception_text(exc),
            site=site,
            case_id=case_id,
            started_at_utc=started,
        )

    expected_case_folder = f"{case_id} TDC Sessions"
    exact_matches: list[tuple[str, Any]] = []
    related_matches: list[str] = []

    def collect_case_matches(parent_name: str, items: list[Any]) -> None:
        for item in items:
            if not item.is_dir:
                continue
            normalized = item.name.strip()
            remote_path = f"{parent_name}/{item.name}"
            if normalized == expected_case_folder:
                exact_matches.append((parent_name, item))
            elif session_key(normalized) == case_id:
                related_matches.append(remote_path)

    collect_case_matches("<share-root>", root_items)
    try:
        for container in containers:
            collect_case_matches(container.name, link.listdir(container.sync_id))
    except Exception as exc:  # noqa: BLE001 - external transport boundary
        return _result(
            status="failed",
            reason_code="remote_case_folder_discovery_failed",
            reason=_safe_exception_text(exc),
            site=site,
            case_id=case_id,
            started_at_utc=started,
        )
    match_paths = [f"{parent}/{folder.name}" for parent, folder in exact_matches]
    if len(exact_matches) != 1:
        code = "missing_exact_case_folder" if not exact_matches else "ambiguous_exact_case_folders"
        return _result(
            status="quarantined",
            reason_code=code,
            reason=(
                f"Expected exactly one remote folder named {expected_case_folder!r}; "
                f"found {len(exact_matches)}."
            ),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=match_paths + related_matches,
        )
    if related_matches:
        return _result(
            status="quarantined",
            reason_code="conflicting_case_folders",
            reason=(
                f"The exact case folder {expected_case_folder!r} exists, but "
                f"{len(related_matches)} additional folder(s) resolve to {case_id}."
            ),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=match_paths + related_matches,
        )

    container_name, case_folder = exact_matches[0]
    case_context = {
        "remote_container": container_name,
        "remote_case_folder": case_folder.name,
    }
    try:
        case_items = link.listdir(case_folder.sync_id)
    except Exception as exc:  # noqa: BLE001 - external transport boundary
        return _result(
            status="failed",
            reason_code="remote_case_listing_failed",
            reason=_safe_exception_text(exc),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            **case_context,
        )

    timestamped_folders: list[tuple[Any, str]] = []
    unexpected_case_directories: list[str] = []
    ignored_case_files: list[str] = []
    for item in case_items:
        normalized = item.name.strip()
        if normalized.casefold() == "applog":
            continue
        if item.is_dir:
            token = _timestamp_token(normalized)
            if token is None:
                unexpected_case_directories.append(item.name)
            else:
                timestamped_folders.append((item, token))
        else:
            ignored_case_files.append(item.name)
    timestamped_folders.sort(key=lambda pair: pair[0].name.casefold())

    if unexpected_case_directories:
        return _result(
            status="quarantined",
            reason_code="unexpected_case_subdirectories",
            reason=(
                f"Case folder {case_folder.name!r} contains non-applog directory "
                "children that do not match the timestamped session-folder format."
            ),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=sorted(unexpected_case_directories, key=str.casefold),
            **case_context,
        )
    if not timestamped_folders:
        return _result(
            status="quarantined",
            reason_code="missing_timestamped_session_folder",
            reason=f"No timestamped session folder exists beneath {case_folder.name!r}.",
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=sorted(ignored_case_files, key=str.casefold),
            **case_context,
        )

    direct_candidates: list[tuple[Any, Any]] = []
    session_export_candidates: list[tuple[Any, Any]] = []
    conflicting_database_paths: list[str] = []
    try:
        for session_folder, _token in timestamped_folders:
            session_items = link.listdir(session_folder.sync_id)
            local_databases = sorted(
                [
                    item
                    for item in session_items
                    if not item.is_dir and item.name.strip().casefold() == "local.db"
                ],
                key=lambda item: (item.name.casefold(), item.sync_id),
            )
            if len(local_databases) > 1:
                conflicting_database_paths.extend(
                    f"{session_folder.name}/{item.name}" for item in local_databases
                )
            elif len(local_databases) == 1:
                direct_candidates.append((session_folder, local_databases[0]))

            session_export_candidates.extend(
                (session_folder, item)
                for item in session_items
                if not item.is_dir
                and item.name.strip().casefold().endswith(".zip")
                and item.name.strip().casefold() != "raw.zip"
            )
    except Exception as exc:  # noqa: BLE001 - external transport boundary
        return _result(
            status="failed",
            reason_code="remote_timestamped_session_listing_failed",
            reason=_safe_exception_text(exc),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            **case_context,
        )

    if conflicting_database_paths:
        return _result(
            status="quarantined",
            reason_code="conflicting_direct_local_db",
            reason="At least one timestamped session folder contains multiple local.db files.",
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=sorted(conflicting_database_paths, key=str.casefold),
            **case_context,
        )
    if len(direct_candidates) > 1:
        return _result(
            status="quarantined",
            reason_code="ambiguous_direct_local_db",
            reason=(
                "Multiple timestamped session folders contain a direct local.db; "
                "refusing to guess."
            ),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            warnings=sorted(
                [f"{folder.name}/{item.name}" for folder, item in direct_candidates],
                key=str.casefold,
            ),
            **case_context,
        )

    database_item: Any | None = None
    archive_item: Any | None = None
    if direct_candidates:
        session_folder, database_item = direct_candidates[0]
    else:
        archive_paths = sorted(
            [f"{folder.name}/{item.name}" for folder, item in session_export_candidates],
            key=str.casefold,
        )
        if not allow_session_zip_fallback:
            return _result(
                status="quarantined",
                reason_code="missing_direct_local_db",
                reason=(
                    "No timestamped session folder contains a direct local.db; "
                    "session-export ZIP fallback was not enabled."
                ),
                site=site,
                case_id=case_id,
                started_at_utc=started,
                warnings=archive_paths,
                **case_context,
            )
        if len(session_export_candidates) != 1:
            code = (
                "missing_session_export_zip"
                if not session_export_candidates
                else "ambiguous_session_export_zips"
            )
            return _result(
                status="quarantined",
                reason_code=code,
                reason=(
                    "Direct local.db is absent and ZIP fallback requires exactly "
                    f"one non-Raw session-export ZIP; found {len(session_export_candidates)}."
                ),
                site=site,
                case_id=case_id,
                started_at_utc=started,
                warnings=archive_paths,
                **case_context,
            )
        session_folder, archive_item = session_export_candidates[0]

    selected_remote_artifact = database_item if database_item is not None else archive_item
    context = {
        **case_context,
        "remote_session_folder": session_folder.name,
        "remote_archive_name": archive_item.name if archive_item is not None else "",
        "remote_database_name": database_item.name if database_item is not None else "local.db",
        "remote_artifact_size_bytes": int(
            getattr(selected_remote_artifact, "size", 0) or 0
        ),
        "remote_artifact_usertime": int(
            getattr(selected_remote_artifact, "usertime", 0) or 0
        ),
    }

    staging_path.parent.mkdir(parents=True, exist_ok=True)
    if database_item is not None:
        try:
            bytes_written = int(link.download(database_item, str(staging_path)))
        except Exception as exc:  # noqa: BLE001 - external transport boundary
            partial = Path(str(staging_path) + ".part")
            quarantine_path = ""
            artifact = staging_path if staging_path.exists() else partial if partial.exists() else None
            if artifact is not None:
                quarantine_path = str(_move_to_quarantine(artifact, quarantine_root))
            return _result(
                status="failed",
                reason_code="download_failed",
                reason=_safe_exception_text(exc),
                site=site,
                case_id=case_id,
                started_at_utc=started,
                quarantine_path=quarantine_path,
                **context,
            )
        actual_size = staging_path.stat().st_size
        expected_size = int(getattr(database_item, "size", 0) or 0)
    else:
        try:
            archive_bytes_written = int(link.download(archive_item, str(staging_archive_path)))
        except Exception as exc:  # noqa: BLE001 - external transport boundary
            partial = Path(str(staging_archive_path) + ".part")
            quarantine_path = ""
            artifact = (
                staging_archive_path
                if staging_archive_path.exists()
                else partial
                if partial.exists()
                else None
            )
            if artifact is not None:
                quarantine_path = str(_move_to_quarantine(artifact, quarantine_root))
            return _result(
                status="failed",
                reason_code="session_export_download_failed",
                reason=_safe_exception_text(exc),
                site=site,
                case_id=case_id,
                started_at_utc=started,
                quarantine_path=quarantine_path,
                **context,
            )
        archive_actual_size = staging_archive_path.stat().st_size
        archive_expected_size = int(getattr(archive_item, "size", 0) or 0)
        if archive_bytes_written != archive_actual_size or (
            archive_expected_size and archive_expected_size != archive_actual_size
        ):
            quarantined = _move_to_quarantine(staging_archive_path, quarantine_root)
            return _result(
                status="quarantined",
                reason_code="session_export_download_size_mismatch",
                reason=(
                    "Session-export ZIP size mismatch: API wrote "
                    f"{archive_bytes_written}, local size {archive_actual_size}, "
                    f"remote listing {archive_expected_size}."
                ),
                site=site,
                case_id=case_id,
                started_at_utc=started,
                quarantine_path=str(quarantined),
                size_bytes=archive_actual_size,
                sha256=_sha256(quarantined),
                **context,
            )
        try:
            member_name, _member_size = _extract_single_local_db(
                staging_archive_path,
                staging_path,
            )
            context["remote_database_name"] = member_name
        except Exception as exc:  # noqa: BLE001 - archive validation boundary
            quarantined_paths: list[str] = []
            if staging_path.exists():
                quarantined_paths.append(str(_move_to_quarantine(staging_path, quarantine_root)))
            if staging_archive_path.exists():
                quarantined_paths.append(
                    str(_move_to_quarantine(staging_archive_path, quarantine_root))
                )
            return _result(
                status="quarantined",
                reason_code="invalid_or_ambiguous_session_export_zip",
                reason=_safe_exception_text(exc),
                site=site,
                case_id=case_id,
                started_at_utc=started,
                quarantine_path=quarantined_paths[0] if quarantined_paths else "",
                warnings=quarantined_paths[1:],
                **context,
            )
        bytes_written = staging_path.stat().st_size
        actual_size = bytes_written
        expected_size = actual_size

    if bytes_written != actual_size or (expected_size and expected_size != actual_size):
        quarantined = _move_to_quarantine(staging_path, quarantine_root)
        warnings: list[str] = []
        if staging_archive_path.exists():
            warnings.append(str(_move_to_quarantine(staging_archive_path, quarantine_root)))
        return _result(
            status="quarantined",
            reason_code="download_size_mismatch",
            reason=(
                f"Download size mismatch: API wrote {bytes_written}, local size "
                f"{actual_size}, remote listing {expected_size}."
            ),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            quarantine_path=str(quarantined),
            size_bytes=actual_size,
            sha256=_sha256(quarantined),
            warnings=warnings,
            **context,
        )

    validation = validate_downloaded_database(
        staging_path,
        expected_case_id=case_id,
        require_case_identity=require_case_identity,
    )
    digest = _sha256(staging_path)
    if validation["status"] != "PASS":
        quarantined = _move_to_quarantine(staging_path, quarantine_root)
        warnings = []
        if staging_archive_path.exists():
            warnings.append(str(_move_to_quarantine(staging_archive_path, quarantine_root)))
        return _result(
            status="quarantined",
            reason_code="invalid_downloaded_database",
            reason=str(validation.get("error") or "SQLite validation failed."),
            site=site,
            case_id=case_id,
            started_at_utc=started,
            quarantine_path=str(quarantined),
            size_bytes=actual_size,
            sha256=digest,
            database_validation=validation,
            warnings=warnings,
            **context,
        )

    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        quarantined = _move_to_quarantine(staging_path, quarantine_root)
        warnings = []
        if staging_archive_path.exists():
            warnings.append(str(_move_to_quarantine(staging_archive_path, quarantine_root)))
        return _result(
            status="quarantined",
            reason_code="destination_created_during_download",
            reason=f"Destination appeared during download; refused overwrite: {final_path}",
            site=site,
            case_id=case_id,
            started_at_utc=started,
            quarantine_path=str(quarantined),
            size_bytes=actual_size,
            sha256=digest,
            database_validation=validation,
            warnings=warnings,
            **context,
        )

    if staging_archive_path.exists():
        try:
            staging_archive_path.unlink()
        except OSError as exc:
            quarantined_database = _move_to_quarantine(staging_path, quarantine_root)
            quarantined_archive = _move_to_quarantine(staging_archive_path, quarantine_root)
            return _result(
                status="failed",
                reason_code="staging_cleanup_failed",
                reason=f"Could not remove validated temporary session-export ZIP: {exc}",
                site=site,
                case_id=case_id,
                started_at_utc=started,
                quarantine_path=str(quarantined_database),
                warnings=[str(quarantined_archive)],
                size_bytes=actual_size,
                sha256=digest,
                database_validation=validation,
                **context,
            )
    staging_path.replace(final_path)
    return _result(
        status="success",
        reason_code="",
        reason="Single-case local.db acquisition and validation succeeded.",
        site=site,
        case_id=case_id,
        started_at_utc=started,
        saved_path=str(final_path.resolve()),
        size_bytes=actual_size,
        sha256=digest,
        database_validation=validation,
        warnings=sorted(ignored_case_files, key=str.casefold),
        **context,
    )


def write_result_report(result: AcquisitionResult, report_path: Path) -> Path:
    """Write one sanitized JSON result report atomically."""
    target = report_path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _failure_from_exception(site: str, case_id: str, started: str, exc: Exception) -> AcquisitionResult:
    code = (
        "configuration_failure"
        if isinstance(exc, AcquisitionConfigurationError)
        else "connection_or_acquisition_failure"
    )
    return _result(
        status="failed",
        reason_code=code,
        reason=_safe_exception_text(exc),
        site=site,
        case_id=case_id,
        started_at_utc=started,
    )


def _configure_logging(verbose: bool) -> None:
    """Configure acquisition diagnostics without exposing signed transport URLs."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    # urllib3 debug records include the complete temporary signed download URL,
    # including encrypted request material. Keep transport details out of logs
    # even when acquisition diagnostics are otherwise verbose.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    """Build the single-case test CLI parser with no implicit site or case."""
    parser = argparse.ArgumentParser(
        description=(
            "Acquire and validate one explicitly selected local.db from a "
            "commercial Sync.com TDC session folder."
        )
    )
    parser.add_argument("--site", required=True, help="Explicit three-digit commercial site ID.")
    parser.add_argument("--case-id", required=True, help="Explicit TDC case/session ID.")
    parser.add_argument(
        "--sites-file",
        required=True,
        type=Path,
        help="External credential-bearing sites.json; never commit this file.",
    )
    sync_source = parser.add_mutually_exclusive_group()
    sync_source.add_argument(
        "--sync-tool-root",
        type=Path,
        help="Directory containing the separately maintained sync_tdc_logs package.",
    )
    sync_source.add_argument(
        "--sync-tool-zip",
        type=Path,
        help="ProfoundTools ZIP containing Python/sync-tdc-logs.",
    )
    parser.add_argument(
        "--destination",
        required=True,
        type=Path,
        help="Configurable temporary/test destination root outside Git.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional result path; defaults beneath <destination>/_reports/.",
    )
    parser.add_argument(
        "--allow-session-zip-fallback",
        action="store_true",
        help=(
            "When no direct local.db exists, inspect exactly one non-Raw "
            "session-export ZIP; ambiguity is quarantined."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the explicit single-case acquisition test and print exact paths."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    started = _utc_now()
    report_path = args.report_json or (
        args.destination / "_reports" / f"{args.case_id}_single_case_acquisition.json"
    )
    result: AcquisitionResult
    try:
        _validate_explicit_selection(args.site, args.case_id)
        site_entry = load_site_entry(args.sites_file, args.site)
        sync_link_class, load_password, session_key = _load_sync_client(
            args.sync_tool_root,
            args.sync_tool_zip,
        )
        LOGGER.info("Connecting read-only to explicitly selected site %s.", args.site)
        password = load_password()
        link = sync_link_class(site_entry["url"], password).open()
        try:
            result = acquire_single_case(
                link=link,
                site=args.site,
                case_id=args.case_id,
                destination=args.destination,
                session_key=session_key,
                allow_session_zip_fallback=args.allow_session_zip_fallback,
            )
        finally:
            session = getattr(link, "session", None)
            close = getattr(session, "close", None)
            if callable(close):
                close()
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic boundary
        result = _failure_from_exception(args.site, args.case_id, started, exc)

    report = write_result_report(result, report_path)
    print(f"Status: {result.status}")
    print(f"Site: {result.site}")
    print(f"Case ID: {result.case_id}")
    print(f"Reason: {result.reason_code or 'none'} - {result.reason}")
    if result.remote_case_folder:
        remote_parts = [result.remote_container, result.remote_case_folder]
        if result.remote_session_folder:
            remote_parts.append(result.remote_session_folder)
        if result.remote_archive_name:
            remote_parts.append(result.remote_archive_name)
        if result.remote_database_name:
            remote_parts.append(result.remote_database_name)
        print(
            "Remote identity: "
            + "/".join(part for part in remote_parts if part)
        )
    if result.database_validation:
        validation = result.database_validation
        print(f"SQLite integrity: {validation.get('integrity_check', '')}")
        print(f"Required tables: {', '.join(REQUIRED_TABLES)}")
        print(f"Row counts: {json.dumps(validation.get('row_counts', {}), sort_keys=True)}")
    if result.saved_path:
        print(f"Saved local.db: {result.saved_path}")
    if result.quarantine_path:
        print(f"Quarantined artifact: {result.quarantine_path}")
    print(f"Result report: {report}")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
