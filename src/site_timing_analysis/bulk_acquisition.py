# Project: Site Timing Analysis
# File: src/site_timing_analysis/bulk_acquisition.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Safely acquires explicit bulk local.db selections with resumable inventory tracking.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Resumable, explicit bulk acquisition of commercial ``local.db`` files.

The bulk layer composes the validated single-case contract. It never discovers
or invents a case selection: callers must supply case IDs directly or through a
plain-text manifest. Each selected case is processed independently through one
authenticated, read-only Sync connection.

Successful databases are published as ``<destination>/<case_id>/local.db``.
Technical inventory, staging, quarantine, and per-run reports are written under
a required, separate backend root. Existing files are reused only when read-only
database validation, a prior successful inventory record, and current remote
metadata all agree. An explicit first-run adoption option verifies an existing
file against a freshly downloaded source by exact SHA-256 equality. No
source-share mutation API is called, and the existing ProfoundTools ``applog``
workflow remains outside this module.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable

from .single_case_acquisition import (
    AcquisitionConfigurationError,
    AcquisitionResult,
    _configure_logging,
    _failure_from_exception,
    _load_sync_client,
    _safe_exception_text,
    _utc_now,
    _validate_explicit_selection,
    acquire_single_case,
    load_site_entry,
    write_result_report,
)


INVENTORY_SCHEMA_VERSION = 1
INVENTORY_DIR_NAME = "_acquisition"
LOGGER = logging.getLogger(__name__)


@dataclass
class BulkCaseOutcome:
    """One case result plus the bulk action and recovery facts."""

    case_id: str
    action: str
    result: AcquisitionResult
    recovered_staging_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result"] = self.result.to_dict()
        return payload


@dataclass
class BulkRunSummary:
    """Complete machine-readable record for one explicit bulk run."""

    run_id: str
    status: str
    reason: str
    site: str
    destination_root: str
    backend_root: str
    requested_case_ids: list[str]
    selection_sha256: str
    started_at_utc: str
    completed_at_utc: str
    source_access_mode: str = "read_only"
    counts: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)
    invariants: dict[str, bool] = field(default_factory=dict)
    global_failures: list[str] = field(default_factory=list)
    outcomes: list[BulkCaseOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcomes"] = [outcome.to_dict() for outcome in self.outcomes]
        return payload


class DestinationLock:
    """Hold a non-blocking advisory lock for one acquisition destination."""

    def __init__(self, path: Path, run_id: str):
        self.path = path.expanduser().resolve()
        self.run_id = run_id
        self._handle: Any | None = None

    def __enter__(self) -> "DestinationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise AcquisitionConfigurationError(
                f"Another acquisition process holds the destination lock: {self.path}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(
            (json.dumps({"run_id": self.run_id, "pid": os.getpid()}) + "\n").encode(
                "utf-8"
            )
        )
        handle.flush()
        self._handle = handle
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None


def _run_id() -> str:
    """Return a sortable, collision-resistant UTC run identifier."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _selection_digest(case_ids: list[str]) -> str:
    payload = ("\n".join(case_ids) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def validate_bulk_selection(site: str, case_ids: list[str]) -> list[str]:
    """Validate one nonempty, unique, explicit same-site case selection."""
    selected = [case_id.strip() for case_id in case_ids]
    if not selected:
        raise AcquisitionConfigurationError("At least one explicit case ID is required.")
    for case_id in selected:
        _validate_explicit_selection(site, case_id)
        if not case_id.casefold().startswith(f"{site}_".casefold()):
            raise AcquisitionConfigurationError(
                f"Case ID {case_id!r} does not use the selected site prefix {site!r}."
            )
    folded = [case_id.casefold() for case_id in selected]
    if len(folded) != len(set(folded)):
        raise AcquisitionConfigurationError(
            "Explicit case IDs must be unique, including case-insensitive duplicates."
        )
    return selected


def load_case_manifest(path: Path) -> list[str]:
    """Load explicit case IDs from a UTF-8 text file, one ID per line."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise AcquisitionConfigurationError(f"Case manifest not found: {resolved}")
    try:
        lines = resolved.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise AcquisitionConfigurationError(
            f"Could not read case manifest {resolved}: {exc}"
        ) from exc
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def resolve_case_selection(
    *,
    site: str,
    case_ids: list[str] | None,
    case_manifest: Path | None,
) -> list[str]:
    """Resolve exactly one explicit CLI selection mechanism."""
    if bool(case_ids) == (case_manifest is not None):
        raise AcquisitionConfigurationError(
            "Use exactly one selection mechanism: repeated --case-id or --case-manifest."
        )
    selected = list(case_ids or load_case_manifest(case_manifest))
    return validate_bulk_selection(site, selected)


def _inventory_paths(backend_root: Path) -> tuple[Path, Path]:
    root = backend_root / INVENTORY_DIR_NAME
    return root / "inventory.json", root / "inventory.csv"


def validate_backend_separation(destination: Path, backend_root: Path) -> tuple[Path, Path]:
    """Require technical artifacts to remain outside the clean destination tree."""
    resolved_destination = destination.expanduser().resolve()
    resolved_backend = backend_root.expanduser().resolve()
    if resolved_backend == resolved_destination or resolved_backend.is_relative_to(
        resolved_destination
    ):
        raise AcquisitionConfigurationError(
            "Backend directory must be separate from and outside the final destination."
        )
    return resolved_destination, resolved_backend


def new_inventory(site: str, destination: Path) -> dict[str, Any]:
    """Create one empty inventory bound to a site and absolute destination."""
    now = _utc_now()
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "site": site,
        "destination_root": str(destination.expanduser().resolve()),
        "created_at_utc": now,
        "updated_at_utc": now,
        "cases": {},
        "runs": [],
    }


def load_inventory(path: Path, *, site: str, destination: Path) -> dict[str, Any]:
    """Load and validate an existing inventory or create an empty one."""
    target = path.expanduser().resolve()
    expected_destination = str(destination.expanduser().resolve())
    if not target.exists():
        return new_inventory(site, destination)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionConfigurationError(
            f"Could not read acquisition inventory {target}: {exc}"
        ) from exc
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise AcquisitionConfigurationError(
            f"Unsupported acquisition inventory schema in {target}."
        )
    if payload.get("site") != site:
        raise AcquisitionConfigurationError(
            f"Inventory site {payload.get('site')!r} does not match {site!r}."
        )
    if str(payload.get("destination_root", "")).casefold() != expected_destination.casefold():
        raise AcquisitionConfigurationError(
            "Inventory destination does not match the selected destination root."
        )
    if not isinstance(payload.get("cases"), dict) or not isinstance(
        payload.get("runs"), list
    ):
        raise AcquisitionConfigurationError("Acquisition inventory has invalid structure.")
    return payload


def _atomic_write_text(path: Path, text: str) -> Path:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temporary, target)
            break
        except PermissionError:
            if attempt == 4:
                raise
            # Windows indexing/antivirus can briefly retain the prior inventory
            # handle after a read. Preserve atomic replacement and retry within
            # a tightly bounded quarter-second window.
            time.sleep(0.05 * (attempt + 1))
    return target


def _inventory_csv(inventory: dict[str, Any]) -> str:
    """Render the current case inventory as a stable CSV table."""
    from io import StringIO

    fields = [
        "case_id",
        "attempt_count",
        "last_status",
        "last_reason_code",
        "last_reason",
        "last_action",
        "saved_path",
        "size_bytes",
        "sha256",
        "sqlite_status",
        "identity_status",
        "remote_container",
        "remote_case_folder",
        "remote_session_folder",
        "remote_archive_name",
        "remote_database_name",
        "remote_artifact_size_bytes",
        "remote_artifact_usertime",
        "last_run_id",
        "last_checked_at_utc",
    ]
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for case_id, record in sorted(
        inventory["cases"].items(), key=lambda pair: pair[0].casefold()
    ):
        artifact = record.get("artifact") or {}
        last_attempt = record.get("last_attempt") or {}
        validation = artifact.get("database_validation") or {}
        writer.writerow(
            {
                "case_id": case_id,
                "attempt_count": record.get("attempt_count", 0),
                "last_status": last_attempt.get("status", ""),
                "last_reason_code": last_attempt.get("reason_code", ""),
                "last_reason": last_attempt.get("reason", ""),
                "last_action": last_attempt.get("action", ""),
                "saved_path": artifact.get("saved_path", ""),
                "size_bytes": artifact.get("size_bytes", ""),
                "sha256": artifact.get("sha256", ""),
                "sqlite_status": validation.get("status", ""),
                "identity_status": validation.get("case_identity", {}).get("status", ""),
                "remote_container": artifact.get("remote_container", ""),
                "remote_case_folder": artifact.get("remote_case_folder", ""),
                "remote_session_folder": artifact.get("remote_session_folder", ""),
                "remote_archive_name": artifact.get("remote_archive_name", ""),
                "remote_database_name": artifact.get("remote_database_name", ""),
                "remote_artifact_size_bytes": artifact.get(
                    "remote_artifact_size_bytes", ""
                ),
                "remote_artifact_usertime": artifact.get("remote_artifact_usertime", ""),
                "last_run_id": last_attempt.get("run_id", ""),
                "last_checked_at_utc": last_attempt.get("completed_at_utc", ""),
            }
        )
    return buffer.getvalue()


def write_inventory(
    inventory: dict[str, Any],
    *,
    json_path: Path,
    csv_path: Path,
) -> tuple[Path, Path]:
    """Atomically write machine- and operator-readable current inventory."""
    inventory["updated_at_utc"] = _utc_now()
    json_target = _atomic_write_text(
        json_path,
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    )
    csv_target = _atomic_write_text(csv_path, _inventory_csv(inventory))
    return json_target, csv_target


def _artifact_record(result: AcquisitionResult, previous: dict[str, Any] | None) -> dict[str, Any]:
    """Build the verified artifact portion of one case inventory record."""
    prior = previous or {}
    acquired_at = prior.get("acquired_at_utc") or result.completed_at_utc
    return {
        "site": result.site,
        "case_id": result.case_id,
        "saved_path": result.saved_path,
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "remote_container": result.remote_container,
        "remote_case_folder": result.remote_case_folder,
        "remote_session_folder": result.remote_session_folder,
        "remote_archive_name": result.remote_archive_name,
        "remote_database_name": result.remote_database_name,
        "remote_artifact_size_bytes": result.remote_artifact_size_bytes,
        "remote_artifact_usertime": result.remote_artifact_usertime,
        "database_validation": result.database_validation,
        "acquired_at_utc": acquired_at,
        "last_verified_at_utc": result.completed_at_utc,
    }


def update_inventory_case(
    inventory: dict[str, Any],
    *,
    run_id: str,
    outcome: BulkCaseOutcome,
) -> None:
    """Update one case while retaining its last verified artifact on failures."""
    cases = inventory["cases"]
    existing = cases.get(outcome.case_id) or {}
    result = outcome.result
    record = {
        "case_id": outcome.case_id,
        "attempt_count": int(existing.get("attempt_count", 0)) + 1,
        "artifact": existing.get("artifact"),
        "last_attempt": {
            "run_id": run_id,
            "status": result.status,
            "reason_code": result.reason_code or "success",
            "reason": result.reason,
            "action": outcome.action,
            "completed_at_utc": result.completed_at_utc,
            "recovered_staging_paths": outcome.recovered_staging_paths,
        },
    }
    if result.status == "success" and result.reason_code != "existing_detected_and_skipped":
        record["artifact"] = _artifact_record(result, existing.get("artifact"))
    cases[outcome.case_id] = record


def _recover_stale_staging(destination: Path, case_id: str, run_id: str) -> list[str]:
    """Move interrupted staging files to a recoverable run-specific quarantine."""
    staging_root = destination / "_staging" / case_id
    files = sorted(
        [path for path in staging_root.rglob("*") if path.is_file()],
        key=lambda path: str(path).casefold(),
    )
    recovered: list[str] = []
    for source in files:
        relative = source.relative_to(staging_root)
        target = (
            destination
            / "_quarantine"
            / case_id
            / "recovered_staging"
            / run_id
            / relative
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        recovered.append(str(target.resolve()))
    return recovered


def _action_for_result(result: AcquisitionResult) -> str:
    if result.status == "success" and result.reason_code == "existing_detected_and_skipped":
        return "skipped_existing"
    if result.status == "success" and result.reason_code == "existing_verified_and_adopted":
        return "adopted_existing"
    if result.status == "success" and result.reason_code == "already_present_valid":
        return "reused_existing"
    if result.status == "success":
        return "downloaded"
    return result.status


def _build_run_summary(
    *,
    run_id: str,
    site: str,
    destination: Path,
    backend_root: Path,
    case_ids: list[str],
    started_at_utc: str,
    outcomes: list[BulkCaseOutcome],
    global_failures: list[str] | None = None,
) -> BulkRunSummary:
    failures = list(global_failures or [])
    status_counts = Counter(outcome.result.status for outcome in outcomes)
    action_counts = Counter(outcome.action for outcome in outcomes)
    reason_counts = Counter(
        outcome.result.reason_code or "success" for outcome in outcomes
    )
    successful = [outcome for outcome in outcomes if outcome.result.status == "success"]
    result_ids = [outcome.case_id.casefold() for outcome in outcomes]
    saved_paths = [outcome.result.saved_path.casefold() for outcome in successful]
    expected_paths = {
        case_id.casefold(): str((destination / case_id / "local.db").resolve()).casefold()
        for case_id in case_ids
    }
    invariants = {
        "explicit_nonempty_selection": bool(case_ids),
        "unique_requested_case_ids": len({case_id.casefold() for case_id in case_ids})
        == len(case_ids),
        "valid_selected_site_prefix": all(
            case_id.casefold().startswith(f"{site}_".casefold()) for case_id in case_ids
        ),
        "complete_case_result_accounting": len(outcomes) == len(case_ids),
        "unique_processed_case_ids": len(result_ids) == len(set(result_ids)),
        "successful_paths_are_case_specific": all(
            outcome.result.saved_path.casefold()
            == expected_paths.get(outcome.case_id.casefold(), "")
            for outcome in successful
        ),
        "unique_successful_paths": len(saved_paths) == len(set(saved_paths)),
        "successful_sqlite_validations_passed": all(
            outcome.result.database_validation.get("status") == "PASS"
            for outcome in successful
        ),
        "successful_case_identities_verified_or_existing_reported": all(
            (
                outcome.result.reason_code == "existing_detected_and_skipped"
                and outcome.result.database_validation.get("case_identity", {}).get("status")
                in {"PASS", "NOT_AVAILABLE"}
            )
            or (
                outcome.result.reason_code != "existing_detected_and_skipped"
                and outcome.result.database_validation.get("case_identity", {}).get("status")
                == "PASS"
            )
            for outcome in successful
        ),
        "no_global_failures": not failures,
    }
    complete = all(invariants.values()) and len(successful) == len(case_ids)
    return BulkRunSummary(
        run_id=run_id,
        status="success" if complete else "partial",
        reason=(
            "Every explicitly selected case was acquired or safely reused."
            if complete
            else (
                "One or more selected cases failed or were quarantined; "
                "other cases were isolated."
            )
        ),
        site=site,
        destination_root=str(destination.resolve()),
        backend_root=str(backend_root.resolve()),
        requested_case_ids=case_ids,
        selection_sha256=_selection_digest(case_ids),
        started_at_utc=started_at_utc,
        completed_at_utc=_utc_now(),
        counts={
            "requested": len(case_ids),
            "success": status_counts.get("success", 0),
            "failed": status_counts.get("failed", 0),
            "quarantined": status_counts.get("quarantined", 0),
            "downloaded": action_counts.get("downloaded", 0),
            "adopted_existing": action_counts.get("adopted_existing", 0),
            "skipped_existing": action_counts.get("skipped_existing", 0),
            "reused_existing": action_counts.get("reused_existing", 0),
            "recovered_staging_files": sum(
                len(outcome.recovered_staging_paths) for outcome in outcomes
            ),
        },
        reason_counts=dict(sorted(reason_counts.items())),
        invariants=invariants,
        global_failures=failures,
        outcomes=outcomes,
    )


def run_bulk_acquisition(
    *,
    link: Any,
    site: str,
    case_ids: list[str],
    destination: Path,
    backend_root: Path,
    session_key: Callable[[str], str | None],
    inventory: dict[str, Any],
    inventory_json_path: Path,
    inventory_csv_path: Path,
    run_id: str,
    allow_session_zip_fallback: bool = False,
    verify_and_adopt_existing: bool = False,
) -> BulkRunSummary:
    """Process every explicit case and checkpoint inventory after each outcome."""
    started = _utc_now()
    selected = validate_bulk_selection(site, case_ids)
    destination, backend_root = validate_backend_separation(destination, backend_root)
    run_root = backend_root / INVENTORY_DIR_NAME / "runs" / run_id
    case_report_root = run_root / "cases"
    outcomes: list[BulkCaseOutcome] = []
    report_failures: list[str] = []
    run_record = {
        "run_id": run_id,
        "started_at_utc": started,
        "completed_at_utc": "",
        "status": "running",
        "selection_sha256": _selection_digest(selected),
        "requested_count": len(selected),
        "completed_count": 0,
        "report_path": str((run_root / "run_report.json").resolve()),
    }
    inventory["runs"].append(run_record)
    LOGGER.info(
        "Starting explicit bulk acquisition run %s for %d case(s).",
        run_id,
        len(selected),
    )
    write_inventory(
        inventory,
        json_path=inventory_json_path,
        csv_path=inventory_csv_path,
    )

    for case_id in selected:
        LOGGER.info("Processing explicitly selected case %s.", case_id)
        recovered = _recover_stale_staging(backend_root, case_id, run_id)
        if recovered:
            LOGGER.warning(
                "Recovered %d stale staging file(s) for %s.",
                len(recovered),
                case_id,
            )
        case_record = inventory["cases"].get(case_id) or {}
        prior_artifact = case_record.get("artifact")
        case_started = _utc_now()
        try:
            result = acquire_single_case(
                link=link,
                site=site,
                case_id=case_id,
                destination=destination,
                session_key=session_key,
                allow_session_zip_fallback=allow_session_zip_fallback,
                require_case_identity=True,
                allow_existing_valid_resume=True,
                existing_inventory=prior_artifact,
                verify_and_adopt_existing=verify_and_adopt_existing,
                technical_root=backend_root,
                skip_existing_with_awareness=True,
            )
        except Exception as exc:  # noqa: BLE001 - isolate one external case
            result = _failure_from_exception(site, case_id, case_started, exc)
        if recovered:
            result.warnings.extend(f"recovered_staging:{path}" for path in recovered)
        outcome = BulkCaseOutcome(
            case_id=case_id,
            action=_action_for_result(result),
            result=result,
            recovered_staging_paths=recovered,
        )
        outcomes.append(outcome)
        if result.status == "success":
            LOGGER.info("Case %s completed with action %s.", case_id, outcome.action)
        elif result.status == "quarantined":
            LOGGER.warning("Case %s quarantined: %s.", case_id, result.reason_code)
        else:
            LOGGER.error("Case %s failed: %s.", case_id, result.reason_code)
        update_inventory_case(inventory, run_id=run_id, outcome=outcome)
        run_record["completed_count"] = len(outcomes)
        write_inventory(
            inventory,
            json_path=inventory_json_path,
            csv_path=inventory_csv_path,
        )
        try:
            write_result_report(
                result,
                case_report_root / f"{case_id}_acquisition.json",
            )
        except OSError as exc:
            report_failures.append(
                f"case_report_write_failed:{case_id}:{_safe_exception_text(exc)}"
            )

    summary = _build_run_summary(
        run_id=run_id,
        site=site,
        destination=destination,
        backend_root=backend_root,
        case_ids=selected,
        started_at_utc=started,
        outcomes=outcomes,
        global_failures=report_failures,
    )
    run_record["completed_at_utc"] = summary.completed_at_utc
    run_record["status"] = summary.status
    run_record["counts"] = summary.counts
    write_inventory(
        inventory,
        json_path=inventory_json_path,
        csv_path=inventory_csv_path,
    )
    return summary


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _run_markdown(summary: BulkRunSummary) -> str:
    lines = [
        "# Bulk `local.db` Acquisition Report",
        "",
        f"- Run ID: `{summary.run_id}`",
        f"- Status: `{summary.status}`",
        f"- Site: `{summary.site}`",
        f"- Source access: `{summary.source_access_mode}`",
        f"- Destination: `{summary.destination_root}`",
        f"- Backend: `{summary.backend_root}`",
        f"- Requested: `{summary.counts.get('requested', 0)}`",
        f"- Downloaded: `{summary.counts.get('downloaded', 0)}`",
        f"- Reused existing: `{summary.counts.get('reused_existing', 0)}`",
        f"- Failed: `{summary.counts.get('failed', 0)}`",
        f"- Quarantined: `{summary.counts.get('quarantined', 0)}`",
        "",
        "## Case results",
        "",
        "| Case ID | Action | Status | Reason code | Reason | Saved/quarantine path |",
        "|---|---|---|---|---|---|",
    ]
    for outcome in summary.outcomes:
        result = outcome.result
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    outcome.case_id,
                    outcome.action,
                    result.status,
                    result.reason_code or "success",
                    result.reason,
                    result.saved_path or result.quarantine_path,
                )
            )
            + " |"
        )
    lines.extend(["", "## Invariants", ""])
    lines.extend(
        f"- `{name}`: `{'PASS' if passed else 'FAIL'}`"
        for name, passed in summary.invariants.items()
    )
    if summary.global_failures:
        lines.extend(["", "## Global failures", ""])
        lines.extend(f"- {_markdown_cell(item)}" for item in summary.global_failures)
    lines.append("")
    return "\n".join(lines)


def _outcome_csv(summary: BulkRunSummary) -> str:
    from io import StringIO

    fields = [
        "case_id",
        "action",
        "status",
        "reason_code",
        "reason",
        "saved_path",
        "quarantine_path",
        "size_bytes",
        "sha256",
        "sqlite_status",
        "identity_status",
        "remote_container",
        "remote_case_folder",
        "remote_session_folder",
        "remote_archive_name",
        "remote_database_name",
        "remote_artifact_size_bytes",
        "remote_artifact_usertime",
        "recovered_staging_paths",
    ]
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for outcome in summary.outcomes:
        result = outcome.result
        validation = result.database_validation
        writer.writerow(
            {
                "case_id": outcome.case_id,
                "action": outcome.action,
                "status": result.status,
                "reason_code": result.reason_code or "success",
                "reason": result.reason,
                "saved_path": result.saved_path,
                "quarantine_path": result.quarantine_path,
                "size_bytes": result.size_bytes,
                "sha256": result.sha256,
                "sqlite_status": validation.get("status", ""),
                "identity_status": validation.get("case_identity", {}).get("status", ""),
                "remote_container": result.remote_container,
                "remote_case_folder": result.remote_case_folder,
                "remote_session_folder": result.remote_session_folder,
                "remote_archive_name": result.remote_archive_name,
                "remote_database_name": result.remote_database_name,
                "remote_artifact_size_bytes": result.remote_artifact_size_bytes,
                "remote_artifact_usertime": result.remote_artifact_usertime,
                "recovered_staging_paths": json.dumps(outcome.recovered_staging_paths),
            }
        )
    return buffer.getvalue()


def write_run_reports(summary: BulkRunSummary, run_root: Path) -> tuple[Path, Path, Path]:
    """Write complete JSON, Markdown, and CSV reports for one run."""
    json_path = _atomic_write_text(
        run_root / "run_report.json",
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    markdown_path = _atomic_write_text(
        run_root / "run_report.md",
        _run_markdown(summary),
    )
    csv_path = _atomic_write_text(
        run_root / "case_results.csv",
        _outcome_csv(summary),
    )
    return json_path, markdown_path, csv_path


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit, no-discovery bulk acquisition CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Acquire explicitly selected commercial Sync.com local.db files "
            "with resumable inventory and no source-share writes."
        )
    )
    parser.add_argument("--site", required=True, help="Explicit three-digit site ID.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Explicit case ID; repeat for every selected case.",
    )
    selection.add_argument(
        "--case-manifest",
        type=Path,
        help="UTF-8 text file containing one explicit case ID per line.",
    )
    parser.add_argument("--sites-file", required=True, type=Path)
    sync_source = parser.add_mutually_exclusive_group()
    sync_source.add_argument("--sync-tool-root", type=Path)
    sync_source.add_argument("--sync-tool-zip", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--backend-dir",
        required=True,
        type=Path,
        help="Technical inventory, staging, quarantine, and report root outside destination.",
    )
    parser.add_argument("--allow-session-zip-fallback", action="store_true")
    parser.add_argument(
        "--verify-and-adopt-existing",
        action="store_true",
        help=(
            "For an existing valid local.db with no inventory, download and "
            "validate the current remote artifact and adopt only an exact "
            "size/SHA-256 match; never overwrite the existing file."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _run_cli(args: argparse.Namespace) -> int:
    """Execute parsed bulk arguments with durable inventory checkpoints."""
    selected = resolve_case_selection(
        site=args.site,
        case_ids=args.case_ids,
        case_manifest=args.case_manifest,
    )
    destination, backend_root = validate_backend_separation(
        args.destination,
        args.backend_dir,
    )
    run_id = _run_id()
    inventory_json, inventory_csv = _inventory_paths(backend_root)
    run_root = backend_root / INVENTORY_DIR_NAME / "runs" / run_id
    lock_path = backend_root / INVENTORY_DIR_NAME / "acquisition.lock"
    link: Any | None = None

    LOGGER.info(
        "Preparing bulk acquisition for site %s with %d explicit case(s).",
        args.site,
        len(selected),
    )
    with DestinationLock(lock_path, run_id):
        inventory = load_inventory(
            inventory_json,
            site=args.site,
            destination=destination,
        )
        try:
            site_entry = load_site_entry(args.sites_file, args.site)
            sync_link_class, load_password, session_key = _load_sync_client(
                args.sync_tool_root,
                args.sync_tool_zip,
            )
            password = load_password()
            link = sync_link_class(site_entry["url"], password).open()
            summary = run_bulk_acquisition(
                link=link,
                site=args.site,
                case_ids=selected,
                destination=destination,
                backend_root=backend_root,
                session_key=session_key,
                inventory=inventory,
                inventory_json_path=inventory_json,
                inventory_csv_path=inventory_csv,
                run_id=run_id,
                allow_session_zip_fallback=args.allow_session_zip_fallback,
                verify_and_adopt_existing=args.verify_and_adopt_existing,
            )
        except Exception as exc:  # noqa: BLE001 - global connection/config boundary
            started = _utc_now()
            global_failures = [_safe_exception_text(exc)]
            outcomes = [
                BulkCaseOutcome(
                    case_id=case_id,
                    action="failed",
                    result=_failure_from_exception(args.site, case_id, started, exc),
                )
                for case_id in selected
            ]
            summary = _build_run_summary(
                run_id=run_id,
                site=args.site,
                destination=destination,
                backend_root=backend_root,
                case_ids=selected,
                started_at_utc=started,
                outcomes=outcomes,
                global_failures=global_failures,
            )
            existing_run = next(
                (
                    record
                    for record in inventory["runs"]
                    if record.get("run_id") == run_id
                ),
                None,
            )
            if existing_run is None:
                existing_run = {
                    "run_id": run_id,
                    "started_at_utc": started,
                    "selection_sha256": _selection_digest(selected),
                    "requested_count": len(selected),
                    "report_path": str((run_root / "run_report.json").resolve()),
                }
                inventory["runs"].append(existing_run)
            for outcome in outcomes:
                last_attempt = (
                    inventory["cases"].get(outcome.case_id, {}).get("last_attempt") or {}
                )
                if last_attempt.get("run_id") != run_id:
                    update_inventory_case(inventory, run_id=run_id, outcome=outcome)
            existing_run.update(
                {
                    "completed_at_utc": summary.completed_at_utc,
                    "status": summary.status,
                    "completed_count": summary.counts.get("requested", 0),
                    "counts": summary.counts,
                }
            )
            try:
                write_inventory(
                    inventory,
                    json_path=inventory_json,
                    csv_path=inventory_csv,
                )
            except OSError as inventory_exc:
                global_failures.append(
                    "inventory_write_after_global_failure_failed:"
                    + _safe_exception_text(inventory_exc)
                )
                summary = _build_run_summary(
                    run_id=run_id,
                    site=args.site,
                    destination=destination,
                    backend_root=backend_root,
                    case_ids=selected,
                    started_at_utc=started,
                    outcomes=outcomes,
                    global_failures=global_failures,
                )
        finally:
            if link is not None:
                session = getattr(link, "session", None)
                close = getattr(session, "close", None)
                if callable(close):
                    close()

        json_report, markdown_report, csv_report = write_run_reports(summary, run_root)

    print(f"Status: {summary.status}")
    print(f"Site: {summary.site}")
    print(f"Requested cases: {summary.counts.get('requested', 0)}")
    print(f"Successful cases: {summary.counts.get('success', 0)}")
    print(f"Downloaded cases: {summary.counts.get('downloaded', 0)}")
    print(f"Skipped existing cases: {summary.counts.get('skipped_existing', 0)}")
    print(f"Reused existing cases: {summary.counts.get('reused_existing', 0)}")
    print(f"Failed cases: {summary.counts.get('failed', 0)}")
    print(f"Quarantined cases: {summary.counts.get('quarantined', 0)}")
    for outcome in summary.outcomes:
        result = outcome.result
        output = result.saved_path or result.quarantine_path or result.reason
        print(f"{outcome.case_id}: {outcome.action}: {result.status}: {output}")
    print(f"Inventory JSON: {inventory_json.resolve()}")
    print(f"Inventory CSV: {inventory_csv.resolve()}")
    print(f"Run report JSON: {json_report}")
    print(f"Run report Markdown: {markdown_report}")
    print(f"Run case CSV: {csv_report}")
    return 0 if summary.status == "success" else 1


def main(argv: list[str] | None = None) -> int:
    """Parse and run bulk acquisition with concise configuration failures."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        return _run_cli(args)
    except (AcquisitionConfigurationError, OSError) as exc:
        print("Status: failed")
        print(f"Reason: {_safe_exception_text(exc)}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
