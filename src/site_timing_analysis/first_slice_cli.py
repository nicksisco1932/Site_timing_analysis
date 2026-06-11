from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import build_run_config_from_args, resolve_year_list
from .db_source import resolve_database_source
from .discovery import discover_cases
from .errors import SiteTimingError
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


def run_first_slice(argv: list[str] | None = None) -> RunManifest:
    started_at = datetime.now(timezone.utc)
    config = build_run_config_from_args(argv)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    layout = output_layout(config.output_dir)
    allowed_years = set(resolve_year_list(config.year_selection))
    site_root = config.site_path if config.site_path is not None else config.root_dir / config.site_code

    case_records = discover_cases(config)
    case_manifest_path = write_case_manifest(case_records, config.output_dir)

    case_results: list[dict[str, object]] = []
    warnings: list[str] = []
    processed = 0
    failed = 0
    intervals_for_plot = []
    processed_case_result_indexes: list[int] = []

    for case_record in case_records:
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
                continue

            source = resolve_database_source(
                case_record,
                allow_ambiguous=config.allow_ambiguous_db,
                db_candidate_index=config.db_candidate_index,
                zip_member_index=config.zip_member_index,
            )

            ingestion_result = ingest_case_database(source, extraction_root=layout.db_extract_dir)
            raw_events = ingestion_result["raw_events"]
            sessions_rows = ingestion_result["sessions_rows"]
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
                continue

            normalized_events, dropped_events = normalize_audit_events(raw_events)
            normalized_export_path = write_normalized_events_csv(
                case_id=case_record.case_id,
                normalized_events=normalized_events,
                output_dir=config.output_dir,
            )

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
            enriched_export_path = write_enriched_events_csv(
                case_id=case_record.case_id,
                enriched_events=enriched_events,
                output_dir=config.output_dir,
            )

            state_labeled_events, state_warnings = assign_states(enriched_events)
            state_labeled_export_path = write_state_labeled_events_csv(
                case_id=case_record.case_id,
                state_labeled_events=state_labeled_events,
                output_dir=config.output_dir,
            )
            state_intervals, timing_warnings = compute_state_intervals(state_labeled_events)
            state_interval_export_path = write_state_intervals_csv(
                case_id=case_record.case_id,
                state_intervals=state_intervals,
                output_dir=config.output_dir,
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
        except SiteTimingError as exc:
            failed += 1
            case_results.append(
                {
                    "case_id": case_record.case_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    plot_paths: dict[str, object] = {}
    if processed_case_result_indexes:
        generated_plot_paths, plot_warnings = generate_timeline_plots(intervals_for_plot, config.output_dir)
        plot_paths = {key: str(path) for key, path in generated_plot_paths.items()}
        warnings.extend(plot_warnings)

        for idx in processed_case_result_indexes:
            case_id = str(case_results[idx]["case_id"])
            case_plot_warnings = [warning for warning in plot_warnings if warning.startswith(f"{case_id}:")]
            case_results[idx]["plot_warning_count"] = len(case_plot_warnings)
            case_results[idx]["plot_warnings"] = case_plot_warnings
            case_results[idx]["normalized_timeline_plot"] = plot_paths.get("normalized_timeline")
            case_results[idx]["original_hour_timeline_plot"] = plot_paths.get("original_hour_timeline")
    else:
        warnings.append("plot:skipped_no_processed_cases")

    tff_artifact_paths: dict[str, str] = {}
    if config.tff_adapter_enabled:
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
    write_run_manifest(run_manifest, config.output_dir)

    if config.diagnostics:
        diagnostics_path = write_diagnostics_summary(
            run_manifest=run_manifest,
            state_intervals=intervals_for_plot,
            output_dir=config.output_dir,
            diagnostics_file=config.diagnostics_file,
        )
        run_manifest.artifact_paths["diagnostics_summary"] = str(diagnostics_path)
        write_run_manifest(run_manifest, config.output_dir)

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
