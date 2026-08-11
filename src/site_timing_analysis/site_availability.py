# Project: Site Timing Analysis
# File: src/site_timing_analysis/site_availability.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Inventories remote and local case availability without acquiring data.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Read-only Sync.com and local case-availability inventory.

The command implemented here answers whether one explicitly selected site is
available at both endpoints and whether its canonical cases have one usable
artifact location at each endpoint. Remote validation is deliberately limited
to folder structure, exact names, and the nonempty size metadata returned by
Sync.com. It never downloads, extracts, stages, opens, hashes, or otherwise
inspects a remote ``local.db``.

Inputs
------
One three-digit site ID, the external Sync registry, and a local parent whose
immediate children are Teams-synced site directories ending in ``_<site>``.

Outputs
-------
An actionable console summary and, when requested, a sanitized JSON report.
Exit status is 0 for complete canonical parity, 1 for case/artifact differences,
and 2 for configuration, endpoint access, local-site, or remote-root failures.

Assumptions and limitations
---------------------------
Only ``TDC Sessions`` and ``TDC Data`` are recognized remote roots. Canonical
case IDs follow the same two stable forms as the bundled Sync transport:
``NNN_0N-NNN`` (including a three-digit zero-leading system field) or
``NNN-NNN``. Noncanonical folders are reported but excluded from parity.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable

from .single_case_acquisition import (
    AcquisitionConfigurationError,
    _load_sync_client,
    load_site_entry,
)


RECOGNIZED_REMOTE_ROOTS = ("TDC Sessions", "TDC Data")
REMOTE_CASE_SUFFIX = " TDC Sessions"
_SITE_ID_RE = re.compile(r"^\d{3}$")
_THREE_PART_CASE_RE = re.compile(
    r"^(?P<site>\d{3})[_-](?P<system>0\d{0,2})[_-](?P<session>\d+)$"
)
_TWO_PART_CASE_RE = re.compile(r"^(?P<site>\d{3})-(?P<session>\d+)$")
_TIMESTAMPED_SESSION_DIR_RE = re.compile(
    r"^_?\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2}(?:\s+\d+)?$"
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(https?://|\b(?:password|pltoken|datakey|signature|cachekey)\s*[:=])"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_sites_file() -> Path:
    """Return the repository-local, ignored Sync registry path."""
    return _default_project_root() / "tools" / "profoundtools" / "sites.json"


def default_sync_tool_root() -> Path:
    """Return the bundled ProfoundTools transport directory."""
    return _default_project_root() / "tools" / "profoundtools"


def default_local_root() -> Path:
    """Return ``%USERPROFILE%\\Profound Medical`` without hard-coding a user."""
    profile = os.environ.get("USERPROFILE")
    base = Path(profile).expanduser() if profile else Path.home()
    return base / "Profound Medical"


def validate_site_id(site: str) -> str:
    """Validate one explicit three-digit site identifier."""
    normalized = str(site).strip()
    if not _SITE_ID_RE.fullmatch(normalized):
        raise AcquisitionConfigurationError(
            f"Site must be one explicit three-digit ID; received {site!r}."
        )
    return normalized


def canonical_case_id(name: str) -> str | None:
    """Return the canonical case ID only when ``name`` is already canonical."""
    value = str(name).strip()
    match = _THREE_PART_CASE_RE.fullmatch(value)
    if match:
        canonical = (
            f"{match.group('site')}_{match.group('system')}-{match.group('session')}"
        )
        return canonical if value == canonical else None
    match = _TWO_PART_CASE_RE.fullmatch(value)
    if match:
        canonical = f"{match.group('site')}-{match.group('session')}"
        return canonical if value == canonical else None
    return None


def _case_belongs_to_site(case_id: str, site: str) -> bool:
    return case_id.startswith(f"{site}_") or case_id.startswith(f"{site}-")


def _safe_remote_label(value: str) -> str:
    """Prevent URL/token-shaped remote names from entering output."""
    text = str(value).strip()
    return "<redacted-remote-name>" if _SENSITIVE_TEXT_RE.search(text) else text


def _safe_error_type(exc: Exception) -> str:
    """Return useful exception classification without serializing its message."""
    name = type(exc).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "Exception"


@dataclass
class ArtifactReference:
    """One inventory-only database location and its reported size."""

    path: str
    size_bytes: int


@dataclass
class CaseInventory:
    """Availability result for one canonical case ID at one endpoint."""

    case_id: str
    status: str
    folders: list[str] = field(default_factory=list)
    session_folders: list[str] = field(default_factory=list)
    database_artifacts: list[ArtifactReference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EndpointInventory:
    """Sanitized remote or local inventory with complete folder accounting."""

    endpoint: str
    status: str
    reason_code: str = ""
    reason: str = ""
    recognized_root: str = ""
    resolved_path: str = ""
    discovered_folder_count: int = 0
    canonical_case_folder_count: int = 0
    noncanonical_folders: list[str] = field(default_factory=list)
    ignored_files: list[str] = field(default_factory=list)
    duplicate_case_ids: list[str] = field(default_factory=list)
    cases: list[CaseInventory] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        statuses: dict[str, int] = {}
        for case in self.cases:
            statuses[case.status] = statuses.get(case.status, 0) + 1
        return {
            "discovered_folders": self.discovered_folder_count,
            "canonical_case_folders": self.canonical_case_folder_count,
            "canonical_case_ids": len(self.cases),
            "noncanonical_folders": len(self.noncanonical_folders),
            "ignored_files": len(self.ignored_files),
            "duplicate_case_ids": len(self.duplicate_case_ids),
            "available_cases": statuses.get("available", 0),
            "case_issues": sum(
                count for status, count in statuses.items() if status != "available"
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["counts"] = self.counts()
        return payload


@dataclass
class SiteAvailabilityReport:
    """Machine-readable result for one remote/local availability check."""

    site: str
    started_at_utc: str
    completed_at_utc: str
    status: str
    exit_code: int
    access_mode: str
    remote: EndpointInventory
    local: EndpointInventory
    parity: dict[str, Any]
    failure_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "site": self.site,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "status": self.status,
            "exit_code": self.exit_code,
            "access_mode": self.access_mode,
            "remote": self.remote.to_dict(),
            "local": self.local.to_dict(),
            "parity": self.parity,
            "failure_reasons": list(self.failure_reasons),
        }


def _endpoint_failure(
    endpoint: str,
    reason_code: str,
    reason: str,
    **kwargs: Any,
) -> EndpointInventory:
    return EndpointInventory(
        endpoint=endpoint,
        status="failure",
        reason_code=reason_code,
        reason=reason,
        **kwargs,
    )


def _remote_case_id(folder_name: str, site: str) -> str | None:
    name = str(folder_name).strip()
    if not name.endswith(REMOTE_CASE_SUFFIX):
        return None
    case_id = canonical_case_id(name[: -len(REMOTE_CASE_SUFFIX)])
    if case_id is None or not _case_belongs_to_site(case_id, site):
        return None
    return case_id if name == f"{case_id}{REMOTE_CASE_SUFFIX}" else None


def _database_status(
    artifacts: list[ArtifactReference],
    *,
    duplicate_status: str,
) -> str:
    """Classify exact-name artifacts without opening or reading their contents."""
    if not artifacts:
        return "missing_database"
    if len(artifacts) > 1:
        return duplicate_status
    if artifacts[0].size_bytes <= 0:
        return "empty_database"
    return "available"


def inventory_remote_site(link: Any, site: str) -> EndpointInventory:
    """Inventory one open Sync link using listing calls only.

    No method other than ``listdir`` is called. In particular, this function
    never requests file keys, download URLs, file bytes, or archive contents.
    """
    site = validate_site_id(site)
    try:
        root_items = list(link.listdir(link.root_sync_id))
    except Exception as exc:  # noqa: BLE001 - external read-only transport boundary
        return _endpoint_failure(
            "remote",
            "remote_root_listing_failed",
            f"The Sync.com share root could not be listed ({_safe_error_type(exc)}).",
        )

    recognized = [
        item
        for item in root_items
        if bool(getattr(item, "is_dir", False))
        and str(getattr(item, "name", "")).strip().casefold()
        in {name.casefold() for name in RECOGNIZED_REMOTE_ROOTS}
    ]
    recognized.sort(key=lambda item: (str(item.name).casefold(), int(item.sync_id)))
    if len(recognized) != 1:
        names = [_safe_remote_label(item.name) for item in recognized]
        code = "missing_recognized_remote_root" if not recognized else "ambiguous_remote_roots"
        reason = (
            "Expected exactly one recognized Sync.com root named 'TDC Sessions' "
            f"or 'TDC Data'; found {len(recognized)}."
        )
        return _endpoint_failure(
            "remote",
            code,
            reason,
            warnings=names,
        )

    selected_root = recognized[0]
    root_name = _safe_remote_label(selected_root.name)
    try:
        items = list(link.listdir(selected_root.sync_id))
    except Exception as exc:  # noqa: BLE001 - external read-only transport boundary
        return _endpoint_failure(
            "remote",
            "remote_case_container_listing_failed",
            f"The recognized remote root could not be listed ({_safe_error_type(exc)}).",
            recognized_root=root_name,
        )

    folders = [item for item in items if bool(getattr(item, "is_dir", False))]
    files = [item for item in items if not bool(getattr(item, "is_dir", False))]
    grouped: dict[str, list[Any]] = {}
    noncanonical: list[str] = []
    for folder in folders:
        case_id = _remote_case_id(folder.name, site)
        if case_id is None:
            noncanonical.append(_safe_remote_label(folder.name))
        else:
            grouped.setdefault(case_id, []).append(folder)

    cases: list[CaseInventory] = []
    access_failures: list[str] = []
    duplicate_ids = sorted(
        [case_id for case_id, matches in grouped.items() if len(matches) > 1],
        key=str.casefold,
    )
    for case_id in sorted(grouped, key=str.casefold):
        case_folders = sorted(
            grouped[case_id], key=lambda item: (str(item.name).casefold(), int(item.sync_id))
        )
        folder_names = [_safe_remote_label(item.name) for item in case_folders]
        if len(case_folders) != 1:
            cases.append(
                CaseInventory(
                    case_id=case_id,
                    status="duplicate_case_id",
                    folders=folder_names,
                    warnings=["Multiple exact remote case folders share this case ID."],
                )
            )
            continue

        case_folder = case_folders[0]
        try:
            case_children = list(link.listdir(case_folder.sync_id))
        except Exception as exc:  # noqa: BLE001
            access_failures.append(case_id)
            cases.append(
                CaseInventory(
                    case_id=case_id,
                    status="access_failure",
                    folders=folder_names,
                    warnings=[
                        f"Case folder listing failed ({_safe_error_type(exc)})."
                    ],
                )
            )
            continue

        timestamped: list[Any] = []
        warnings: list[str] = []
        for child in case_children:
            name = str(getattr(child, "name", "")).strip()
            if bool(getattr(child, "is_dir", False)):
                if name.casefold() == "applog":
                    continue
                if _TIMESTAMPED_SESSION_DIR_RE.fullmatch(name):
                    timestamped.append(child)
                else:
                    warnings.append(
                        f"Ignored non-timestamped child directory: {_safe_remote_label(name)}"
                    )
            else:
                warnings.append(
                    f"Ignored case-level file: {_safe_remote_label(name)}"
                )
        timestamped.sort(
            key=lambda item: (str(item.name).casefold(), int(item.sync_id))
        )

        artifacts: list[ArtifactReference] = []
        session_names: list[str] = []
        listing_failed = False
        for session_folder in timestamped:
            safe_session_name = _safe_remote_label(session_folder.name)
            session_names.append(safe_session_name)
            try:
                session_items = list(link.listdir(session_folder.sync_id))
            except Exception as exc:  # noqa: BLE001
                listing_failed = True
                warnings.append(
                    f"Session folder listing failed ({_safe_error_type(exc)}): "
                    f"{safe_session_name}"
                )
                continue
            for item in session_items:
                if bool(getattr(item, "is_dir", False)):
                    continue
                if str(getattr(item, "name", "")).strip().casefold() != "local.db":
                    continue
                artifacts.append(
                    ArtifactReference(
                        path=f"{safe_session_name}/local.db",
                        size_bytes=max(0, int(getattr(item, "size", 0) or 0)),
                    )
                )

        if listing_failed:
            access_failures.append(case_id)
            status = "access_failure"
        else:
            status = _database_status(artifacts, duplicate_status="ambiguous_database")
        cases.append(
            CaseInventory(
                case_id=case_id,
                status=status,
                folders=folder_names,
                session_folders=session_names,
                database_artifacts=artifacts,
                warnings=sorted(warnings, key=str.casefold),
            )
        )

    endpoint_status = "failure" if access_failures else "available"
    return EndpointInventory(
        endpoint="remote",
        status=endpoint_status,
        reason_code="remote_listing_incomplete" if access_failures else "",
        reason=(
            "One or more remote case/session folders could not be listed."
            if access_failures
            else "Configured Sync.com share is reachable read-only."
        ),
        recognized_root=root_name,
        discovered_folder_count=len(folders),
        canonical_case_folder_count=sum(len(matches) for matches in grouped.values()),
        noncanonical_folders=sorted(noncanonical, key=str.casefold),
        ignored_files=sorted(
            [_safe_remote_label(item.name) for item in files], key=str.casefold
        ),
        duplicate_case_ids=duplicate_ids,
        cases=cases,
        warnings=(
            [f"Incomplete listing for canonical cases: {', '.join(sorted(access_failures))}"]
            if access_failures
            else []
        ),
    )


def _missing_local_message(site: str) -> str:
    return (
        f"Site {site} is not available locally. Sync the site directory ending in "
        f"_{site} from the Clinical Science Team through the Teams app, then rerun."
    )


def inventory_local_site(local_root: Path, site: str) -> EndpointInventory:
    """Inventory canonical immediate local case folders without changing files."""
    site = validate_site_id(site)
    root = local_root.expanduser().resolve()
    if not root.is_dir():
        return _endpoint_failure(
            "local",
            "local_parent_missing",
            _missing_local_message(site),
            resolved_path=str(root),
        )
    try:
        root_items = list(root.iterdir())
    except OSError as exc:
        return _endpoint_failure(
            "local",
            "local_parent_access_failed",
            f"The local parent could not be listed ({_safe_error_type(exc)}): {root}",
            resolved_path=str(root),
        )
    suffix = f"_{site}".casefold()
    site_directories = sorted(
        [item for item in root_items if item.is_dir() and item.name.casefold().endswith(suffix)],
        key=lambda path: path.name.casefold(),
    )
    if not site_directories:
        return _endpoint_failure(
            "local",
            "local_site_missing",
            _missing_local_message(site),
            resolved_path=str(root),
        )
    if len(site_directories) != 1:
        return _endpoint_failure(
            "local",
            "ambiguous_local_site_directories",
            (
                f"Expected exactly one immediate local site directory ending in _{site}; "
                f"found {len(site_directories)}."
            ),
            resolved_path=str(root),
            warnings=[str(path.resolve()) for path in site_directories],
        )

    site_path = site_directories[0].resolve()
    try:
        site_items = list(site_path.iterdir())
    except OSError as exc:
        return _endpoint_failure(
            "local",
            "local_site_access_failed",
            f"The local site directory could not be listed ({_safe_error_type(exc)}).",
            resolved_path=str(site_path),
        )
    folders = [item for item in site_items if item.is_dir()]
    files = [item for item in site_items if not item.is_dir()]
    grouped: dict[str, list[Path]] = {}
    noncanonical: list[str] = []
    for folder in folders:
        case_id = canonical_case_id(folder.name)
        if case_id is None or not _case_belongs_to_site(case_id, site):
            noncanonical.append(folder.name)
        else:
            grouped.setdefault(case_id, []).append(folder)

    cases: list[CaseInventory] = []
    access_failures: list[str] = []
    duplicate_ids = sorted(
        [case_id for case_id, matches in grouped.items() if len(matches) > 1],
        key=str.casefold,
    )
    for case_id in sorted(grouped, key=str.casefold):
        case_folders = sorted(grouped[case_id], key=lambda path: path.name.casefold())
        folder_paths = [str(path.resolve()) for path in case_folders]
        if len(case_folders) != 1:
            cases.append(
                CaseInventory(
                    case_id=case_id,
                    status="duplicate_case_id",
                    folders=folder_paths,
                    warnings=["Multiple canonical local folders share this case ID."],
                )
            )
            continue
        case_folder = case_folders[0]
        try:
            case_items = list(case_folder.iterdir())
            artifacts = [
                ArtifactReference(
                    path=str(item.resolve()),
                    size_bytes=max(0, int(item.stat().st_size)),
                )
                for item in case_items
                if item.is_file() and item.name.casefold() == "local.db"
            ]
        except OSError as exc:
            access_failures.append(case_id)
            cases.append(
                CaseInventory(
                    case_id=case_id,
                    status="access_failure",
                    folders=folder_paths,
                    warnings=[f"Local case listing failed ({_safe_error_type(exc)})."],
                )
            )
            continue
        artifacts.sort(key=lambda artifact: artifact.path.casefold())
        cases.append(
            CaseInventory(
                case_id=case_id,
                status=_database_status(artifacts, duplicate_status="duplicate_database"),
                folders=folder_paths,
                database_artifacts=artifacts,
            )
        )

    endpoint_status = "failure" if access_failures else "available"
    return EndpointInventory(
        endpoint="local",
        status=endpoint_status,
        reason_code="local_listing_incomplete" if access_failures else "",
        reason=(
            "One or more local case folders could not be listed."
            if access_failures
            else "Teams-synced local site directory is available read-only."
        ),
        resolved_path=str(site_path),
        discovered_folder_count=len(folders),
        canonical_case_folder_count=sum(len(matches) for matches in grouped.values()),
        noncanonical_folders=sorted(noncanonical, key=str.casefold),
        ignored_files=sorted([item.name for item in files], key=str.casefold),
        duplicate_case_ids=duplicate_ids,
        cases=cases,
        warnings=(
            [f"Incomplete listing for canonical cases: {', '.join(sorted(access_failures))}"]
            if access_failures
            else []
        ),
    )


def _case_map(endpoint: EndpointInventory) -> dict[str, CaseInventory]:
    return {case.case_id: case for case in endpoint.cases}


def build_site_report(
    site: str,
    remote: EndpointInventory,
    local: EndpointInventory,
    *,
    started_at_utc: str,
) -> SiteAvailabilityReport:
    """Reconcile two endpoint inventories and assign the documented exit code."""
    remote_cases = _case_map(remote)
    local_cases = _case_map(local)
    remote_ids = set(remote_cases)
    local_ids = set(local_cases)
    matched = sorted(remote_ids & local_ids, key=str.casefold)
    remote_only = sorted(remote_ids - local_ids, key=str.casefold)
    local_only = sorted(local_ids - remote_ids, key=str.casefold)
    complete = [
        case_id
        for case_id in matched
        if remote_cases[case_id].status == "available"
        and local_cases[case_id].status == "available"
    ]
    remote_issues = {
        case_id: remote_cases[case_id].status
        for case_id in sorted(remote_cases, key=str.casefold)
        if remote_cases[case_id].status != "available"
    }
    local_issues = {
        case_id: local_cases[case_id].status
        for case_id in sorted(local_cases, key=str.casefold)
        if local_cases[case_id].status != "available"
    }
    ambiguous_ids = sorted(
        set(remote.duplicate_case_ids) | set(local.duplicate_case_ids),
        key=str.casefold,
    )
    parity = {
        "matched_cases": matched,
        "complete_cases": complete,
        "remote_only_cases": remote_only,
        "local_only_cases": local_only,
        "remote_case_issues": remote_issues,
        "local_case_issues": local_issues,
        "duplicate_or_ambiguous_case_ids": ambiguous_ids,
        "counts": {
            "matched_cases": len(matched),
            "complete_cases": len(complete),
            "remote_only_cases": len(remote_only),
            "local_only_cases": len(local_only),
            "remote_case_issues": len(remote_issues),
            "local_case_issues": len(local_issues),
            "duplicate_or_ambiguous_case_ids": len(ambiguous_ids),
        },
    }

    endpoint_failures = [
        f"{endpoint.endpoint}:{endpoint.reason_code}"
        for endpoint in (remote, local)
        if endpoint.status != "available"
    ]
    if endpoint_failures:
        status, exit_code = "failure", 2
    elif remote_only or local_only or remote_issues or local_issues or ambiguous_ids:
        status, exit_code = "differences", 1
    else:
        status, exit_code = "complete", 0
    return SiteAvailabilityReport(
        site=site,
        started_at_utc=started_at_utc,
        completed_at_utc=_utc_now(),
        status=status,
        exit_code=exit_code,
        access_mode="inventory_only_read_only",
        remote=remote,
        local=local,
        parity=parity,
        failure_reasons=endpoint_failures,
    )


def _remote_connection_failure(exc: Exception) -> tuple[str, str]:
    """Classify connection errors without retaining credential-bearing text."""
    lowered = str(exc).casefold()
    code = getattr(exc, "code", None)
    if "password" in lowered or "auth" in lowered or code in {1005, 1101}:
        return (
            "remote_authentication_failed",
            f"Sync.com authentication failed ({_safe_error_type(exc)}). "
            "Verify the stored credential.",
        )
    return (
        "remote_access_failed",
        f"The configured Sync.com share could not be opened ({_safe_error_type(exc)}).",
    )


def check_site_availability(
    *,
    site: str,
    sites_file: Path,
    local_root: Path,
    sync_tool_root: Path | None = None,
    sync_link_class: Any | None = None,
    credential_loader: Callable[[], str] | None = None,
) -> SiteAvailabilityReport:
    """Inventory both endpoints while keeping endpoint failures independent."""
    started = _utc_now()
    site = validate_site_id(site)
    local = inventory_local_site(local_root, site)

    remote: EndpointInventory
    try:
        entry = load_site_entry(sites_file, site)
        if sync_link_class is None or credential_loader is None:
            loaded_class, loaded_credential, _session_key = _load_sync_client(
                sync_tool_root or default_sync_tool_root(),
                None,
            )
            sync_link_class = sync_link_class or loaded_class
            credential_loader = credential_loader or loaded_credential
        try:
            password = credential_loader()
        except Exception as exc:  # noqa: BLE001 - credential-provider boundary
            remote = _endpoint_failure(
                "remote",
                "credential_retrieval_failed",
                f"The Sync.com credential could not be retrieved ({_safe_error_type(exc)}).",
            )
        else:
            link: Any | None = None
            try:
                link = sync_link_class(entry["url"], password)
                link.open()
                remote = inventory_remote_site(link, site)
            except Exception as exc:  # noqa: BLE001 - external transport boundary
                reason_code, reason = _remote_connection_failure(exc)
                remote = _endpoint_failure("remote", reason_code, reason)
            finally:
                session = getattr(link, "session", None)
                close = getattr(session, "close", None)
                if callable(close):
                    close()
    except AcquisitionConfigurationError as exc:
        remote = _endpoint_failure(
            "remote",
            "remote_configuration_failed",
            str(exc),
        )

    return build_site_report(site, remote, local, started_at_utc=started)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def write_json_report(
    report: SiteAvailabilityReport,
    report_path: Path,
    *,
    local_root: Path,
) -> Path:
    """Write sanitized JSON outside the Teams-synced local parent."""
    target = report_path.expanduser().resolve()
    prohibited_root = local_root.expanduser().resolve()
    if _is_within(target, prohibited_root):
        raise AcquisitionConfigurationError(
            "--report-json must be outside the Teams-synced local parent so the "
            "read-only site tree remains unchanged."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _print_values(label: str, values: Iterable[str]) -> None:
    materialized = list(values)
    print(f"{label}: {', '.join(materialized) if materialized else 'none'}")


def print_console_summary(report: SiteAvailabilityReport) -> None:
    """Print the same status and counts represented by the JSON report."""
    remote_counts = report.remote.counts()
    local_counts = report.local.counts()
    parity_counts = report.parity["counts"]
    print(f"Site availability and case parity: {report.site}")
    print(
        "Remote Sync.com: "
        f"{report.remote.status}; root={report.remote.recognized_root or 'unresolved'}; "
        f"canonical cases={remote_counts['canonical_case_ids']}"
    )
    if report.remote.reason:
        print(f"Remote detail: {report.remote.reason_code or 'ok'} - {report.remote.reason}")
    print(
        "Local Teams: "
        f"{report.local.status}; path={report.local.resolved_path or 'unresolved'}; "
        f"canonical cases={local_counts['canonical_case_ids']}"
    )
    if report.local.reason:
        print(f"Local detail: {report.local.reason_code or 'ok'} - {report.local.reason}")
    print(
        "Parity counts: "
        f"matched={parity_counts['matched_cases']}, "
        f"complete={parity_counts['complete_cases']}, "
        f"remote-only={parity_counts['remote_only_cases']}, "
        f"local-only={parity_counts['local_only_cases']}"
    )
    _print_values("Remote-only cases", report.parity["remote_only_cases"])
    _print_values("Local-only cases", report.parity["local_only_cases"])
    _print_values(
        "Remote case issues",
        [
            f"{case_id} ({status})"
            for case_id, status in report.parity["remote_case_issues"].items()
        ],
    )
    _print_values(
        "Local case issues",
        [f"{case_id} ({status})" for case_id, status in report.parity["local_case_issues"].items()],
    )
    _print_values(
        "Duplicate or ambiguous case IDs",
        report.parity["duplicate_or_ambiguous_case_ids"],
    )
    _print_values("Remote noncanonical folders (excluded)", report.remote.noncanonical_folders)
    _print_values("Local noncanonical folders (excluded)", report.local.noncanonical_folders)
    print(f"Result: {report.status}; exit code={report.exit_code}")


def build_parser() -> argparse.ArgumentParser:
    """Build the PowerShell-friendly site inventory CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Read-only inventory of one site's Sync.com TDC sessions and "
            "Teams-synced local case folders. No files are acquired."
        )
    )
    parser.add_argument("--site", required=True, help="Explicit three-digit site ID.")
    parser.add_argument(
        "--sites-file",
        type=Path,
        default=default_sites_file(),
        help="Sync registry (default: tools/profoundtools/sites.json).",
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        default=default_local_root(),
        help=(
            "Parent of Teams-synced site directories "
            "(default: %%USERPROFILE%%\\Profound Medical)."
        ),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional sanitized JSON path outside the Teams-synced local parent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the inventory, print its summary, and optionally serialize JSON."""
    args = build_parser().parse_args(argv)
    try:
        report = check_site_availability(
            site=args.site,
            sites_file=args.sites_file,
            local_root=args.local_root,
        )
    except AcquisitionConfigurationError as exc:
        print(f"Configuration failure: {exc}")
        return 2

    print_console_summary(report)
    if args.report_json is not None:
        try:
            report_path = write_json_report(
                report,
                args.report_json,
                local_root=args.local_root,
            )
        except (AcquisitionConfigurationError, OSError) as exc:
            print(f"Report failure: {exc}")
            return 2
        print(f"JSON report: {report_path}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
