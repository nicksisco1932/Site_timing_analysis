# Project: Site Timing Analysis
# File: scripts/run_asui_122_timeline_analysis.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-10
# Purpose: Runs and validates an allowlisted site timeline analysis export.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import time

_PROCESS_WALL_STARTED = time.perf_counter()
_PROCESS_CPU_STARTED = time.process_time()

import argparse
import csv
from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from site_timing_analysis.config import build_run_config  # noqa: E402
from site_timing_analysis.analytical_store import analysis_configuration  # noqa: E402
from site_timing_analysis.discovery import discover_cases  # noqa: E402
from site_timing_analysis.first_slice_cli import run_first_slice  # noqa: E402
from site_timing_analysis.output_layout import output_layout  # noqa: E402
from site_timing_analysis.profiling import PerformanceProfiler  # noqa: E402
from site_timing_analysis.preflight_baseline import (  # noqa: E402
    DEFAULT_MAX_AGE_HOURS,
    capture_baseline,
    load_reusable_baseline,
)
from site_timing_analysis.timeline_cache import TimelineCacheReader  # noqa: E402
from site_timing_analysis.timing_gantt_deliverables import (  # noqa: E402
    PHASE_ORDER,
    PHASE_STATE_MAP,
    _state_to_phase,
    publish_top_level_timeline_plots,
)


REQUESTED_STATES = tuple(
    state
    for phase in PHASE_ORDER
    for state in PHASE_STATE_MAP[phase]
)
VALID_EVENT_SOURCES = {"auditlog", "sessions", "timing_log"}
SOURCE_PRIORITY = {"auditlog": 0, "sessions": 1, "timing_log": 2}
EPSILON_SEC = 1e-7
RECONCILIATION_TOLERANCE_MIN = 0.1


DEFAULT_SITE_CODE = "ASUI_122"
DEFAULT_ALLOWLIST = tuple(f"122_01-{index:03d}" for index in range(1, 10))


def _site_slug(site_code: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in site_code).strip("_")


def _default_site_root(site_code: str = DEFAULT_SITE_CODE) -> Path:
    return Path(rf"C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - {site_code}")


def _default_run_dir(site_code: str = DEFAULT_SITE_CODE) -> Path:
    date_prefix = datetime.now().strftime("%Y.%m.%d")
    return REPO_ROOT / "outputs" / "timing_gantt" / f"{date_prefix}_{site_code}_timing_Gantt"


def _default_rollup(site_code: str = DEFAULT_SITE_CODE) -> Path | None:
    if site_code != DEFAULT_SITE_CODE:
        return None
    return (
        REPO_ROOT
        / "outputs"
        / "timing_gantt"
        / "2026.03.19_ASUI_122_timing_Gantt"
        / "final"
        / "operational_state_summary_by_case.csv"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and validate an allowlisted wide operational-state timeline analysis."
    )
    parser.add_argument("--site", "--site-code", dest="site_code", default=DEFAULT_SITE_CODE)
    parser.add_argument("--site-root", default=None, help="Site root containing case folders.")
    parser.add_argument(
        "--case-list",
        "--allowlist-file",
        dest="case_list",
        default=None,
        help="Newline-delimited case IDs or full case-folder paths. Non-case lines are reported and excluded.",
    )
    parser.add_argument(
        "--select-all-canonical",
        action="store_true",
        help=(
            "Select every currently discovered canonical case folder. This explicit option "
            "overrides the ASUI_122 compatibility allowlist without changing the default."
        ),
    )
    parser.add_argument("--run-dir", default=None, help="Run output directory. Defaults to dated site output.")
    parser.add_argument("--rollup", default=None, help="Optional five-phase roll-up comparator CSV.")
    parser.add_argument("--canonical-prefix", default=None, help="Canonical folder prefix, e.g. 064_.")
    parser.add_argument(
        "--timing-log-dir",
        default=None,
        help=(
            "Optional directory containing exact <case_id>.csv or <case_id>.xlsx timing logs. "
            "Missing case workbooks are reported and do not stop processing."
        ),
    )
    parser.add_argument(
        "--allow-unselected-canonical",
        action="store_true",
        help=(
            "Allow an explicit --case-list to select a canonical subset while reporting "
            "other canonical folders as excluded. The default strict unexpected-folder gate is unchanged."
        ),
    )
    parser.add_argument(
        "--publish-partial",
        action="store_true",
        help="Publish successfully processed case rows when only case-level failures remain; the report marks the CSV partial.",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Collect temporary wall-clock/CPU profiling reports under Backend/reports.",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Explicit analytical-store path; required only for read-only cache mode.",
    )
    parser.add_argument(
        "--cache-mode",
        choices=("off", "read-only"),
        default="off",
        help="Opt-in exact analytical-store cache lookup. Default: off.",
    )
    parser.add_argument(
        "--baseline-mode",
        choices=("live", "reuse"),
        default="live",
        help="Run the live preflight by default, or explicitly reuse an exact verified snapshot.",
    )
    parser.add_argument(
        "--baseline-snapshot",
        default=None,
        help="Explicit reusable baseline JSON path; required only with --baseline-mode=reuse.",
    )
    parser.add_argument(
        "--baseline-max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help=f"Maximum reusable snapshot age in hours. Default: {DEFAULT_MAX_AGE_HOURS:g}.",
    )
    args = parser.parse_args(argv)
    if args.select_all_canonical and args.case_list:
        parser.error("--select-all-canonical cannot be combined with --case-list")
    if args.cache_mode == "read-only" and not args.database:
        parser.error("--database is required when --cache-mode=read-only")
    if args.database and args.cache_mode == "off":
        parser.error("--database requires --cache-mode=read-only")
    if args.baseline_mode == "reuse" and not args.baseline_snapshot:
        parser.error("--baseline-snapshot is required when --baseline-mode=reuse")
    if args.baseline_mode == "live" and args.baseline_snapshot:
        parser.error("--baseline-snapshot requires --baseline-mode=reuse")
    if args.baseline_max_age_hours <= 0:
        parser.error("--baseline-max-age-hours must be greater than zero")
    return args


def _backend_root(run_dir: Path) -> Path:
    return run_dir / "Backend"


def _profile_stage(
    profiler: PerformanceProfiler | None,
    stage: str,
    *,
    case_id: str | None = None,
):
    """Return an opt-in stage timer or a no-op context manager."""
    if profiler is None:
        return nullcontext()
    return profiler.stage(stage, case_id=case_id)


@contextmanager
def _profile_artifact_write(
    profiler: PerformanceProfiler | None,
    *,
    subtype: str,
    case_id: str | None = None,
):
    """Measure one artifact write in both its parent and specific subtype."""
    with _profile_stage(profiler, "all artifact writes", case_id=case_id):
        with _profile_stage(profiler, subtype, case_id=case_id):
            yield


def _backend_layout(run_dir: Path):
    return output_layout(_backend_root(run_dir))


def _public_report_dir(run_dir: Path) -> Path:
    return run_dir / "Report"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _parse_datetime(value: str, *, context: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError(f"{context}: empty timestamp")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{context}: invalid ISO timestamp {text!r}") from exc


def _format_datetime(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _format_clock(value: datetime) -> str:
    """Format a datetime for the public CSV without date or fractional seconds."""
    hour = value.hour % 12 or 12
    meridiem = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d}:{value.second:02d} {meridiem}"


def _event_sort_key(row: dict[str, str]) -> tuple[Any, ...]:
    timestamp = _parse_datetime(row["timestamp"], context="event")
    source = row.get("source", "").strip()
    is_synthetic = row.get("is_synthetic", "").strip().lower() == "true"
    raw_first = 0 if not is_synthetic else 1
    row_number_text = row.get("row_number", "").strip()
    row_number = int(row_number_text) if row_number_text else 10**12
    return (
        timestamp,
        raw_first,
        row_number,
        SOURCE_PRIORITY.get(source, 99),
        row.get("event_type", ""),
        row.get("source_detail", ""),
    )


def _state_mapping_validation() -> dict[str, Any]:
    memberships: dict[str, list[str]] = defaultdict(list)
    for phase, states in PHASE_STATE_MAP.items():
        for state in states:
            memberships[state].append(phase)

    failures: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for state in REQUESTED_STATES:
        phases = memberships.get(state, [])
        implementation_phase = _state_to_phase(state)
        status = "PASS"
        if len(phases) != 1 or implementation_phase == "Other" or implementation_phase != phases[0]:
            status = "FAIL"
            failures.append(
                {
                    "failure_type": "mapping_or_schema_failure",
                    "state": state,
                    "phases": phases,
                    "implementation_phase": implementation_phase,
                }
            )
        details.append(
            {
                "state": state,
                "declared_phases": "|".join(phases),
                "implementation_phase": implementation_phase,
                "status": status,
            }
        )

    return {"status": "PASS" if not failures else "FAIL", "details": details, "failures": failures}


def _read_case_list(
    path: Path | None,
    site_root: Path,
    site_code: str,
    folders: list[Path],
    *,
    select_all_canonical: bool = False,
) -> dict[str, Any]:
    """Resolve newline-delimited IDs or full folder paths into a selection request."""
    if path is None:
        if site_code == DEFAULT_SITE_CODE and not select_all_canonical:
            return {
                "requested_case_ids": list(DEFAULT_ALLOWLIST),
                "invalid_entries": [],
                "duplicate_case_ids": [],
                "selection_source": "built_in_default_allowlist",
            }
        return {
            "requested_case_ids": [folder.name for folder in folders],
            "invalid_entries": [],
            "duplicate_case_ids": [],
            "selection_source": "all_discovered_canonical_folders",
        }

    if not path.is_file():
        raise FileNotFoundError(f"Case list is missing: {path}")
    requested: list[str] = []
    invalid_entries: list[dict[str, str]] = []
    duplicate_case_ids: list[str] = []
    seen: set[str] = set()
    site_root_resolved = site_root.resolve()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        token = raw_line.strip().strip('"')
        if not token or token.startswith("#"):
            continue
        candidate = Path(token)
        if candidate.is_absolute() or "\\" in token or "/" in token:
            candidate = candidate.expanduser().resolve()
            case_id = candidate.name
            try:
                candidate.relative_to(site_root_resolved)
            except ValueError:
                invalid_entries.append({"line": str(line_number), "value": token, "reason": "outside_site_root"})
                continue
            if not candidate.is_dir():
                invalid_entries.append({"line": str(line_number), "value": token, "reason": "not_a_case_folder"})
                continue
        else:
            case_id = token
        if case_id in seen:
            invalid_entries.append({"line": str(line_number), "value": token, "reason": "duplicate_case_id"})
            if case_id not in duplicate_case_ids:
                duplicate_case_ids.append(case_id)
            continue
        seen.add(case_id)
        requested.append(case_id)

    folder_ids = {folder.name for folder in folders}
    return {
        "requested_case_ids": requested,
        "invalid_entries": invalid_entries,
        "duplicate_case_ids": duplicate_case_ids,
        "selection_source": str(path),
        "missing_requested_case_ids": sorted(set(requested).difference(folder_ids)),
    }


def _discover_and_select(
    site_root: Path,
    run_dir: Path,
    *,
    site_code: str,
    case_list_path: Path | None,
    canonical_prefix: str | None,
    allow_unselected_canonical: bool = False,
    select_all_canonical: bool = False,
    performance_profiler: PerformanceProfiler | None = None,
) -> dict[str, Any]:
    if not site_root.is_dir():
        raise FileNotFoundError(f"Site root is missing: {site_root}")

    with _profile_stage(performance_profiler, "directory discovery"):
        folders = sorted(
            (path for path in site_root.iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        )
        folder_names = [path.name for path in folders]
    selection_timer = _profile_stage(performance_profiler, "case selection")
    selection_timer.__enter__()
    selection = _read_case_list(
        case_list_path,
        site_root,
        site_code,
        folders,
        select_all_canonical=select_all_canonical,
    )
    requested_ids = selection["requested_case_ids"]
    allowlist_set = set(requested_ids)
    if canonical_prefix is None:
        site_suffix = site_code.rsplit("_", 1)[-1]
        canonical_prefix = f"{site_suffix}_" if site_suffix.isdigit() else ""
    canonical_prefix = canonical_prefix.strip()
    selected = [
        path
        for path in folders
        if path.name in allowlist_set and (not canonical_prefix or path.name.startswith(canonical_prefix))
    ]
    selected_names = {path.name for path in selected}
    unselected_canonical = sorted(
        name for name in folder_names
        if canonical_prefix and name.startswith(canonical_prefix) and name not in selected_names
    )
    unexpected_canonical = [] if allow_unselected_canonical else unselected_canonical
    quarantined_noncanonical = sorted(
        name
        for name in folder_names
        if name not in selected_names and name not in unselected_canonical
    )
    missing_allowlist = sorted(set(requested_ids).difference(folder_names))

    rows = []
    for path in folders:
        if path in selected:
            category = "selected"
            reason = "explicit_allowlist"
        elif path.name in unexpected_canonical:
            category = "global_abort"
            reason = f"unexpected_canonical_prefix:{canonical_prefix}"
        elif path.name in unselected_canonical:
            category = "excluded_unselected_canonical"
            reason = "outside_explicit_case_list"
        else:
            category = "quarantined_noncanonical"
            reason = "outside_explicit_allowlist"
        rows.append({"folder_id": path.name, "folder_path": str(path), "category": category, "reason": reason})

    invariant_failures: list[dict[str, Any]] = []
    if len(folder_names) != len(set(folder_names)):
        invariant_failures.append(
            {
                "failure_type": "duplicate_discovered_case_id",
                "reason": "discovered folder IDs are not unique",
            }
        )
    if selection.get("duplicate_case_ids"):
        invariant_failures.append(
            {
                "failure_type": "duplicate_selected_case_id",
                "reason": ",".join(selection["duplicate_case_ids"]),
            }
        )
    if canonical_prefix and any(not path.name.startswith(canonical_prefix) for path in selected):
        invariant_failures.append(
            {
                "failure_type": "invalid_canonical_prefix_selection",
                "reason": f"selected IDs must start with {canonical_prefix}",
            }
        )
    accounted_ids = [row["folder_id"] for row in rows]
    if len(rows) != len(folders) or set(accounted_ids) != set(folder_names):
        invariant_failures.append(
            {
                "failure_type": "incomplete_discovered_folder_accounting",
                "reason": f"accounted={len(rows)} discovered={len(folders)}",
            }
        )
    if selection["invalid_entries"]:
        invariant_failures.append(
            {
                "failure_type": "invalid_case_list_entry",
                "reason": f"count={len(selection['invalid_entries'])}",
            }
        )
    invariant_status = "PASS" if not invariant_failures else "FAIL"
    category_counts = dict(Counter(row["category"] for row in rows))
    selection_timer.__exit__(None, None, None)

    report_dir = _backend_layout(run_dir).reports_dir
    with _profile_artifact_write(performance_profiler, subtype="CSV export"):
        _write_csv(
            report_dir / "discovery_selection.csv",
            ["folder_id", "folder_path", "category", "reason"],
            rows,
        )
    payload = {
        "actual_discovered_folders": len(folders),
        "actual_quarantined_noncanonical_folders": len(quarantined_noncanonical),
        "actual_selected_cases": len(selected),
        "selected_case_ids": [path.name for path in selected],
        "missing_allowlist_case_ids": missing_allowlist,
        "unexpected_canonical_case_ids": unexpected_canonical,
        "unselected_canonical_case_ids": unselected_canonical,
        "allow_unselected_canonical": allow_unselected_canonical,
        "select_all_canonical": select_all_canonical,
        "invalid_case_list_entries": selection["invalid_entries"],
        "duplicate_case_ids": selection.get("duplicate_case_ids", []),
        "noncanonical_requested_case_ids": [
            case_id for case_id in requested_ids if canonical_prefix and not case_id.startswith(canonical_prefix)
        ],
        "case_list_source": selection["selection_source"],
        "canonical_prefix": canonical_prefix,
        "category_counts": category_counts,
        "semantic_invariant_status": invariant_status,
        "semantic_invariant_failures": invariant_failures,
        "semantic_invariants": {
            "unique_case_ids": "PASS" if len(folder_names) == len(set(folder_names)) and not selection.get("duplicate_case_ids") else "FAIL",
            "valid_canonical_prefix_selection": "PASS" if not canonical_prefix or all(path.name.startswith(canonical_prefix) for path in selected) else "FAIL",
            "complete_discovered_folder_accounting": "PASS" if len(rows) == len(folders) and set(accounted_ids) == set(folder_names) else "FAIL",
        },
        "folders": rows,
    }
    with _profile_artifact_write(performance_profiler, subtype="report generation"):
        _write_json(report_dir / "discovery_selection.json", payload)
    return {"folders": folders, "selected": selected, **payload}


def _zip_localdb_members(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            return sorted(
                name for name in archive.namelist() if name.casefold().endswith("local.db")
            )
    except (OSError, zipfile.BadZipFile):
        return []


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _probe_database(path: Path, probe_copy: Path | None = None) -> dict[str, Any]:
    attempted: list[str] = []
    paths = [path]
    if probe_copy is not None:
        paths.append(probe_copy)
    last_error = ""
    for candidate in paths:
        try:
            connection = _open_read_only(candidate)
        except (OSError, sqlite3.Error) as exc:
            attempted.append(str(candidate))
            last_error = str(exc)
            continue
        try:
            tables = sorted(
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            )
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            required = {"AuditLogRecords", "Sessions", "Treatments"}
            missing = sorted(required.difference(tables))
            return {
                "usable": not missing and integrity.casefold() == "ok",
                "probe_path": str(candidate),
                "tables": tables,
                "missing_required_tables": missing,
                "integrity_check": integrity,
                "error": "" if not missing and integrity.casefold() == "ok" else "required_schema_or_integrity_failure",
                "attempted": attempted,
            }
        finally:
            connection.close()
    return {
        "usable": False,
        "probe_path": "",
        "tables": [],
        "missing_required_tables": [],
        "integrity_check": "",
        "error": last_error or "database_open_failed",
        "attempted": attempted,
    }


def _source_file_stat(path: Path) -> dict[str, Any]:
    """Capture immutable-source metadata used to detect accidental DB changes."""
    try:
        stat = path.stat()
    except OSError as exc:
        return {
            "source_size_bytes": None,
            "source_mtime_ns": None,
            "source_stat_error": str(exc),
        }
    return {
        "source_size_bytes": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_stat_error": "",
    }


def _candidate_descriptors(case_record: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in case_record.candidate_unzipped_db_paths:
        key = ("unzipped", str(path), "")
        if key not in seen:
            candidates.append({"kind": "unzipped", "path": path, "member": ""})
            seen.add(key)
    for path in case_record.candidate_zip_paths:
        members = _zip_localdb_members(path)
        for member in members:
            key = ("zip", str(path), member)
            if key not in seen:
                candidates.append({"kind": "zip", "path": path, "member": member})
                seen.add(key)
    return candidates


def _validate_candidates(
    site_root: Path,
    run_dir: Path,
    selected_ids: list[str],
    *,
    site_code: str,
    performance_profiler: PerformanceProfiler | None = None,
) -> dict[str, Any]:
    config = build_run_config(
        site_code=site_code,
        year_selection="All",
        root_dir=site_root.parent,
        site_path=site_root,
        output_dir=run_dir,
    )
    with _profile_stage(performance_profiler, "directory discovery"):
        records = {record.case_id: record for record in discover_cases(config)}
    case_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    probe_root = _backend_root(run_dir) / "staging" / "database_probes"
    for case_id in selected_ids:
        with _profile_stage(performance_profiler, "database candidate resolution", case_id=case_id):
            record = records.get(case_id)
            if record is None:
                failure = {
                    "case_id": case_id,
                    "failure_type": "missing_selected_manifest_case",
                    "reason": "case was not returned by canonical discovery",
                }
                failures.append(failure)
                case_rows.append(failure)
                continue
            descriptors = _candidate_descriptors(record)
            usable: list[dict[str, Any]] = []
            descriptor_rows: list[dict[str, Any]] = []
            for index, descriptor in enumerate(descriptors, start=1):
                probe_copy = probe_root / case_id / f"candidate_{index}.db"
                probe_copy.parent.mkdir(parents=True, exist_ok=True)
                source_path = Path(descriptor["path"])
                source_stat = _source_file_stat(source_path)
                try:
                    if descriptor["kind"] == "zip":
                        with _profile_stage(
                            performance_profiler,
                            "staging or copying",
                            case_id=case_id,
                        ):
                            with zipfile.ZipFile(source_path) as archive, archive.open(descriptor["member"]) as source:
                                with probe_copy.open("wb") as target:
                                    shutil.copyfileobj(source, target)
                        candidate_path = probe_copy
                    else:
                        candidate_path = source_path
                        if not candidate_path.is_file():
                            raise FileNotFoundError(str(candidate_path))
                        try:
                            _open_read_only(candidate_path).close()
                        except (OSError, sqlite3.Error):
                            with _profile_stage(
                                performance_profiler,
                                "staging or copying",
                                case_id=case_id,
                            ):
                                shutil.copyfile(candidate_path, probe_copy)
                    probe = _probe_database(candidate_path, probe_copy if candidate_path != probe_copy else None)
                except (OSError, sqlite3.Error, zipfile.BadZipFile, KeyError) as exc:
                    probe = {
                        "usable": False,
                        "probe_path": "",
                        "tables": [],
                        "missing_required_tables": [],
                        "integrity_check": "",
                        "error": str(exc),
                        "attempted": [],
                    }
                row = {
                    "case_id": case_id,
                    "candidate_kind": descriptor["kind"],
                    "candidate_path": str(source_path),
                    "zip_member": descriptor["member"],
                    **source_stat,
                    **probe,
                }
                descriptor_rows.append(row)
                if performance_profiler is not None and probe_copy.is_file():
                    with _profile_stage(
                        performance_profiler,
                        "final output discovery",
                        case_id=case_id,
                    ):
                        performance_profiler.record_output_paths(case_id, [probe_copy])
                if probe.get("usable"):
                    usable.append(row)

            status = "PASS" if len(usable) == 1 else "QUARANTINED"
            reason = "exactly_one_usable_database_candidate"
            if len(usable) == 0:
                reason = "unresolved_or_unusable_database_candidate"
            elif len(usable) > 1:
                reason = "multiple_usable_database_candidates"
            case_rows.append(
                {
                    "case_id": case_id,
                    "status": status,
                    "candidate_count": len(descriptors),
                    "usable_candidate_count": len(usable),
                    "reason": reason,
                    "candidates": descriptor_rows,
                }
            )
            if status != "PASS":
                failures.append(
                    {
                        "case_id": case_id,
                        "failure_type": "database_candidate_quarantine",
                        "reason": reason,
                        "candidate_count": len(descriptors),
                        "usable_candidate_count": len(usable),
                    }
                )

    flattened = []
    for row in case_rows:
        for candidate in row.get("candidates", []):
            flattened.append(candidate)
    with _profile_artifact_write(performance_profiler, subtype="CSV export"):
        _write_csv(
            _backend_layout(run_dir).reports_dir / "database_candidate_audit.csv",
            [
                "case_id",
                "candidate_kind",
                "candidate_path",
                "zip_member",
                "source_size_bytes",
                "source_mtime_ns",
                "source_stat_error",
                "usable",
                "probe_path",
                "integrity_check",
                "missing_required_tables",
                "error",
            ],
            flattened,
        )
    with _profile_artifact_write(performance_profiler, subtype="report generation"):
        _write_json(
            _backend_layout(run_dir).reports_dir / "database_candidate_audit.json",
            {"cases": case_rows, "failures": failures},
        )
    return {"records": records, "cases": case_rows, "failures": failures}


def _check_database_source_integrity(candidate_audit: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Verify candidate database files retained their pre-ingestion size and mtime."""
    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in candidate_audit["cases"]:
        for candidate in case.get("candidates", []):
            current = _source_file_stat(Path(candidate["candidate_path"]))
            unchanged = (
                not candidate.get("source_stat_error")
                and not current.get("source_stat_error")
                and candidate.get("source_size_bytes") == current.get("source_size_bytes")
                and candidate.get("source_mtime_ns") == current.get("source_mtime_ns")
            )
            check = {
                "case_id": candidate["case_id"],
                "candidate_kind": candidate["candidate_kind"],
                "candidate_path": candidate["candidate_path"],
                "zip_member": candidate.get("zip_member", ""),
                "before_size_bytes": candidate.get("source_size_bytes"),
                "before_mtime_ns": candidate.get("source_mtime_ns"),
                "after_size_bytes": current.get("source_size_bytes"),
                "after_mtime_ns": current.get("source_mtime_ns"),
                "status": "PASS" if unchanged else "FAIL",
                "reason": current.get("source_stat_error") or candidate.get("source_stat_error", ""),
            }
            checks.append(check)
            if not unchanged:
                failures.append(
                    {
                        "case_id": candidate["case_id"],
                        "failure_type": "database_source_modified",
                        "reason": check["reason"] or "size_or_mtime_changed_during_run",
                        "candidate_path": candidate["candidate_path"],
                    }
                )
    payload = {"status": "PASS" if not failures else "FAIL", "checks": checks, "failures": failures}
    _write_json(_backend_layout(run_dir).reports_dir / "database_source_integrity.json", payload)
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _valid_event_stream(path: Path, case_id: str) -> dict[str, Any]:
    rows = _read_csv(path)
    valid: list[dict[str, str]] = []
    excluded: Counter[str] = Counter()
    parse_failures: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        if row.get("case_id", "").strip() != case_id:
            excluded["case_id_mismatch"] += 1
            continue
        source = row.get("source", "").strip()
        if source not in VALID_EVENT_SOURCES:
            excluded["unrelated_source"] += 1
            continue
        if row.get("drop_reason", "").strip():
            excluded["drop_reason"] += 1
            continue
        if row.get("event_type", "").strip() == "SignalRecord":
            excluded["signal_record"] += 1
            continue
        try:
            _parse_datetime(row.get("timestamp", ""), context=f"{case_id}:event_row={row_number}")
        except ValueError as exc:
            parse_failures.append(str(exc))
            continue
        valid.append(row)

    valid.sort(key=_event_sort_key)
    if not valid:
        return {
            "status": "FAIL",
            "failure_type": "invalid_event_stream",
            "reason": "no valid case events",
            "valid_rows": [],
            "excluded_counts": dict(excluded),
            "parse_failures": parse_failures,
        }
    timestamps = [_parse_datetime(row["timestamp"], context=f"{case_id}:event") for row in valid]
    return {
        "status": "PASS" if not parse_failures else "FAIL",
        "failure_type": "invalid_event_stream" if parse_failures else "",
        "reason": "invalid event timestamps" if parse_failures else "",
        "valid_rows": valid,
        "excluded_counts": dict(excluded),
        "parse_failures": parse_failures,
        "start": timestamps[0],
        "end": timestamps[-1],
        "start_row": valid[0],
        "end_row": valid[-1],
    }


def _provenance(row: dict[str, str]) -> dict[str, str]:
    return {
        "source": row.get("source", ""),
        "source_detail": row.get("source_detail", ""),
        "event_type": row.get("event_type", ""),
        "row_number": row.get("row_number", ""),
        "insertion_rule": row.get("insertion_rule", ""),
    }


def _float_value(row: dict[str, str], field: str, case_id: str) -> float:
    text = row.get(field, "").strip()
    if not text:
        raise ValueError(f"{case_id}: interval row missing {field}")
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{case_id}: interval {field} is not finite")
    return value


def _interval_analysis(path: Path, case_id: str, event_stream: dict[str, Any]) -> dict[str, Any]:
    rows = _read_csv(path)
    if not rows:
        return {"status": "FAIL", "failure_type": "invalid_detailed_intervals", "reason": "empty interval artifact"}

    window_start = event_stream["start"]
    window_end = event_stream["end"]
    failures: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    totals: dict[str, float] = {state: 0.0 for state in REQUESTED_STATES}
    seen: set[tuple[Any, ...]] = set()

    for row_number, row in enumerate(rows, start=2):
        if row.get("case_id", "").strip() != case_id:
            failures.append({"row": row_number, "reason": "folder_case_id_vs_interval_case_id_mismatch"})
            continue
        try:
            timestamp = _parse_datetime(row.get("timestamp", ""), context=f"{case_id}:interval_row={row_number}")
            duration_sec = _float_value(row, "duration_sec", case_id)
            start_sec = _float_value(row, "start_sec", case_id)
        except ValueError as exc:
            failures.append({"row": row_number, "reason": str(exc)})
            continue
        state = row.get("state", "").strip()
        duplicate_key = (
            row.get("case_id", ""),
            row.get("timestamp", ""),
            state,
            row.get("duration_sec", ""),
            row.get("start_sec", ""),
            row.get("row_number", ""),
            row.get("source", ""),
            row.get("origin_event_type", ""),
        )
        if duplicate_key in seen:
            duplicates.append({"row": row_number, "reason": "identical_duplicate_interval_collapsed"})
            continue
        seen.add(duplicate_key)

        if duration_sec < -EPSILON_SEC:
            failures.append({"row": row_number, "reason": "negative_duration"})
            continue
        end_timestamp = timestamp + timedelta(seconds=max(duration_sec, 0.0))
        if end_timestamp < timestamp:
            failures.append({"row": row_number, "reason": "reversed_interval"})
        if timestamp < window_start - timedelta(seconds=EPSILON_SEC) or end_timestamp > window_end + timedelta(seconds=EPSILON_SEC):
            failures.append(
                {
                    "row": row_number,
                    "reason": "interval_outside_valid_case_event_window",
                    "interval_start": _format_datetime(timestamp),
                    "interval_end": _format_datetime(end_timestamp),
                }
            )
        if state and state not in REQUESTED_STATES and state not in {"NA", "<NA>"}:
            failures.append({"row": row_number, "reason": f"unexpected_operational_state:{state}"})
        if duration_sec > EPSILON_SEC and state not in {"", "NA", "<NA>"}:
            intervals.append(
                {
                    "start": timestamp,
                    "end": end_timestamp,
                    "state": state,
                    "row": row_number,
                }
            )
            totals[state] += duration_sec

    intervals.sort(key=lambda item: (item["start"], item["end"], item["row"]))
    active: list[dict[str, Any]] = []
    for interval in intervals:
        active = [item for item in active if item["end"] > interval["start"] + timedelta(seconds=EPSILON_SEC)]
        for prior in active:
            failures.append(
                {
                    "row": interval["row"],
                    "reason": "unexpected_positive_duration_overlap",
                    "prior_row": prior["row"],
                    "prior_state": prior["state"],
                    "state": interval["state"],
                }
            )
        active.append(interval)

    status = "PASS" if not failures else "FAIL"
    return {
        "status": status,
        "failure_type": "invalid_detailed_intervals" if failures else "",
        "reason": "; ".join(sorted({str(item["reason"]) for item in failures})),
        "failures": failures,
        "duplicate_intervals": duplicates,
        "state_duration_sec": totals,
        "state_duration_min_unrounded": {state: seconds / 60.0 for state, seconds in totals.items()},
        "interval_count": len(intervals),
    }


def _identity_validation(db_path: Path, case_id: str) -> dict[str, Any]:
    try:
        connection = _open_read_only(db_path)
    except (OSError, sqlite3.Error) as exc:
        return {"status": "FAIL", "failure_type": "database_identity_failure", "reason": str(exc)}
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {"AuditLogRecords", "Sessions", "Treatments"}
        missing = sorted(required.difference(tables))
        if missing:
            return {
                "status": "FAIL",
                "failure_type": "database_identity_failure",
                "reason": "missing_required_tables",
                "missing_tables": missing,
            }
        audit_orphans = int(
            connection.execute(
                "SELECT COUNT(*) FROM AuditLogRecords a "
                "LEFT JOIN Treatments t ON a.TreatmentId=t.Id "
                "WHERE a.TreatmentId IS NOT NULL AND t.Id IS NULL"
            ).fetchone()[0]
        )
        treatment_orphans = int(
            connection.execute(
                "SELECT COUNT(*) FROM Treatments t "
                "LEFT JOIN Sessions s ON t.SessionId=s.Id "
                "WHERE t.SessionId IS NOT NULL AND s.Id IS NULL"
            ).fetchone()[0]
        )
        folder_id_text_occurrences = 0
        for table in ("AuditLogRecords", "Sessions", "Treatments"):
            columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
            for column in columns:
                folder_id_text_occurrences += int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE typeof({column})='text' AND instr({column}, ?) > 0",
                        (case_id,),
                    ).fetchone()[0]
                )
        failures = []
        if audit_orphans:
            failures.append("auditlog_treatment_orphans")
        if treatment_orphans:
            failures.append("treatment_session_orphans")
        return {
            "status": "PASS" if not failures else "FAIL",
            "failure_type": "database_identity_failure" if failures else "",
            "reason": "; ".join(failures),
            "tables": sorted(tables),
            "auditlog_treatment_orphans": audit_orphans,
            "treatment_session_orphans": treatment_orphans,
            "folder_id_text_occurrences": folder_id_text_occurrences,
            "folder_id_direct_match_required": False,
        }
    finally:
        connection.close()


def _rollup_index(path: Path | None, *, site_code: str, case_ids: Iterable[str]) -> dict[str, Any]:
    required = {
        "site_id",
        "case_id",
        "pre_op_min",
        "device_insertion_min",
        "planning_min",
        "ablation_min",
        "post_op_min",
        "total_time_min",
    }
    if path is None:
        return {
            "rows": [],
            "relevant": [],
            "by_case": defaultdict(list),
            "failures": [],
            "missing_columns": [],
            "status": "NOT_PROVIDED",
        }
    if not path.is_file():
        return {
            "rows": [],
            "relevant": [],
            "by_case": defaultdict(list),
            "failures": [{"failure_type": "mapping_or_schema_failure", "reason": f"rollup_missing:{path}"}],
            "missing_columns": sorted(required),
            "status": "FAIL",
        }
    rows = _read_csv(path)
    missing_columns = sorted(required.difference(rows[0].keys() if rows else set()))
    relevant = [row for row in rows if row.get("site_id", "").strip() == site_code]
    by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in relevant:
        by_case[row.get("case_id", "").strip()].append(row)
    failures: list[dict[str, Any]] = []
    if missing_columns:
        failures.append({"failure_type": "mapping_or_schema_failure", "reason": f"rollup_missing_columns:{missing_columns}"})
    for case_id in case_ids:
        count = len(by_case.get(case_id, []))
        if count == 0:
            failures.append({"case_id": case_id, "failure_type": "missing_comparable_rollup_row"})
        elif count > 1:
            failures.append({"case_id": case_id, "failure_type": "duplicate_comparable_rollup_row", "count": count})
    return {
        "rows": rows,
        "relevant": relevant,
        "by_case": by_case,
        "failures": failures,
        "missing_columns": missing_columns,
        "status": "FAIL" if failures else "PASS",
    }


def _reconcile(case_id: str, detailed: dict[str, Any], rollup: dict[str, str]) -> list[dict[str, Any]]:
    detailed_min = detailed["state_duration_min_unrounded"]
    phase_rollup_columns = {
        "Pre-op": "pre_op_min",
        "Device insertion": "device_insertion_min",
        "Planning": "planning_min",
        "Ablation": "ablation_min",
        "Post-op": "post_op_min",
    }
    rows = []
    for phase in PHASE_ORDER:
        detailed_phase = sum(detailed_min[state] for state in PHASE_STATE_MAP[phase])
        rollup_value = float(rollup[phase_rollup_columns[phase]])
        difference = detailed_phase - rollup_value
        status = "PASS" if abs(difference) <= RECONCILIATION_TOLERANCE_MIN + EPSILON_SEC else "FAIL"
        rows.append(
            {
                "case_id": case_id,
                "phase": phase,
                "detailed_minutes_unrounded": f"{detailed_phase:.12f}",
                "rollup_minutes": f"{rollup_value:.1f}",
                "difference_minutes": f"{difference:.12f}",
                "status": status,
                "failure_type": "detailed_vs_rollup_timing_mismatch" if status == "FAIL" else "",
            }
        )
    return rows


def _state_headers() -> list[str]:
    return [
        "Experience",
        "Site",
        "PtId",
        "starttime",
        "endtime",
        *REQUESTED_STATES,
    ]


def _export_row(
    case_id: str,
    event_stream: dict[str, Any],
    interval_analysis: dict[str, Any],
    *,
    site_code: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Experience": "",
        "Site": site_code,
        "PtId": case_id,
        "starttime": _format_clock(event_stream["start"]),
        "endtime": _format_clock(event_stream["end"]),
    }
    for state in REQUESTED_STATES:
        value = max(0.0, float(interval_analysis["state_duration_min_unrounded"][state]))
        row[state] = f"{value:.1f}"
    return row


def _render_report(
    *,
    site_code: str,
    run_dir: Path,
    discovery: dict[str, Any],
    baseline: dict[str, Any],
    candidate_audit: dict[str, Any],
    source_integrity: dict[str, Any],
    mapping: dict[str, Any],
    rollup: dict[str, Any],
    cases: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
    status: str,
    final_csv: Path,
    staged_csv: Path,
    exported_row_count: int,
    publish_partial: bool,
) -> Path:
    report_path = _public_report_dir(run_dir) / f"{_site_slug(site_code)}_timeline_analysis_report.md"
    lines = [
        f"# {site_code} Timeline Analysis Report",
        "",
        f"- publication status: **{status}**",
        f"- final CSV: `{final_csv if final_csv.exists() else 'WITHHELD'}`",
        f"- staged CSV: `{staged_csv if staged_csv.exists() else 'not created'}`",
        f"- exported CSV rows: `{exported_row_count}`",
        f"- partial publication opt-in: `{publish_partial}`",
        "",
        "## Discovery and selection",
        "",
        f"- discovered folders: `{discovery['actual_discovered_folders']}`",
        f"- quarantined noncanonical folders: `{discovery['actual_quarantined_noncanonical_folders']}`",
        f"- selected folders: `{discovery['actual_selected_cases']}`",
        f"- category counts: `{json.dumps(discovery.get('category_counts', {}), sort_keys=True)}`",
        f"- semantic invariant status: `{discovery.get('semantic_invariant_status', 'NOT_RUN')}`",
        f"- semantic invariants: `{json.dumps(discovery.get('semantic_invariants', {}), sort_keys=True)}`",
        f"- canonical prefix: `{discovery.get('canonical_prefix') or 'none'}`",
        f"- case-list source: `{discovery.get('case_list_source', '')}`",
        f"- selected IDs: `{', '.join(discovery['selected_case_ids'])}`",
        f"- missing allowlist IDs: `{', '.join(discovery['missing_allowlist_case_ids']) or 'none'}`",
        f"- unexpected canonical IDs: `{', '.join(discovery['unexpected_canonical_case_ids']) or 'none'}`",
        f"- excluded unselected canonical IDs: `{', '.join(discovery.get('unselected_canonical_case_ids', [])) or 'none'}`",
        f"- noncanonical requested IDs: `{', '.join(discovery.get('noncanonical_requested_case_ids', [])) or 'none'}`",
        f"- invalid case-list entries: `{len(discovery.get('invalid_case_list_entries', []))}`",
        "",
        "## Pre-execution baseline",
        "",
        f"- mode: `{baseline.get('baseline_mode', 'live')}`",
        f"- branch: `{baseline['git_branch']['stdout'].strip()}`",
        f"- pytest: `{baseline['pytest']['returncode']}`",
        f"- pip check: `{baseline['pip_check']['returncode']}`",
        f"- git diff --check: `{baseline['git_diff_check']['returncode']}`",
        "",
        "## Source database integrity",
        "",
        f"- source database size/mtime checks: `{source_integrity['status']}` ({len(source_integrity['checks'])} candidate files checked)",
        f"- exactly one usable database per selected case: `{sum(row.get('status') == 'PASS' for row in candidate_audit['cases'])}/{len(discovery['selected_case_ids'])}`",
        "",
        "## Database candidate and case identity results",
        "",
        "| case | candidate status | assigned DB status | identity status | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    identity_by_case = {row["case_id"]: row for row in cases}
    candidate_by_case = {row["case_id"]: row for row in candidate_audit["cases"]}
    for case_id in discovery["selected_case_ids"]:
        candidate = candidate_by_case.get(case_id, {})
        case = identity_by_case.get(case_id, {})
        lines.append(
            f"| `{case_id}` | `{candidate.get('status', 'NOT_RUN')}` | `{case.get('assigned_database_status', 'NOT_RUN')}` | "
            f"`{case.get('identity_status', 'NOT_RUN')}` | "
            f"{case.get('failure_reason') or candidate.get('reason', '')} |"
        )

    lines.extend(
        [
            "",
            "## Timestamp provenance",
            "",
            "| case | starttime | start source | endtime | end source |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for case in cases:
        if case.get("event_status") == "PASS":
            lines.append(
                f"| `{case['case_id']}` | `{case['starttime']}` | `{case['start_provenance']}` | "
                f"`{case['endtime']}` | `{case['end_provenance']}` |"
            )

    lines.extend(
        [
            "",
            "## Mapping verification",
            "",
            f"- mapping status: `{mapping['status']}`",
            "- Each requested state was checked for exactly one phase membership and agreement with `_state_to_phase`; multiple states per phase are valid.",
            "",
            "## Reconciliation failures",
            "",
            f"- roll-up comparator status: `{rollup.get('status', 'NOT_PROVIDED')}`",
        ]
    )
    if rollup["failures"]:
        for failure in rollup["failures"]:
            lines.append(f"- `{failure['failure_type']}`: `{failure.get('case_id', '')}` {failure.get('reason', '')}")
    for case in cases:
        for failure in case.get("failures", []):
            lines.append(f"- `{failure.get('failure_type', '')}`: `{case['case_id']}` {failure.get('reason', '')}")
    for row in reconciliation:
        if row["status"] == "FAIL":
            lines.append(
                f"- `{row['failure_type']}`: `{row['case_id']}` `{row['phase']}` "
                f"difference `{row['difference_minutes']}` minutes"
            )
    if not rollup["failures"] and not any(case.get("failures") for case in cases) and not any(
        row["status"] == "FAIL" for row in reconciliation
    ):
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Reconciliation detail",
            "",
            "| case | phase | detailed unrounded min | roll-up min | difference min | status |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in reconciliation:
        lines.append(
            f"| `{row['case_id']}` | `{row['phase']}` | `{row['detailed_minutes_unrounded']}` | "
            f"`{row['rollup_minutes']}` | `{row['difference_minutes']}` | `{row['status']}` |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Detailed interval durations are authoritative for the exported state values.",
            "- The existing operational-state roll-up is used only as a validation comparator.",
            f"- A final CSV is valid only when all `{discovery['actual_selected_cases']}` selected cases pass every gate.",
            "- Final CSV starttime/endtime values are clock-only `h:mm:ss AM/PM`; full ISO datetimes and endpoint provenance remain in this report.",
        ]
    )
    if status == "PARTIAL_PUBLISHED":
        lines.append("- This CSV is intentionally partial: failed or quarantined cases are omitted and are listed above; it is not a complete selected-case deliverable.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def run_analysis(
    *,
    site_code: str,
    site_root: Path,
    run_dir: Path,
    rollup_path: Path | None,
    case_list_path: Path | None,
    canonical_prefix: str | None,
    publish_partial: bool,
    timing_log_dir: Path | None = None,
    allow_unselected_canonical: bool = False,
    select_all_canonical: bool = False,
    database_path: Path | None = None,
    cache_mode: str = "off",
    baseline_mode: str = "live",
    baseline_snapshot_path: Path | None = None,
    baseline_max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    profile: bool = False,
    performance_profiler: PerformanceProfiler | None = None,
) -> dict[str, Any]:
    if performance_profiler is None and profile:
        performance_profiler = PerformanceProfiler(site_code=site_code, output_dir=run_dir)
    run_orchestration_timer = _profile_stage(
        performance_profiler,
        "run orchestration outside named stages",
    )
    run_orchestration_timer.__enter__()
    with _profile_stage(performance_profiler, "preflight and manifest construction"):
        layout = _backend_layout(run_dir)
        public_report_dir = _public_report_dir(run_dir)
        if layout.run_manifest_path.exists():
            raise FileExistsError(f"Refusing to reuse completed run directory: {run_dir}")
        layout.run_dir.mkdir(parents=True, exist_ok=True)
        public_report_dir.mkdir(parents=True, exist_ok=True)
        if baseline_mode == "live":
            baseline = capture_baseline(
                repository_root=REPO_ROOT,
                basetemp=REPO_ROOT / f".pytest_tmp_{_site_slug(site_code)}_baseline",
            )
        elif baseline_mode == "reuse":
            if baseline_snapshot_path is None:
                raise ValueError("Reusable baseline mode requires an explicit snapshot path.")
            baseline = load_reusable_baseline(
                baseline_snapshot_path,
                repository_root=REPO_ROOT,
                max_age_hours=baseline_max_age_hours,
            )
        else:
            raise ValueError(f"Unsupported baseline mode: {baseline_mode}")
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            _write_json(layout.reports_dir / "pre_execution_baseline.json", baseline)

    discovery = _discover_and_select(
        site_root,
        run_dir,
        site_code=site_code,
        case_list_path=case_list_path,
        canonical_prefix=canonical_prefix,
        allow_unselected_canonical=allow_unselected_canonical,
        select_all_canonical=select_all_canonical,
        performance_profiler=performance_profiler,
    )
    selected_ids = discovery["selected_case_ids"]
    cache_reader: TimelineCacheReader | None = None
    if cache_mode == "read-only":
        if database_path is None:
            raise ValueError("Read-only cache mode requires an explicit database path.")
        _, configuration_fingerprint = analysis_configuration(
            year_selection="All",
            canonical_prefix=str(discovery["canonical_prefix"]),
        )
        cache_reader = TimelineCacheReader(
            database=database_path,
            site_code=site_code,
            configuration_fingerprint_sha256=configuration_fingerprint,
        )
    with _profile_stage(performance_profiler, "validation and reconciliation"):
        mapping = _state_mapping_validation()
    candidate_audit = _validate_candidates(
        site_root,
        run_dir,
        selected_ids,
        site_code=site_code,
        performance_profiler=performance_profiler,
    )
    candidate_failure_ids = {
        str(failure.get("case_id", "")).strip()
        for failure in candidate_audit["failures"]
        if str(failure.get("case_id", "")).strip()
    }
    processable_ids = [case_id for case_id in selected_ids if case_id not in candidate_failure_ids]

    global_failures: list[dict[str, Any]] = []
    if discovery["semantic_invariant_failures"]:
        global_failures.extend(discovery["semantic_invariant_failures"])
    if discovery["unexpected_canonical_case_ids"]:
        global_failures.append(
            {
                "failure_type": "unexpected_canonical_folder",
                "reason": ",".join(discovery["unexpected_canonical_case_ids"]),
            }
        )
    if mapping["status"] != "PASS":
        global_failures.extend(mapping["failures"])

    with _profile_stage(performance_profiler, "preflight and manifest construction"):
        selected_id_file = layout.manifests_dir / "selected_case_ids.txt"
        processable_id_file = layout.manifests_dir / "processable_case_ids.txt"
        selected_id_file.parent.mkdir(parents=True, exist_ok=True)
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            selected_id_file.write_text("\n".join(selected_ids) + "\n", encoding="utf-8")
            processable_id_file.write_text(
                "\n".join(processable_ids) + ("\n" if processable_ids else ""),
                encoding="utf-8",
            )
    pipeline_manifest: dict[str, Any] | None = None
    if not global_failures and processable_ids:
        diagnostics_path = layout.reports_dir / "diagnostics_summary.md"
        pipeline_manifest_obj = run_first_slice(
            [
                "--site",
                site_code,
                "--years",
                "All",
                "--root",
                str(site_root.parent),
                "--site-path",
                str(site_root),
                "--output",
                str(layout.run_dir),
                "--case-id-file",
                str(processable_id_file),
                "--diagnostics",
                "--diagnostics-file",
                str(diagnostics_path),
                *(
                    ["--timing-log-dir", str(timing_log_dir)]
                    if timing_log_dir is not None
                    else []
                ),
            ],
            performance_profiler=performance_profiler,
            cache_reader=cache_reader,
        )
        pipeline_manifest = {
            "cases_discovered": pipeline_manifest_obj.cases_discovered,
            "cases_processed": pipeline_manifest_obj.cases_processed,
            "cases_failed": pipeline_manifest_obj.cases_failed,
            "case_results": pipeline_manifest_obj.case_results,
            "warnings": pipeline_manifest_obj.warnings,
        }
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            _write_json(layout.reports_dir / "pipeline_manifest_summary.json", pipeline_manifest)
    else:
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            _write_json(
                layout.reports_dir / "pipeline_manifest_summary.json",
                {"status": "NOT_RUN", "failures": global_failures},
            )

    if candidate_audit["failures"]:
        global_failures.extend(candidate_audit["failures"])
        if performance_profiler is not None:
            for failure in candidate_audit["failures"]:
                case_id = str(failure.get("case_id", "")).strip()
                if case_id:
                    performance_profiler.add_case_failure(case_id, str(failure.get("reason", "")))
    with _profile_stage(performance_profiler, "validation and reconciliation"):
        source_integrity = _check_database_source_integrity(candidate_audit, run_dir)
    if source_integrity["failures"]:
        global_failures.extend(source_integrity["failures"])

    cache_summary: dict[str, Any] | None = None
    if cache_reader is not None:
        cache_summary = cache_reader.summary()
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            _write_json(layout.reports_dir / "cache_summary.json", cache_summary)
        with _profile_artifact_write(performance_profiler, subtype="CSV export"):
            _write_csv(
                layout.reports_dir / "cache_by_case.csv",
                [
                    "case_id",
                    "status",
                    "reason",
                    "duration_seconds",
                    "input_fingerprint_sha256",
                    "source_sha256",
                    "timing_log_sha256",
                    "case_analysis_id",
                ],
                list(cache_summary["cases"]),
            )

    with _profile_stage(performance_profiler, "validation and reconciliation"):
        rollup = _rollup_index(rollup_path, site_code=site_code, case_ids=selected_ids)
    if rollup["failures"]:
        global_failures.extend(rollup["failures"])

    cases: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    staged_rows: list[dict[str, Any]] = []
    if pipeline_manifest is not None:
        manifest_rows = _read_csv(layout.case_manifest_path) if layout.case_manifest_path.exists() else []
        manifest_ids = [row.get("case_id", "").strip() for row in manifest_rows]
        if len(manifest_ids) != len(set(manifest_ids)):
            duplicate_manifest_ids = sorted(
                case_id for case_id, count in Counter(manifest_ids).items() if case_id and count > 1
            )
            global_failures.append(
                {
                    "failure_type": "duplicate_processed_case",
                    "reason": f"case manifest duplicates: {','.join(duplicate_manifest_ids)}",
                }
            )
        if sorted(manifest_ids) != sorted(processable_ids):
            global_failures.append({"failure_type": "selected_manifest_not_exact_allowlist", "reason": str(manifest_ids)})
        processed_case_ids = [
            str(row.get("case_id", "")).strip()
            for row in pipeline_manifest["case_results"]
            if row.get("status") == "processed" and str(row.get("case_id", "")).strip()
        ]
        duplicate_processed_ids = sorted(
            case_id for case_id, count in Counter(processed_case_ids).items() if count > 1
        )
        if duplicate_processed_ids:
            global_failures.append(
                {
                    "failure_type": "duplicate_processed_case",
                    "reason": f"pipeline results duplicate: {','.join(duplicate_processed_ids)}",
                }
            )
        result_by_case = {str(row.get("case_id")): row for row in pipeline_manifest["case_results"]}
        candidate_by_case = {row["case_id"]: row for row in candidate_audit["cases"]}
        for case_id in selected_ids:
            if case_id in candidate_failure_ids:
                candidate_failure = next(
                    failure for failure in candidate_audit["failures"] if failure.get("case_id") == case_id
                )
                cases.append(
                    {
                        "case_id": case_id,
                        "pipeline_status": "quarantined_preingestion",
                        "generated_case_id": "",
                        "assigned_database_status": "QUARANTINED",
                        "identity_status": "NOT_RUN",
                        "failures": [candidate_failure],
                        "failure_reason": candidate_failure.get("reason", ""),
                    }
                )
                continue
            result = result_by_case.get(case_id, {})
            case = {"case_id": case_id, "pipeline_status": result.get("status", "missing")}
            interval_path = layout.state_intervals_dir / f"{case_id}_state_intervals.csv"
            event_path = layout.state_labeled_events_dir / f"{case_id}_state_labeled_events.csv"
            case_failures: list[dict[str, Any]] = []
            generated_case_id = str(result.get("case_id", "")).strip()
            case["generated_case_id"] = generated_case_id
            if generated_case_id != case_id:
                case_failures.append({"failure_type": "folder_id_vs_generated_case_id_failure", "reason": f"generated_case_id={generated_case_id or 'missing'}"})
            if result.get("status") != "processed":
                case_failures.append({"failure_type": "pipeline_case_failure", "reason": result.get("error") or result.get("status", "missing")})
            if not interval_path.exists():
                case_failures.append({"failure_type": "folder_id_vs_interval_artifact_failure", "reason": "missing interval artifact"})
            if not event_path.exists():
                case_failures.append({"failure_type": "invalid_event_stream", "reason": "missing state-labeled event artifact"})
            if not case_failures:
                with _profile_stage(
                    performance_profiler,
                    "validation and reconciliation",
                    case_id=case_id,
                ):
                    event_stream = _valid_event_stream(event_path, case_id)
                case["event_status"] = event_stream["status"]
                if event_stream["status"] != "PASS":
                    case_failures.append({"failure_type": event_stream["failure_type"], "reason": event_stream["reason"]})
                else:
                    case["starttime"] = _format_datetime(event_stream["start"])
                    case["endtime"] = _format_datetime(event_stream["end"])
                    case["start_provenance"] = json.dumps(_provenance(event_stream["start_row"]), sort_keys=True)
                    case["end_provenance"] = json.dumps(_provenance(event_stream["end_row"]), sort_keys=True)
                    with _profile_stage(
                        performance_profiler,
                        "detailed aggregation",
                        case_id=case_id,
                    ):
                        interval_analysis = _interval_analysis(interval_path, case_id, event_stream)
                    case["interval_status"] = interval_analysis["status"]
                    if interval_analysis["status"] != "PASS":
                        case_failures.append({"failure_type": interval_analysis["failure_type"], "reason": interval_analysis["reason"]})
                    else:
                        staged_rows.append(_export_row(case_id, event_stream, interval_analysis, site_code=site_code))
                        if len(rollup["by_case"].get(case_id, [])) == 1:
                            with _profile_stage(
                                performance_profiler,
                                "validation and reconciliation",
                                case_id=case_id,
                            ):
                                reconciliation.extend(_reconcile(case_id, interval_analysis, rollup["by_case"][case_id][0]))
            assigned_source = str(result.get("source_path") or "").strip()
            identity_path = Path(assigned_source) if assigned_source else Path("__missing_assigned_database__")
            if not identity_path.exists():
                staged_path = layout.db_extract_dir / case_id / "local.db"
                identity_path = staged_path if staged_path.exists() else identity_path
            if identity_path.exists():
                usable_candidates = [candidate for candidate in candidate_by_case.get(case_id, {}).get("candidates", []) if candidate.get("usable")]
                assigned_database_match = len(usable_candidates) == 1 and identity_path.resolve() == Path(usable_candidates[0]["candidate_path"]).resolve()
                case["assigned_database_status"] = "PASS" if assigned_database_match else "FAIL"
                if not assigned_database_match:
                    case_failures.append({"failure_type": "folder_id_vs_assigned_database_failure", "reason": "pipeline-assigned database does not match the unique usable pre-ingestion candidate"})
                with _profile_stage(
                    performance_profiler,
                    "validation and reconciliation",
                    case_id=case_id,
                ):
                    identity = _identity_validation(identity_path, case_id)
                case["identity_status"] = identity["status"]
                case["identity_reason"] = identity.get("reason", "")
                if identity["status"] != "PASS":
                    case_failures.append({"failure_type": identity["failure_type"], "reason": identity.get("reason", "")})
            else:
                case["assigned_database_status"] = "FAIL"
                case["identity_status"] = "FAIL"
                case_failures.append({"failure_type": "database_identity_failure", "reason": "assigned database path unavailable"})
            case["failures"] = case_failures
            case["failure_reason"] = "; ".join(item["reason"] for item in case_failures)
            cases.append(case)
            if performance_profiler is not None:
                for failure in case_failures:
                    performance_profiler.add_case_failure(case_id, str(failure.get("reason", "")))

    for case_id in discovery["missing_allowlist_case_ids"]:
        global_failures.append({"failure_type": "missing_selected_case_folder", "case_id": case_id, "reason": "requested case folder was not discovered"})
    required_success_count = len(selected_ids)
    staged_csv = layout.run_dir / "staging" / f"{_site_slug(site_code)}_timeline_analysis_STAGED_NOT_FOR_USE.csv"
    if staged_rows:
        with _profile_artifact_write(performance_profiler, subtype="CSV export"):
            _write_csv(staged_csv, _state_headers(), staged_rows)

    case_failures = [failure for case in cases for failure in case.get("failures", [])]
    if case_failures:
        for failure in case_failures:
            if failure not in global_failures:
                global_failures.append(failure)
    if discovery["unexpected_canonical_case_ids"]:
        status = "GLOBAL_ABORT"
    elif pipeline_manifest is None:
        status = "WITHHELD_PREINGESTION"
    elif global_failures:
        status = "WITHHELD"
        partial_case_failure_types = {
            "database_candidate_quarantine",
            "pipeline_case_failure",
            "folder_id_vs_generated_case_id_failure",
            "folder_id_vs_interval_artifact_failure",
            "invalid_event_stream",
            "invalid_detailed_intervals",
            "database_identity_failure",
            "folder_id_vs_assigned_database_failure",
        }
        partial_eligible = (
            publish_partial
            and staged_rows
            and all(
                failure.get("case_id") in selected_ids
                and failure.get("failure_type") in partial_case_failure_types
                for failure in global_failures
            )
        )
        if partial_eligible:
            status = "PARTIAL_PUBLISHED"
    elif len(staged_rows) != required_success_count:
        status = "WITHHELD"
        global_failures.append({"failure_type": "publication_case_count_gate", "reason": f"valid_rows={len(staged_rows)} expected={required_success_count}"})
    elif any(row["status"] == "FAIL" for row in reconciliation):
        status = "WITHHELD"
        global_failures.append({"failure_type": "detailed_vs_rollup_timing_mismatch", "reason": "one or more phase differences exceeded tolerance"})
    else:
        status = "PUBLISHED"

    final_csv = public_report_dir / f"{_site_slug(site_code)}_timeline_analysis.csv"
    top_level_timeline_plots: dict[str, Path] = {}
    if status in {"PUBLISHED", "PARTIAL_PUBLISHED"}:
        top_level_timeline_plots = publish_top_level_timeline_plots(run_dir)
        with _profile_artifact_write(performance_profiler, subtype="CSV export"):
            _write_csv(final_csv, _state_headers(), staged_rows)

    with _profile_stage(performance_profiler, "report assembly and serialization"):
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            report_path = _render_report(
                site_code=site_code,
                run_dir=run_dir,
                discovery=discovery,
                baseline=baseline,
                candidate_audit=candidate_audit,
                source_integrity=source_integrity,
                mapping=mapping,
                rollup=rollup,
                cases=cases,
                reconciliation=reconciliation,
                status=status,
                final_csv=final_csv,
                staged_csv=staged_csv,
                exported_row_count=len(staged_rows),
                publish_partial=publish_partial,
            )
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            _write_json(
                layout.reports_dir / "execution_result.json",
                {
                    "status": status,
                    "global_failures": global_failures,
                    "source_integrity": source_integrity,
                    "cases": cases,
                    "reconciliation": reconciliation,
                    "exported_row_count": len(staged_rows),
                    "publish_partial": publish_partial,
                    "final_csv": str(final_csv) if final_csv.exists() else None,
                    "staged_csv": str(staged_csv) if staged_csv.exists() else None,
                    "report": str(report_path),
                    "top_level_timeline_plots": {
                        key: str(path) for key, path in top_level_timeline_plots.items()
                    },
                    "cache": cache_summary,
                },
            )
    with _profile_artifact_write(performance_profiler, subtype="CSV export"):
        _write_csv(
            layout.reports_dir / "phase_reconciliation.csv",
            ["case_id", "phase", "detailed_minutes_unrounded", "rollup_minutes", "difference_minutes", "status", "failure_type"],
            reconciliation,
        )
    performance_paths: dict[str, str] = {}
    if performance_profiler is not None:
        with _profile_stage(performance_profiler, "final output discovery"):
            performance_profiler.record_global_output_paths(
                [path for path in run_dir.rglob("*") if path.is_file()]
            )
        run_orchestration_timer.__exit__(None, None, None)
        performance_summary_path, performance_case_csv_path = performance_profiler.write_reports(layout.reports_dir)
        performance_paths = {
            "performance_summary": str(performance_summary_path),
            "performance_by_case": str(performance_case_csv_path),
        }
    else:
        run_orchestration_timer.__exit__(None, None, None)
    return {
        "status": status,
        "discovery": discovery,
        "cases": cases,
        "global_failures": global_failures,
        "exported_row_count": len(staged_rows),
        "final_csv": final_csv if final_csv.exists() else None,
        "staged_csv": staged_csv if staged_csv.exists() else None,
        "report": report_path,
        "top_level_timeline_plots": top_level_timeline_plots,
        "performance": performance_paths,
        "cache": cache_summary,
    }


def main(
    argv: list[str] | None = None,
    *,
    process_wall_started: float | None = None,
    process_cpu_started: float | None = None,
) -> int:
    args = parse_args(argv)
    site_code = args.site_code
    site_root = Path(args.site_root).expanduser().resolve() if args.site_root else _default_site_root(site_code).resolve()
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else _default_run_dir(site_code).resolve()
    rollup_path = Path(args.rollup).expanduser().resolve() if args.rollup else _default_rollup(site_code)
    case_list_path = Path(args.case_list).expanduser().resolve() if args.case_list else None
    timing_log_dir = (
        Path(args.timing_log_dir).expanduser().resolve() if args.timing_log_dir else None
    )
    database_path = (
        Path(args.database).expanduser().resolve() if args.database else None
    )
    baseline_snapshot_path = (
        Path(args.baseline_snapshot).expanduser().resolve()
        if args.baseline_snapshot
        else None
    )
    performance_profiler: PerformanceProfiler | None = None
    if args.profile:
        wall_started = _PROCESS_WALL_STARTED if process_wall_started is None else process_wall_started
        cpu_started = _PROCESS_CPU_STARTED if process_cpu_started is None else process_cpu_started
        performance_profiler = PerformanceProfiler(
            site_code=site_code,
            output_dir=run_dir,
            wall_started=wall_started,
            cpu_started=cpu_started,
        )
        performance_profiler.record_external_stage(
            "process startup and CLI parsing",
            wall_seconds=max(0.0, time.perf_counter() - wall_started),
            process_cpu_seconds=max(0.0, time.process_time() - cpu_started),
        )
    try:
        result = run_analysis(
            site_code=site_code,
            site_root=site_root,
            run_dir=run_dir,
            rollup_path=rollup_path,
            case_list_path=case_list_path,
            canonical_prefix=args.canonical_prefix,
            allow_unselected_canonical=args.allow_unselected_canonical,
            select_all_canonical=args.select_all_canonical,
            publish_partial=args.publish_partial,
            timing_log_dir=timing_log_dir,
            database_path=database_path,
            cache_mode=args.cache_mode,
            baseline_mode=args.baseline_mode,
            baseline_snapshot_path=baseline_snapshot_path,
            baseline_max_age_hours=args.baseline_max_age_hours,
            profile=args.profile,
            performance_profiler=performance_profiler,
        )
    except Exception as exc:  # pragma: no cover - operator-facing safety net
        print(f"{site_code} analysis aborted: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    performance_text = ""
    if args.profile:
        performance_text = (
            f" performance_summary={result['performance'].get('performance_summary', '')}"
            f" performance_by_case={result['performance'].get('performance_by_case', '')}"
        )
    print(
        f"status={result['status']} "
        f"discovered={result['discovery']['actual_discovered_folders']} "
        f"quarantined_noncanonical={result['discovery']['actual_quarantined_noncanonical_folders']} "
        f"selected={result['discovery']['actual_selected_cases']} "
        f"final_csv={result['final_csv'] or 'WITHHELD'} "
        f"report={result['report']}"
        f"{performance_text}"
    )
    return 0 if result["status"] in {"PUBLISHED", "PARTIAL_PUBLISHED"} else 1


if __name__ == "__main__":
    raise SystemExit(
        main(
            process_wall_started=_PROCESS_WALL_STARTED,
            process_cpu_started=_PROCESS_CPU_STARTED,
        )
    )
