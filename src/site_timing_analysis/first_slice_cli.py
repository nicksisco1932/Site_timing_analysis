# Project: Site Timing Analysis
# File: src/site_timing_analysis/first_slice_cli.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Orchestrates the staged timing pipeline from discovery through plots and diagnostics.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import build_run_config_from_args, resolve_year_list
from .db_source import resolve_database_source
from .discovery import discover_cases
from .errors import ConfigValidationError, SiteTimingError
from .enrichment import (
    derive_session_synthetic_events,
    derive_timing_log_synthetic_events,
    merge_enriched_events,
)
from .ingestion import ingest_case_database
from .manifest import (
    write_case_manifest,
    write_enriched_events_csv,
    write_normalized_events_csv,
    write_state_intervals_csv,
    write_state_labeled_events_csv,
    write_run_manifest,
)
from .models import RunManifest, StateInterval
from .normalization import normalize_audit_events
from .output_layout import first_existing_path, output_layout
from .plotting import generate_timeline_plots
from .profiling import PerformanceProfiler
from .state_machine import assign_states
from .timing import compute_state_intervals
from .timing_log import find_timing_log, parse_timing_log_csv
from .tff_adapter import apply_read_only_tff_adapter


def _case_matches_year(raw_timestamp: str | None, allowed_years: set[int]) -> bool:
    if raw_timestamp is None or len(raw_timestamp) < 4:
        return False
    year_prefix = raw_timestamp[:4]
    if not year_prefix.isdigit():
        return False
    return int(year_prefix) in allowed_years


def _read_case_id_file(path: Path | None) -> set[str] | None:
    """Read an optional newline-delimited case selection file."""
    if path is None:
        return None
    if not path.is_file():
        raise ConfigValidationError(f"case_id_file does not exist: {path}")
    case_ids: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        token = raw_line.strip().strip('"')
        if not token or token.startswith("#"):
            continue
        case_ids.add(Path(token).name if ("\\" in token or "/" in token) else token)
    if not case_ids:
        raise ConfigValidationError(f"case_id_file is empty: {path}")
    return case_ids


_DIAGNOSTIC_FLAGS = (
    "interval_truncated_large_gap",
    "interval_terminal_state_clamped",
    "interval_early_state_truncated",
    "interval_session_synthetic_truncated",
    "interval_unassigned_state_truncated",
    "negative_rebased_start",
)


def _warning_category(warning: str) -> str:
    parts = warning.split(":", 2)
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return "uncategorized"


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
    """Measure an artifact write once in the write parent and its subtype."""
    with _profile_stage(profiler, "all artifact writes", case_id=case_id):
        with _profile_stage(profiler, subtype, case_id=case_id):
            yield


def build_run_diagnostics(
    *,
    run_manifest: RunManifest,
    state_intervals: list[StateInterval],
    output_dir: Path,
) -> dict[str, object]:
    durations = [float(interval.duration_sec) for interval in state_intervals]
    max_duration_sec = max(durations) if durations else 0.0

    threshold_counts = {
        ">7200": sum(1 for value in durations if value > 7200.0),
        ">14400": sum(1 for value in durations if value > 14400.0),
        ">28800": sum(1 for value in durations if value > 28800.0),
    }

    quality_flag_counts: dict[str, int] = {flag: 0 for flag in _DIAGNOSTIC_FLAGS}
    for interval in state_intervals:
        for flag in interval.quality_flags:
            if flag in quality_flag_counts:
                quality_flag_counts[flag] += 1

    warning_categories = Counter(_warning_category(warning) for warning in run_manifest.warnings)
    top_warning_categories = warning_categories.most_common(8)
    layout = output_layout(output_dir)

    run_manifest_path = first_existing_path(layout.run_manifest_path, output_dir / "run_manifest.json")
    case_manifest_path = first_existing_path(layout.case_manifest_path, output_dir / "case_manifest.csv")
    interval_diag_path = first_existing_path(
        layout.interval_outlier_diagnostics_path,
        output_dir / "interval_outlier_diagnostics.md",
    )
    normalized_plot_path = (
        Path(run_manifest.artifact_paths["normalized_timeline"])
        if "normalized_timeline" in run_manifest.artifact_paths
        else first_existing_path(
            layout.timeline_plots_dir / "normalized_timeline.png",
            output_dir / "plots" / "normalized_timeline.png",
        )
    )
    original_plot_path = (
        Path(run_manifest.artifact_paths["original_hour_timeline"])
        if "original_hour_timeline" in run_manifest.artifact_paths
        else first_existing_path(
            layout.timeline_plots_dir / "original_hour_timeline.png",
            output_dir / "plots" / "original_hour_timeline.png",
        )
    )

    artifact_summary = {
        "run_manifest": {"path": str(run_manifest_path), "exists": run_manifest_path.exists()},
        "case_manifest": {"path": str(case_manifest_path), "exists": case_manifest_path.exists()},
        "normalized_timeline_plot": {
            "path": str(normalized_plot_path),
            "exists": normalized_plot_path.exists(),
        },
        "original_hour_timeline_plot": {
            "path": str(original_plot_path),
            "exists": original_plot_path.exists(),
        },
        "interval_outlier_diagnostics": {
            "path": str(interval_diag_path),
            "exists": interval_diag_path.exists(),
        },
    }

    return {
        "run_summary": {
            "site": run_manifest.site_code,
            "years": run_manifest.year_selection,
            "output_dir": str(run_manifest.output_dir),
            "cases_discovered": run_manifest.cases_discovered,
            "cases_processed": run_manifest.cases_processed,
            "cases_failed": run_manifest.cases_failed,
        },
        "interval_sanity": {
            "max_duration_sec": max_duration_sec,
            "duration_count_gt_7200": threshold_counts[">7200"],
            "duration_count_gt_14400": threshold_counts[">14400"],
            "duration_count_gt_28800": threshold_counts[">28800"],
        },
        "quality_flag_counts": quality_flag_counts,
        "warning_summary": {
            "total_warnings": len(run_manifest.warnings),
            "top_categories": top_warning_categories,
        },
        "artifact_summary": artifact_summary,
    }


def _render_diagnostics_markdown(summary: dict[str, object]) -> str:
    run = summary["run_summary"]
    interval = summary["interval_sanity"]
    flags = summary["quality_flag_counts"]
    warning = summary["warning_summary"]
    artifacts = summary["artifact_summary"]

    lines = [
        "# Diagnostics Summary",
        "",
        "## Run Summary",
        f"- site: `{run['site']}`",
        f"- years: `{run['years']}`",
        f"- output directory: `{run['output_dir']}`",
        f"- cases discovered: `{run['cases_discovered']}`",
        f"- cases processed: `{run['cases_processed']}`",
        f"- cases failed: `{run['cases_failed']}`",
        "",
        "## Interval Sanity",
        f"- max duration_sec: `{interval['max_duration_sec']}`",
        f"- count duration_sec > 7200: `{interval['duration_count_gt_7200']}`",
        f"- count duration_sec > 14400: `{interval['duration_count_gt_14400']}`",
        f"- count duration_sec > 28800: `{interval['duration_count_gt_28800']}`",
        "",
        "## Quality-Flag Counts",
    ]

    for flag in _DIAGNOSTIC_FLAGS:
        lines.append(f"- {flag}: `{flags[flag]}`")

    lines.extend(
        [
            "",
            "## Warning Summary",
            f"- total warnings: `{warning['total_warnings']}`",
            "- top warning categories:",
        ]
    )

    top_categories = warning["top_categories"]
    if top_categories:
        for category, count in top_categories:
            lines.append(f"- {category}: `{count}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Artifact Summary"])
    for name, details in artifacts.items():
        exists_label = "yes" if details["exists"] else "no"
        lines.append(f"- {name}: `{details['path']}` (exists: `{exists_label}`)")

    return "\n".join(lines) + "\n"


def write_diagnostics_summary(
    *,
    run_manifest: RunManifest,
    state_intervals: list[StateInterval],
    output_dir: Path,
    diagnostics_file: Path | None,
) -> Path:
    summary = build_run_diagnostics(
        run_manifest=run_manifest,
        state_intervals=state_intervals,
        output_dir=output_dir,
    )
    out_path = diagnostics_file if diagnostics_file is not None else output_layout(output_dir).diagnostics_summary_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_diagnostics_markdown(summary), encoding="utf-8")
    return out_path


def run_first_slice(
    argv: list[str] | None = None,
    *,
    performance_profiler: PerformanceProfiler | None = None,
) -> RunManifest:
    with _profile_stage(performance_profiler, "global setup and teardown"):
        started_at = datetime.now(timezone.utc)
        config = build_run_config_from_args(argv)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        layout = output_layout(config.output_dir)
        allowed_years = set(resolve_year_list(config.year_selection))
        site_root = config.site_path if config.site_path is not None else config.root_dir / config.site_code

    extra_case_prefixes = (
        ("STA_",)
        if config.tff_adapter_enabled
        and config.tff_filter_known_exclusions
        and config.site_code.casefold().startswith("stanford_")
        else ()
    )
    with _profile_stage(performance_profiler, "directory discovery"):
        case_records = discover_cases(config, extra_case_prefixes=extra_case_prefixes)
    with _profile_stage(performance_profiler, "case selection"):
        selected_case_ids = _read_case_id_file(config.case_id_file)
        if selected_case_ids is not None:
            case_records = [record for record in case_records if record.case_id in selected_case_ids]
    with _profile_artifact_write(performance_profiler, subtype="CSV export"):
        case_manifest_path = write_case_manifest(case_records, config.output_dir)

    case_results: list[dict[str, object]] = []
    warnings: list[str] = []
    processed = 0
    failed = 0
    intervals_for_plot = []
    processed_case_result_indexes: list[int] = []

    for case_record in case_records:
        case_profile_timer = _profile_stage(
            performance_profiler,
            "per-case orchestration outside named stages",
            case_id=case_record.case_id,
        )
        case_profile_timer.__enter__()
        try:
            if (
                len(case_record.candidate_unzipped_db_paths) == 0
                and len(case_record.candidate_zip_paths) == 0
            ):
                case_results.append(
                    {
                        "case_id": case_record.case_id,
                        "status": "skipped_no_database_candidates",
                        "warnings": list(case_record.warnings),
                    }
                )
                warnings.extend(case_record.warnings)
                if performance_profiler is not None:
                    performance_profiler.add_case_warnings(case_record.case_id, list(case_record.warnings))
                case_profile_timer.__exit__(None, None, None)
                continue

            with _profile_stage(
                performance_profiler,
                "database candidate resolution",
                case_id=case_record.case_id,
            ):
                source = resolve_database_source(
                    case_record,
                    allow_ambiguous=config.allow_ambiguous_db,
                    db_candidate_index=config.db_candidate_index,
                    zip_member_index=config.zip_member_index,
                )

            with _profile_stage(
                performance_profiler,
                "database connection and ingestion",
                case_id=case_record.case_id,
            ):
                ingestion_result = ingest_case_database(
                    source,
                    extraction_root=layout.db_extract_dir,
                    performance_profiler=performance_profiler,
                )
            raw_events = ingestion_result["raw_events"]
            sessions_rows = ingestion_result["sessions_rows"]
            if performance_profiler is not None:
                performance_profiler.set_case_metrics(
                    case_record.case_id,
                    database_rows_read=len(raw_events) + len(sessions_rows),
                )
                ingested_db_path = Path(ingestion_result["db_path"]).resolve()
                try:
                    ingested_db_path.relative_to(config.output_dir.resolve())
                except ValueError:
                    pass
                else:
                    with _profile_stage(
                        performance_profiler,
                        "final output discovery",
                        case_id=case_record.case_id,
                    ):
                        performance_profiler.record_output_paths(
                            case_record.case_id,
                            [ingested_db_path],
                        )
            if raw_events:
                first_timestamp = raw_events[0].raw_timestamp
            else:
                first_timestamp = None

            if not _case_matches_year(first_timestamp, allowed_years):
                case_results.append(
                    {
                        "case_id": case_record.case_id,
                        "status": "skipped_year_filter",
                        "first_timestamp": first_timestamp,
                    }
                )
                case_profile_timer.__exit__(None, None, None)
                continue

            with _profile_stage(
                performance_profiler,
                "event normalization",
                case_id=case_record.case_id,
            ):
                normalized_events, dropped_events = normalize_audit_events(raw_events)
            with _profile_artifact_write(
                performance_profiler,
                subtype="CSV export",
                case_id=case_record.case_id,
            ):
                normalized_export_path = write_normalized_events_csv(
                    case_id=case_record.case_id,
                    normalized_events=normalized_events,
                    output_dir=config.output_dir,
                )
            if performance_profiler is not None:
                performance_profiler.set_case_metrics(
                    case_record.case_id,
                    normalized_events=len(normalized_events),
                )

            with _profile_stage(
                performance_profiler,
                "event enrichment",
                case_id=case_record.case_id,
            ):
                session_synthetic_events, session_warnings = derive_session_synthetic_events(
                    case_record.case_id,
                    sessions_rows,
                )

                timing_entries = []
                timing_parse_warnings: list[str] = []
                timing_log_synthetic_events = []
                timing_mapping_warnings: list[str] = []
                timing_log_path = find_timing_log(
                    case_record.case_id,
                    resolved_site_root=site_root,
                    timing_log_dir_override=config.timing_log_dir,
                )
                if timing_log_path is not None:
                    timing_entries, timing_parse_warnings = parse_timing_log_csv(
                        timing_log_path,
                        case_record.case_id,
                    )
                    timing_log_synthetic_events, timing_mapping_warnings = derive_timing_log_synthetic_events(
                        timing_entries
                    )

                synthetic_events = [*session_synthetic_events, *timing_log_synthetic_events]
                enriched_events = merge_enriched_events(normalized_events, synthetic_events)
            with _profile_artifact_write(
                performance_profiler,
                subtype="CSV export",
                case_id=case_record.case_id,
            ):
                enriched_export_path = write_enriched_events_csv(
                    case_id=case_record.case_id,
                    enriched_events=enriched_events,
                    output_dir=config.output_dir,
                )

            with _profile_stage(
                performance_profiler,
                "state labeling",
                case_id=case_record.case_id,
            ):
                state_labeled_events, state_warnings = assign_states(enriched_events)
            with _profile_artifact_write(
                performance_profiler,
                subtype="CSV export",
                case_id=case_record.case_id,
            ):
                state_labeled_export_path = write_state_labeled_events_csv(
                    case_id=case_record.case_id,
                    state_labeled_events=state_labeled_events,
                    output_dir=config.output_dir,
                )
            with _profile_stage(
                performance_profiler,
                "interval construction",
                case_id=case_record.case_id,
            ):
                state_intervals, timing_warnings = compute_state_intervals(state_labeled_events)
            with _profile_artifact_write(
                performance_profiler,
                subtype="CSV export",
                case_id=case_record.case_id,
            ):
                state_interval_export_path = write_state_intervals_csv(
                    case_id=case_record.case_id,
                    state_intervals=state_intervals,
                    output_dir=config.output_dir,
                )
            if performance_profiler is not None:
                performance_profiler.set_case_metrics(
                    case_record.case_id,
                    labeled_events=len(state_labeled_events),
                    intervals=len(state_intervals),
                )

            case_warnings = [
                *source.warnings,
                *session_warnings,
                *timing_parse_warnings,
                *timing_mapping_warnings,
                *state_warnings,
                *timing_warnings,
            ]

            processed += 1
            case_results.append(
                {
                    "case_id": case_record.case_id,
                    "status": "processed",
                    "source_type": source.source_type,
                    "source_path": str(source.source_path),
                    "raw_event_count": len(raw_events),
                    "normalized_event_count": len(normalized_events),
                    "dropped_event_count": len(dropped_events),
                    "normalized_export": str(normalized_export_path),
                    "timing_log_path": str(timing_log_path) if timing_log_path is not None else None,
                    "timing_log_entry_count": len(timing_entries),
                    "session_synthetic_count": len(session_synthetic_events),
                    "timing_log_synthetic_count": len(timing_log_synthetic_events),
                    "enriched_event_count": len(enriched_events),
                    "enriched_export": str(enriched_export_path),
                    "state_labeled_event_count": len(state_labeled_events),
                    "state_labeled_export": str(state_labeled_export_path),
                    "state_assignment_warning_count": len(state_warnings),
                    "state_warnings": state_warnings,
                    "state_interval_count": len(state_intervals),
                    "state_interval_export": str(state_interval_export_path),
                    "timing_warning_count": len(timing_warnings),
                    "timing_warnings": timing_warnings,
                    "plot_warning_count": 0,
                    "plot_warnings": [],
                    "enrichment_warnings": case_warnings,
                }
            )
            intervals_for_plot.extend(state_intervals)
            processed_case_result_indexes.append(len(case_results) - 1)
            warnings.extend(case_warnings)
            if performance_profiler is not None:
                performance_profiler.add_case_warnings(case_record.case_id, case_warnings)
                performance_profiler.record_output_paths(
                    case_record.case_id,
                    [
                        normalized_export_path,
                        enriched_export_path,
                        state_labeled_export_path,
                        state_interval_export_path,
                    ],
                )
            case_profile_timer.__exit__(None, None, None)
        except SiteTimingError as exc:
            failed += 1
            if performance_profiler is not None:
                performance_profiler.add_case_failure(case_record.case_id, str(exc))
            case_profile_timer.__exit__(type(exc), exc, exc.__traceback__)
            case_results.append(
                {
                    "case_id": case_record.case_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    plot_paths: dict[str, object] = {}
    if processed_case_result_indexes:
        with _profile_stage(performance_profiler, "global plot orchestration"):
            with _profile_stage(performance_profiler, "all artifact writes"):
                with _profile_stage(performance_profiler, "plot generation"):
                    generated_plot_paths, plot_warnings = generate_timeline_plots(
                        intervals_for_plot,
                        config.output_dir,
                    )
            plot_paths = {key: str(path) for key, path in generated_plot_paths.items()}
            warnings.extend(plot_warnings)

            for idx in processed_case_result_indexes:
                case_id = str(case_results[idx]["case_id"])
                case_plot_warnings = [warning for warning in plot_warnings if warning.startswith(f"{case_id}:")]
                case_results[idx]["plot_warning_count"] = len(case_plot_warnings)
                case_results[idx]["plot_warnings"] = case_plot_warnings
                case_results[idx]["normalized_timeline_plot"] = plot_paths.get("normalized_timeline")
                case_results[idx]["original_hour_timeline_plot"] = plot_paths.get("original_hour_timeline")
                if performance_profiler is not None:
                    performance_profiler.add_case_warnings(case_id, case_plot_warnings)
            if performance_profiler is not None:
                performance_profiler.record_global_output_paths(list(plot_paths.values()))
    else:
        warnings.append("plot:skipped_no_processed_cases")

    tff_artifact_paths: dict[str, str] = {}
    if config.tff_adapter_enabled:
        with _profile_stage(performance_profiler, "all artifact writes"):
            case_results, tff_artifact_paths, tff_warnings = apply_read_only_tff_adapter(
                case_results=case_results,
                output_dir=config.output_dir,
                tff_case_table=config.tff_normalized_case_table,
                filter_known_exclusions=config.tff_filter_known_exclusions,
            )
        warnings.extend(tff_warnings)

    run_manifest_path = layout.run_manifest_path
    artifact_paths = {
        "case_manifest": str(case_manifest_path),
        "run_manifest": str(run_manifest_path),
        "manifests_dir": str(layout.manifests_dir),
        "normalized_events_dir": str(layout.normalized_events_dir),
        "enriched_events_dir": str(layout.enriched_events_dir),
        "state_labeled_events_dir": str(layout.state_labeled_events_dir),
        "state_intervals_dir": str(layout.state_intervals_dir),
        "tables_dir": str(layout.tables_dir),
        "reports_dir": str(layout.reports_dir),
        "scratch_dir": str(layout.scratch_dir),
    }
    for key, value in plot_paths.items():
        artifact_paths[key] = str(value)
    artifact_paths.update(tff_artifact_paths)

    run_manifest = RunManifest(
        run_id=str(uuid4()),
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        site_code=config.site_code,
        year_selection=config.year_selection,
        root_dir=config.root_dir,
        output_dir=config.output_dir,
        cases_discovered=len(case_records),
        cases_processed=processed,
        cases_failed=failed,
        warnings=warnings,
        case_results=case_results,
        artifact_paths=artifact_paths,
    )
    with _profile_artifact_write(performance_profiler, subtype="report generation"):
        write_run_manifest(run_manifest, config.output_dir)

    if config.diagnostics:
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            diagnostics_path = write_diagnostics_summary(
                run_manifest=run_manifest,
                state_intervals=intervals_for_plot,
                output_dir=config.output_dir,
                diagnostics_file=config.diagnostics_file,
            )
        run_manifest.artifact_paths["diagnostics_summary"] = str(diagnostics_path)
        with _profile_artifact_write(performance_profiler, subtype="report generation"):
            write_run_manifest(run_manifest, config.output_dir)

    if performance_profiler is not None:
        with _profile_stage(performance_profiler, "final output discovery"):
            performance_profiler.record_global_output_paths(
                [
                    case_manifest_path,
                    run_manifest_path,
                    *plot_paths.values(),
                    *tff_artifact_paths.values(),
                    run_manifest.artifact_paths.get("diagnostics_summary"),
                ]
            )

    return run_manifest


def main() -> None:
    manifest = run_first_slice()
    print(
        f"run_id={manifest.run_id} "
        f"cases_discovered={manifest.cases_discovered} "
        f"cases_processed={manifest.cases_processed} "
        f"cases_failed={manifest.cases_failed}"
    )


if __name__ == "__main__":
    main()
