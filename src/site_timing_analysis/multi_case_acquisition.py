# Project: Site Timing Analysis
# File: src/site_timing_analysis/multi_case_acquisition.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Validates read-only local.db acquisition across an explicit five-case test set.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
"""Dependency-gated five-case commercial ``local.db`` acquisition validation.

Inputs are one explicit three-digit site ID, at least five unique explicit case
IDs, an external Sync site configuration, and an external destination. The
module reuses the single-case acquisition and validation contract sequentially
through one authenticated, read-only Sync connection.

Outputs are one validated ``<destination>/<case_id>/local.db`` per successful
case, sanitized case-level JSON reports, and machine-/human-readable aggregate
summaries beneath ``<destination>/_reports``. A failed or ambiguous case is
isolated and does not prevent the remaining explicitly selected cases from
being evaluated. This validation surface is intentionally not a bulk or
resumable acquisition implementation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
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


MINIMUM_VALIDATION_CASES = 5


@dataclass
class MultiCaseAcquisitionSummary:
    """Machine-readable outcome for one explicit multi-case validation run."""

    status: str
    reason: str
    site: str
    requested_case_ids: list[str]
    started_at_utc: str
    completed_at_utc: str
    source_access_mode: str = "read_only"
    counts: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)
    invariants: dict[str, bool] = field(default_factory=dict)
    structure_summary: dict[str, Any] = field(default_factory=dict)
    global_failures: list[str] = field(default_factory=list)
    case_results: list[AcquisitionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable aggregate report."""
        payload = asdict(self)
        payload["case_results"] = [result.to_dict() for result in self.case_results]
        return payload


def validate_case_set_selection(site: str, case_ids: list[str]) -> list[str]:
    """Validate an explicit, unique, same-site set of at least five cases."""
    normalized = [case_id.strip() for case_id in case_ids]
    if len(normalized) < MINIMUM_VALIDATION_CASES:
        raise AcquisitionConfigurationError(
            f"At least {MINIMUM_VALIDATION_CASES} explicit case IDs are required; "
            f"received {len(normalized)}."
        )
    for case_id in normalized:
        _validate_explicit_selection(site, case_id)
        if not case_id.casefold().startswith(f"{site}_".casefold()):
            raise AcquisitionConfigurationError(
                f"Case ID {case_id!r} does not use the selected site prefix {site!r}."
            )
    folded = [case_id.casefold() for case_id in normalized]
    if len(folded) != len(set(folded)):
        raise AcquisitionConfigurationError(
            "Explicit case IDs must be unique, including case-insensitive duplicates."
        )
    return normalized


def _build_summary(
    *,
    site: str,
    case_ids: list[str],
    started_at_utc: str,
    case_results: list[AcquisitionResult],
    destination: Path,
    global_failures: list[str] | None = None,
) -> MultiCaseAcquisitionSummary:
    """Evaluate aggregate invariants without changing case-level outcomes."""
    destination = destination.expanduser().resolve()
    failures = list(global_failures or [])
    status_counts = Counter(result.status for result in case_results)
    reason_counts = Counter(result.reason_code or "success" for result in case_results)
    result_ids = [result.case_id.casefold() for result in case_results]
    successful = [result for result in case_results if result.status == "success"]
    saved_paths = [result.saved_path.casefold() for result in successful if result.saved_path]

    expected_paths = {
        case_id.casefold(): str((destination / case_id / "local.db").resolve()).casefold()
        for case_id in case_ids
    }
    case_specific_paths = all(
        result.saved_path
        and result.saved_path.casefold() == expected_paths.get(result.case_id.casefold(), "")
        for result in successful
    )
    identity_verified = all(
        result.database_validation.get("case_identity", {}).get("status") == "PASS"
        for result in successful
    )
    sqlite_valid = all(
        result.database_validation.get("status") == "PASS" for result in successful
    )

    invariants = {
        "requested_at_least_five_cases": len(case_ids) >= MINIMUM_VALIDATION_CASES,
        "unique_requested_case_ids": len({case_id.casefold() for case_id in case_ids})
        == len(case_ids),
        "valid_selected_site_prefix": all(
            case_id.casefold().startswith(f"{site}_".casefold()) for case_id in case_ids
        ),
        "complete_case_result_accounting": len(case_results) == len(case_ids),
        "unique_processed_case_ids": len(result_ids) == len(set(result_ids)),
        "at_least_five_cases_acquired": len(successful) >= MINIMUM_VALIDATION_CASES,
        "all_requested_cases_successful": len(successful) == len(case_ids),
        "all_sqlite_validations_passed": sqlite_valid and len(successful) == len(case_ids),
        "all_case_identities_verified": identity_verified and len(successful) == len(case_ids),
        "all_saved_paths_are_case_specific": case_specific_paths
        and len(successful) == len(case_ids),
        "unique_saved_paths": len(saved_paths) == len(set(saved_paths)),
        "no_global_failures": not failures,
    }

    structure_modes = Counter(
        "session_export_zip" if result.remote_archive_name else "direct_local_db"
        for result in successful
    )
    containers = Counter(result.remote_container for result in successful)
    structure_summary = {
        "acquisition_modes": dict(sorted(structure_modes.items())),
        "remote_containers": dict(sorted(containers.items())),
        "distinct_timestamped_session_folder_names": len(
            {result.remote_session_folder for result in successful}
        ),
    }

    complete = all(invariants.values())
    return MultiCaseAcquisitionSummary(
        status="success" if complete else "incomplete",
        reason=(
            "All explicitly selected cases passed acquisition and validation."
            if complete
            else "One or more cases or aggregate validation invariants did not pass."
        ),
        site=site,
        requested_case_ids=case_ids,
        started_at_utc=started_at_utc,
        completed_at_utc=_utc_now(),
        counts={
            "requested": len(case_ids),
            "success": status_counts.get("success", 0),
            "failed": status_counts.get("failed", 0),
            "quarantined": status_counts.get("quarantined", 0),
        },
        reason_counts=dict(sorted(reason_counts.items())),
        invariants=invariants,
        structure_summary=structure_summary,
        global_failures=failures,
        case_results=case_results,
    )


def acquire_case_set(
    *,
    link: Any,
    site: str,
    case_ids: list[str],
    destination: Path,
    session_key: Callable[[str], str | None],
    allow_session_zip_fallback: bool = False,
) -> MultiCaseAcquisitionSummary:
    """Acquire and validate an explicit five-or-more-case set sequentially."""
    started = _utc_now()
    selected = validate_case_set_selection(site, case_ids)
    destination = destination.expanduser().resolve()
    case_report_root = destination / "_reports" / "cases"
    results: list[AcquisitionResult] = []
    report_failures: list[str] = []

    for case_id in selected:
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
            )
        except Exception as exc:  # noqa: BLE001 - isolate one external case
            result = _failure_from_exception(site, case_id, case_started, exc)
        results.append(result)
        try:
            write_result_report(
                result,
                case_report_root / f"{case_id}_acquisition.json",
            )
        except OSError as exc:
            report_failures.append(
                f"case_report_write_failed:{case_id}:{_safe_exception_text(exc)}"
            )

    return _build_summary(
        site=site,
        case_ids=selected,
        started_at_utc=started,
        case_results=results,
        destination=destination,
        global_failures=report_failures,
    )


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _summary_markdown(summary: MultiCaseAcquisitionSummary) -> str:
    """Render the concise human-readable validation summary."""
    lines = [
        "# Multi-case `local.db` Acquisition Validation",
        "",
        f"- Status: `{summary.status}`",
        f"- Site: `{summary.site}`",
        f"- Source access: `{summary.source_access_mode}`",
        f"- Requested: `{summary.counts.get('requested', 0)}`",
        f"- Successful: `{summary.counts.get('success', 0)}`",
        f"- Failed: `{summary.counts.get('failed', 0)}`",
        f"- Quarantined: `{summary.counts.get('quarantined', 0)}`",
        "",
        "## Case results",
        "",
        "| Case ID | Status | Reason code | Reason | SQLite | Identity | Saved path |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in summary.case_results:
        validation = result.database_validation
        identity = validation.get("case_identity", {})
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    result.case_id,
                    result.status,
                    result.reason_code or "success",
                    result.reason,
                    validation.get("status", ""),
                    identity.get("status", ""),
                    result.saved_path or result.quarantine_path,
                )
            )
            + " |"
        )

    lines.extend(["", "## Aggregate invariants", ""])
    lines.extend(
        f"- `{name}`: `{'PASS' if passed else 'FAIL'}`"
        for name, passed in summary.invariants.items()
    )
    lines.extend(["", "## Structure summary", "", "```json"])
    lines.append(json.dumps(summary.structure_summary, indent=2, sort_keys=True))
    lines.append("```")
    if summary.global_failures:
        lines.extend(["", "## Global failures", ""])
        lines.extend(f"- {_markdown_cell(reason)}" for reason in summary.global_failures)
    lines.append("")
    return "\n".join(lines)


def write_multi_case_reports(
    summary: MultiCaseAcquisitionSummary,
    *,
    json_path: Path,
    markdown_path: Path,
) -> tuple[Path, Path]:
    """Write sanitized aggregate JSON and Markdown reports atomically."""
    json_target = json_path.expanduser().resolve()
    markdown_target = markdown_path.expanduser().resolve()
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)

    json_temporary = json_target.with_suffix(json_target.suffix + ".tmp")
    markdown_temporary = markdown_target.with_suffix(markdown_target.suffix + ".tmp")
    json_temporary.write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_temporary.write_text(_summary_markdown(summary), encoding="utf-8")
    json_temporary.replace(json_target)
    markdown_temporary.replace(markdown_target)
    return json_target, markdown_target


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit multi-case validation CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Acquire and validate at least five explicitly selected commercial "
            "Sync.com local.db files without modifying the source share."
        )
    )
    parser.add_argument("--site", required=True, help="Explicit three-digit site ID.")
    parser.add_argument(
        "--case-id",
        action="append",
        required=True,
        dest="case_ids",
        help="Explicit case ID; repeat this argument at least five times.",
    )
    parser.add_argument("--sites-file", required=True, type=Path)
    sync_source = parser.add_mutually_exclusive_group()
    sync_source.add_argument("--sync-tool-root", type=Path)
    sync_source.add_argument("--sync-tool-zip", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--report-markdown", type=Path)
    parser.add_argument("--allow-session-zip-fallback", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the dependency-gated multi-case validation and print exact outputs."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    started = _utc_now()
    destination = args.destination.expanduser().resolve()
    json_path = args.report_json or destination / "_reports" / "acquisition_summary.json"
    markdown_path = args.report_markdown or destination / "_reports" / "acquisition_summary.md"
    link: Any | None = None

    try:
        selected = validate_case_set_selection(args.site, args.case_ids)
        site_entry = load_site_entry(args.sites_file, args.site)
        sync_link_class, load_password, session_key = _load_sync_client(
            args.sync_tool_root,
            args.sync_tool_zip,
        )
        password = load_password()
        link = sync_link_class(site_entry["url"], password).open()
        summary = acquire_case_set(
            link=link,
            site=args.site,
            case_ids=selected,
            destination=destination,
            session_key=session_key,
            allow_session_zip_fallback=args.allow_session_zip_fallback,
        )
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic boundary
        selected = [case_id.strip() for case_id in args.case_ids]
        global_reason = _safe_exception_text(exc)
        results = [
            _failure_from_exception(args.site, case_id, started, exc)
            for case_id in selected
        ]
        summary = _build_summary(
            site=args.site,
            case_ids=selected,
            started_at_utc=started,
            case_results=results,
            destination=destination,
            global_failures=[global_reason],
        )
    finally:
        if link is not None:
            session = getattr(link, "session", None)
            close = getattr(session, "close", None)
            if callable(close):
                close()

    json_report, markdown_report = write_multi_case_reports(
        summary,
        json_path=json_path,
        markdown_path=markdown_path,
    )
    print(f"Status: {summary.status}")
    print(f"Site: {summary.site}")
    print(f"Requested cases: {summary.counts.get('requested', 0)}")
    print(f"Successful cases: {summary.counts.get('success', 0)}")
    print(f"Failed cases: {summary.counts.get('failed', 0)}")
    print(f"Quarantined cases: {summary.counts.get('quarantined', 0)}")
    for result in summary.case_results:
        output = result.saved_path or result.quarantine_path or result.reason
        print(f"{result.case_id}: {result.status}: {output}")
    print(f"Machine-readable summary: {json_report}")
    print(f"Human-readable summary: {markdown_report}")
    return 0 if summary.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
