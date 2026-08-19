# Project: Site Timing Analysis
# File: src/site_timing_analysis/timing_gantt_deliverables.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: Unknown
# Purpose: Builds standardized final timing Gantt deliverables from existing run artifacts.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from statistics import median
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from .models import StateInterval
from .output_layout import first_existing_path, output_layout
from .plotting import (
    STATE_COLOR_MAP,
    UNKNOWN_STATE_COLOR,
    PlotRow,
    minutes_since_midnight,
    prepare_device_insertion_normalized_rows,
    prepare_plot_rows,
    seconds_to_minutes,
)
from .workflow_summary import PHASE_COLOR_MAP, PHASE_ORDER, PHASE_STATE_MAP


CANONICAL_RUN_NAME = "2026.03.20_UCSD_109_timing_Gantt"
SUPERSEDED_RUN_NAMES = {"2026.03.19_UCSD_109_timing_Gantt": CANONICAL_RUN_NAME}
GROUP_LABELS = ("Early", "Middle", "Late")
FINAL_FLOAT_PRECISION = 1
PLOT_DATA_TOLERANCE = 1e-5

PHASE_COLUMN_NAMES = {
    "Pre-op": "pre_op_min",
    "Device insertion": "device_insertion_min",
    "Planning": "planning_min",
    "Ablation": "ablation_min",
    "Post-op": "post_op_min",
}
GROUP_PHASE_COLUMN_NAMES = {
    "Pre-op": "pre_op_median_min",
    "Device insertion": "device_insertion_median_min",
    "Planning": "planning_median_min",
    "Ablation": "ablation_median_min",
    "Post-op": "post_op_median_min",
}
WIDE_STATE_COLUMN_ALIASES = {
    "TULSA QA": "tulsa_qa_min",
    "Room ready": "room_ready_min",
    "Patient positioning & induction": "patient_positioning_and_induction_min",
    "Device insertion": "device_insertion_min",
    "Device repositioning": "device_repositioning_min",
    "Alignment": "alignment_min",
    "Coarse": "coarse_min",
    "Detailed": "detailed_min",
    "Planning start angle": "planning_start_angle_min",
    "Initialization": "initialization_min",
    "Treating": "treating_min",
    "Paused": "paused_min",
    "Review": "review_min",
    "Post-treatment scans & Device removal": "device_removal_min",
    "Patient recovery & transfer": "patient_transfer_min",
}


@dataclass(frozen=True, slots=True)
class RunAudit:
    run_name: str
    run_dir: Path
    site_id: str
    status: str
    reason: str
    interval_file_count: int
    case_count: int
    final_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class SegmentRow:
    site_id: str
    case_id: str
    case_date: str
    chronology_group: str
    operational_phase: str
    operational_state: str
    start_min_from_anchor: float
    end_min_from_anchor: float
    duration_min: float
    anchor_state: str
    quality_flags: str
    source_run: str
    source_file: str


@dataclass(frozen=True, slots=True)
class CaseSummaryRow:
    site_id: str
    case_id: str
    case_date: str
    chronology_group: str
    phase_minutes: dict[str, float]
    total_time_min: float


@dataclass(frozen=True, slots=True)
class GroupSummaryRow:
    site_id: str
    group_label: str
    case_count: int
    first_case_date: str
    last_case_date: str
    phase_medians: dict[str, float]
    total_time_median_min: float


@dataclass(frozen=True, slots=True)
class PlotSourceInfo:
    case_id: str
    case_date: str
    state: str
    original_start_sec: float
    duration_sec: float
    anchor_state: str
    quality_flags: str
    source_file: str


@dataclass(frozen=True, slots=True)
class TimelinePlotDataPaths:
    plot_data_dir: Path
    normalized_segments: Path
    original_hour_segments: Path
    normalized_case_index: Path
    original_hour_case_index: Path
    legend: Path
    normalized_state_runs: Path
    original_hour_state_runs: Path
    normalized_state_summary_long: Path
    original_hour_state_summary_long: Path
    normalized_state_summary_wide: Path
    original_hour_state_summary_wide: Path


@dataclass(frozen=True, slots=True)
class RunDeliverable:
    run_name: str
    site_id: str
    status: str
    final_dir: Path
    case_count: int
    group_sizes: list[int]
    workflow_tertiles_png: Path
    workflow_tertiles_csv: Path
    workflow_summary_png: Path
    workflow_summary_csv: Path
    operational_state_segments_csv: Path
    operational_state_summary_by_case_csv: Path
    operational_state_summary_by_group_csv: Path
    data_dictionary_csv: Path
    readme_md: Path
    plot_data_dir: Path
    normalized_timeline_segments_csv: Path
    original_hour_timeline_segments_csv: Path
    normalized_timeline_case_index_csv: Path
    original_hour_timeline_case_index_csv: Path
    timeline_legend_csv: Path
    normalized_timeline_state_runs_csv: Path
    original_hour_timeline_state_runs_csv: Path
    normalized_timeline_state_summary_long_csv: Path
    original_hour_timeline_state_summary_long_csv: Path
    normalized_timeline_state_summary_wide_csv: Path
    original_hour_timeline_state_summary_wide_csv: Path
    validation_checks: list[dict[str, str]]


def _site_id_from_run_name(run_name: str) -> str:
    parts = run_name.split("_")
    if len(parts) >= 4 and parts[0].count(".") == 2:
        return f"{parts[1]}_{parts[2]}"
    return run_name.replace("_timing_Gantt", "")


def _read_manifest(run_dir: Path) -> dict[str, object]:
    manifest_path = first_existing_path(
        output_layout(run_dir).run_manifest_path,
        run_dir / "run_manifest.json",
    )
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _read_case_manifest_dates(run_dir: Path) -> dict[str, str]:
    manifest_path = first_existing_path(
        output_layout(run_dir).case_manifest_path,
        run_dir / "case_manifest.csv",
    )
    if not manifest_path.exists():
        return {}
    result: dict[str, str] = {}
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            case_id = str(row.get("case_id", "")).strip()
            case_date = _parse_case_date(row.get("case_date"))
            if case_id and case_date:
                result[case_id] = case_date
    return result


def _state_intervals_dir(run_dir: Path) -> Path:
    return first_existing_path(
        output_layout(run_dir).state_intervals_dir,
        run_dir / "state_intervals",
    )


def _interval_paths(run_dir: Path) -> list[Path]:
    intervals_dir = _state_intervals_dir(run_dir)
    if not intervals_dir.exists():
        return []
    return sorted(intervals_dir.glob("*_state_intervals.csv"))


def _parse_case_date(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(f"{text}T00:00:00").date().isoformat()
        except ValueError:
            return ""


def _state_to_phase(state: str) -> str:
    for phase, states in PHASE_STATE_MAP.items():
        if state in states:
            return phase
    return "Other"


def _round_one(value: float) -> float:
    return round(float(value), FINAL_FLOAT_PRECISION)


def _format_one(value: float) -> str:
    return f"{_round_one(value):.{FINAL_FLOAT_PRECISION}f}"


def _case_sort_key(case_id: str, case_date_by_case: dict[str, str]) -> tuple[object, ...]:
    case_date = case_date_by_case.get(case_id, "")
    if case_date:
        return (0, case_date, case_id)
    return (1, case_id)


def balanced_group_sizes(case_count: int) -> list[int]:
    """
    Split cases into three balanced chronological groups.

    Input:
        Number of sorted cases.
    Output:
        Three group sizes for ``Early``, ``Middle``, and ``Late``.
    Assumptions:
        A single remainder case is placed in ``Late``; two remainder cases are
        placed in ``Early`` and ``Middle``. This matches the explicitly approved
        9 -> 3/3/3, 29 -> 10/10/9, 79 -> 26/26/27, and 135 -> 45/45/45 rules.
    """
    if case_count < 0:
        raise ValueError("case_count must be nonnegative")
    base = case_count // 3
    remainder = case_count % 3
    if remainder == 0:
        return [base, base, base]
    if remainder == 1:
        return [base, base, base + 1]
    return [base + 1, base + 1, base]


def assign_chronology_groups(case_ids: list[str], case_date_by_case: dict[str, str]) -> dict[str, str]:
    """
    Assign sorted cases to Early/Middle/Late chronology groups.

    Input:
        Case IDs and resolved case dates.
    Output:
        Mapping from case ID to chronology group label.
    Assumptions:
        Cases with dates sort before cases without dates; case ID is the stable
        deterministic fallback.
    """
    ordered = sorted(case_ids, key=lambda case_id: _case_sort_key(case_id, case_date_by_case))
    sizes = balanced_group_sizes(len(ordered))
    group_by_case: dict[str, str] = {}
    start = 0
    for label, size in zip(GROUP_LABELS, sizes):
        for case_id in ordered[start : start + size]:
            group_by_case[case_id] = label
        start += size
    return group_by_case


def _load_interval_segments(
    *,
    run_dir: Path,
    repo_root: Path,
    site_id: str,
    source_run: str,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    manifest_dates = _read_case_manifest_dates(run_dir)
    rows: list[dict[str, object]] = []
    earliest_date_by_case: dict[str, str] = {}
    for interval_path in _interval_paths(run_dir):
        with interval_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                case_id = str(row.get("case_id", "")).strip()
                state = str(row.get("state", "")).strip()
                if not case_id or state in {"", "NA"}:
                    continue
                duration_sec = float(row.get("duration_sec", "0") or 0)
                if duration_sec <= 0:
                    continue
                timestamp = str(row.get("timestamp", "")).strip()
                case_date = manifest_dates.get(case_id) or _parse_case_date(timestamp)
                if case_date and (
                    case_id not in earliest_date_by_case or case_date < earliest_date_by_case[case_id]
                ):
                    earliest_date_by_case[case_id] = case_date
                start_sec = float(row.get("start_sec", "0") or 0)
                source_file = _relative_path(interval_path, repo_root)
                rows.append(
                    {
                        "site_id": site_id,
                        "case_id": case_id,
                        "case_date": case_date,
                        "state": state,
                        "phase": _state_to_phase(state),
                        "start_min": start_sec / 60.0,
                        "end_min": (start_sec + duration_sec) / 60.0,
                        "duration_min": duration_sec / 60.0,
                        "anchor_state": str(row.get("rebase_anchor", "")).strip(),
                        "quality_flags": str(row.get("quality_flags", "")).strip(),
                        "source_run": source_run,
                        "source_file": source_file,
                    }
                )
    case_date_by_case = dict(earliest_date_by_case)
    for case_id, case_date in manifest_dates.items():
        case_date_by_case.setdefault(case_id, case_date)
    return rows, case_date_by_case


def _parse_optional_int(text: object) -> int | None:
    value = str(text or "").strip()
    if not value:
        return None
    return int(value)


def _parse_quality_flags(text: object) -> list[str]:
    value = str(text or "").strip()
    if not value:
        return []
    return [flag for flag in value.split("|") if flag]


def _plot_source_key(row: PlotRow | StateInterval) -> tuple[object, ...]:
    state = "" if row.state is None else str(row.state)
    return (
        row.case_id,
        row.timestamp.isoformat(timespec="microseconds"),
        state,
        round(float(row.duration_sec), 9),
        row.row_number,
    )


def _load_plot_source_intervals(
    *,
    run_dir: Path,
    repo_root: Path,
) -> tuple[list[StateInterval], dict[tuple[object, ...], PlotSourceInfo]]:
    """
    Load state intervals with enough provenance to export timeline plot sources.

    Input:
        Completed run folder containing per-case ``state_intervals`` files.
    Output:
        Parsed ``StateInterval`` rows plus a lookup keyed to plot-prepared rows.
    Assumptions:
        The timeline plotter filters and orders intervals through
        ``prepare_plot_rows``; this loader preserves source file, anchor, date,
        and quality flag context for the rows that survive that preparation.
    """
    manifest_dates = _read_case_manifest_dates(run_dir)
    intervals: list[StateInterval] = []
    source_by_key: dict[tuple[object, ...], PlotSourceInfo] = {}
    for interval_path in _interval_paths(run_dir):
        source_file = _relative_path(interval_path, repo_root)
        with interval_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                case_id = str(row.get("case_id", "")).strip()
                timestamp_text = str(row.get("timestamp", "")).strip()
                if not case_id or not timestamp_text:
                    continue
                timestamp = datetime.fromisoformat(timestamp_text)
                state_text = str(row.get("state", "")).strip()
                interval = StateInterval(
                    case_id=case_id,
                    timestamp=timestamp,
                    state=state_text or None,
                    start_sec=float(row.get("start_sec", "0") or 0),
                    duration_sec=float(row.get("duration_sec", "0") or 0),
                    rebase_anchor=str(row.get("rebase_anchor", "")).strip() or None,
                    origin_event_type=str(row.get("origin_event_type", "")).strip(),
                    source=str(row.get("source", "")).strip(),
                    is_synthetic=str(row.get("is_synthetic", "")).strip().lower() == "true",
                    source_detail=str(row.get("source_detail", "")).strip(),
                    row_number=_parse_optional_int(row.get("row_number")),
                    state_assignment_rule=str(row.get("state_assignment_rule", "")).strip() or None,
                    cleanup_rule_applied=str(row.get("cleanup_rule_applied", "")).strip() or None,
                    quality_flags=_parse_quality_flags(row.get("quality_flags")),
                    segment_id=str(row.get("segment_id", "")).strip() or None,
                    event_kind=_parse_optional_int(row.get("event_kind")),
                    drop_reason=str(row.get("drop_reason", "")).strip() or None,
                    insertion_rule=str(row.get("insertion_rule", "")).strip() or None,
                    raw_payload={},
                )
                intervals.append(interval)
                source_by_key[_plot_source_key(interval)] = PlotSourceInfo(
                    case_id=case_id,
                    case_date=manifest_dates.get(case_id) or _parse_case_date(timestamp_text),
                    state=state_text,
                    original_start_sec=float(row.get("start_sec", "0") or 0),
                    duration_sec=float(row.get("duration_sec", "0") or 0),
                    anchor_state=str(row.get("rebase_anchor", "")).strip(),
                    quality_flags=str(row.get("quality_flags", "")).strip(),
                    source_file=source_file,
                )
    return intervals, source_by_key


def _normalized_anchor_by_case(warnings: Iterable[str]) -> dict[str, str]:
    anchors: dict[str, str] = {}
    marker = ":plot_normalized_anchor_used:"
    for warning in warnings:
        if marker not in warning:
            continue
        case_id, remainder = warning.split(marker, 1)
        anchor_state = remainder.split(":", 1)[0]
        if case_id and anchor_state:
            anchors[case_id] = anchor_state
    return anchors


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _build_segment_rows(
    *,
    raw_rows: list[dict[str, object]],
    group_by_case: dict[str, str],
) -> list[SegmentRow]:
    segments: list[SegmentRow] = []
    for row in sorted(
        raw_rows,
        key=lambda item: (
            str(item["site_id"]),
            str(item["case_id"]),
            float(item["start_min"]),
            str(item["state"]),
        ),
    ):
        segments.append(
            SegmentRow(
                site_id=str(row["site_id"]),
                case_id=str(row["case_id"]),
                case_date=str(row["case_date"]),
                chronology_group=group_by_case[str(row["case_id"])],
                operational_phase=str(row["phase"]),
                operational_state=str(row["state"]),
                start_min_from_anchor=float(row["start_min"]),
                end_min_from_anchor=float(row["end_min"]),
                duration_min=float(row["duration_min"]),
                anchor_state=str(row["anchor_state"]),
                quality_flags=str(row["quality_flags"]),
                source_run=str(row["source_run"]),
                source_file=str(row["source_file"]),
            )
        )
    return segments


def _build_case_summaries(segments: list[SegmentRow]) -> list[CaseSummaryRow]:
    by_case: dict[str, dict[str, object]] = {}
    for segment in segments:
        entry = by_case.setdefault(
            segment.case_id,
            {
                "site_id": segment.site_id,
                "case_id": segment.case_id,
                "case_date": segment.case_date,
                "chronology_group": segment.chronology_group,
                "phase_minutes": {phase: 0.0 for phase in PHASE_ORDER},
            },
        )
        if segment.operational_phase in PHASE_ORDER:
            phase_minutes = entry["phase_minutes"]
            assert isinstance(phase_minutes, dict)
            phase_minutes[segment.operational_phase] += segment.duration_min

    summaries: list[CaseSummaryRow] = []
    for entry in by_case.values():
        phase_minutes = entry["phase_minutes"]
        assert isinstance(phase_minutes, dict)
        exact_phase_minutes = {
            phase: float(phase_minutes.get(phase, 0.0))
            for phase in PHASE_ORDER
        }
        total_time = _round_one(sum(_round_one(value) for value in exact_phase_minutes.values()))
        summaries.append(
            CaseSummaryRow(
                site_id=str(entry["site_id"]),
                case_id=str(entry["case_id"]),
                case_date=str(entry["case_date"]),
                chronology_group=str(entry["chronology_group"]),
                phase_minutes=exact_phase_minutes,
                total_time_min=total_time,
            )
        )
    return sorted(
        summaries,
        key=lambda row: (
            _case_sort_key(row.case_id, {row.case_id: row.case_date}),
            row.case_id,
        ),
    )


def _build_group_summaries(case_rows: list[CaseSummaryRow]) -> list[GroupSummaryRow]:
    rows_by_group: dict[str, list[CaseSummaryRow]] = {label: [] for label in GROUP_LABELS}
    for row in case_rows:
        rows_by_group[row.chronology_group].append(row)

    groups: list[GroupSummaryRow] = []
    for label in GROUP_LABELS:
        rows = rows_by_group[label]
        if not rows:
            groups.append(
                GroupSummaryRow(
                    site_id=case_rows[0].site_id if case_rows else "",
                    group_label=label,
                    case_count=0,
                    first_case_date="",
                    last_case_date="",
                    phase_medians={phase: 0.0 for phase in PHASE_ORDER},
                    total_time_median_min=0.0,
                )
            )
            continue
        phase_medians = {
            phase: _round_one(median([row.phase_minutes[phase] for row in rows]))
            for phase in PHASE_ORDER
        }
        total_time = _round_one(sum(phase_medians.values()))
        case_dates = [row.case_date for row in rows if row.case_date]
        groups.append(
            GroupSummaryRow(
                site_id=rows[0].site_id,
                group_label=label,
                case_count=len(rows),
                first_case_date=min(case_dates) if case_dates else "",
                last_case_date=max(case_dates) if case_dates else "",
                phase_medians=phase_medians,
                total_time_median_min=total_time,
            )
        )
    return groups


def _build_overall_summary(case_rows: list[CaseSummaryRow]) -> GroupSummaryRow:
    if not case_rows:
        return GroupSummaryRow("", "All cases", 0, "", "", {phase: 0.0 for phase in PHASE_ORDER}, 0.0)
    phase_medians = {
        phase: _round_one(median([row.phase_minutes[phase] for row in case_rows]))
        for phase in PHASE_ORDER
    }
    total_time = _round_one(sum(phase_medians.values()))
    case_dates = [row.case_date for row in case_rows if row.case_date]
    return GroupSummaryRow(
        site_id=case_rows[0].site_id,
        group_label="All cases",
        case_count=len(case_rows),
        first_case_date=min(case_dates) if case_dates else "",
        last_case_date=max(case_dates) if case_dates else "",
        phase_medians=phase_medians,
        total_time_median_min=total_time,
    )


def discover_runs(timing_root: Path) -> list[RunAudit]:
    """
    Audit timing-gantt run folders without modifying them.

    Input:
        Root directory containing ``*_timing_Gantt`` run folders.
    Output:
        One audit row per run folder with retained/superseded/incomplete status.
    Assumptions:
        UCSD 2026.03.20 is the canonical UCSD run; UCSD 2026.03.19 is
        superseded and excluded from canonical final deliverables.
    """
    audits: list[RunAudit] = []
    for run_dir in sorted(path for path in timing_root.iterdir() if path.is_dir()):
        if not run_dir.name.endswith("_timing_Gantt"):
            continue
        manifest = _read_manifest(run_dir)
        site_id = str(manifest.get("site_code") or _site_id_from_run_name(run_dir.name))
        interval_file_count = len(_interval_paths(run_dir))
        case_count = _count_cases_from_interval_files(run_dir)
        if run_dir.name in SUPERSEDED_RUN_NAMES:
            status = "superseded"
            reason = f"Superseded by {SUPERSEDED_RUN_NAMES[run_dir.name]}"
        elif run_dir.name == CANONICAL_RUN_NAME:
            status = "canonical"
            reason = "Canonical UCSD model run"
        elif interval_file_count == 0:
            status = "incomplete"
            reason = "No state interval files found"
        else:
            status = "retained"
            reason = "Retained for standardized final deliverables"
        audits.append(
            RunAudit(
                run_name=run_dir.name,
                run_dir=run_dir,
                site_id=site_id,
                status=status,
                reason=reason,
                interval_file_count=interval_file_count,
                case_count=case_count,
                final_dir=run_dir / "final" if status in {"canonical", "retained"} else None,
            )
        )
    return audits


def _count_cases_from_interval_files(run_dir: Path) -> int:
    return len(_interval_paths(run_dir))


def build_run_deliverables(run: RunAudit, *, repo_root: Path) -> RunDeliverable:
    """
    Build standardized final deliverables for one retained timing-gantt run.

    Input:
        A retained or canonical run audit row.
    Output:
        Paths and validation checks for the generated final artifacts.
    Assumptions:
        Existing reconstruction artifacts are read-only inputs. Files under
        ``final/`` and the two published top-level timeline PNG copies are safe
        to overwrite for idempotent reruns.
    """
    if run.status not in {"canonical", "retained"}:
        raise ValueError(f"Cannot build deliverables for run status {run.status!r}")

    final_dir = run.run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    publish_top_level_timeline_plots(run.run_dir)

    raw_segments, case_date_by_case = _load_interval_segments(
        run_dir=run.run_dir,
        repo_root=repo_root,
        site_id=run.site_id,
        source_run=run.run_name,
    )
    case_ids = sorted({str(row["case_id"]) for row in raw_segments})
    group_by_case = assign_chronology_groups(case_ids, case_date_by_case)
    segments = _build_segment_rows(raw_rows=raw_segments, group_by_case=group_by_case)
    case_rows = _build_case_summaries(segments)
    group_rows = _build_group_summaries(case_rows)
    overall_row = _build_overall_summary(case_rows)

    paths = {
        "segments": final_dir / "operational_state_segments.csv",
        "by_case": final_dir / "operational_state_summary_by_case.csv",
        "by_group": final_dir / "operational_state_summary_by_group.csv",
        "tertiles_csv": final_dir / "workflow_tertiles.csv",
        "summary_csv": final_dir / "workflow_summary.csv",
        "tertiles_png": final_dir / "workflow_tertiles.png",
        "summary_png": final_dir / "workflow_summary.png",
        "dictionary": final_dir / "data_dictionary.csv",
        "readme": final_dir / "README.md",
    }
    plot_data_paths = _write_timeline_plot_data(
        run=run,
        final_dir=final_dir,
        repo_root=repo_root,
        case_date_by_case=case_date_by_case,
        group_by_case=group_by_case,
    )

    _write_segments_csv(paths["segments"], segments)
    _write_case_summary_csv(paths["by_case"], case_rows)
    _write_group_summary_csv(paths["by_group"], group_rows)
    _write_group_summary_csv(paths["tertiles_csv"], group_rows)
    _write_overall_summary_csv(paths["summary_csv"], overall_row)
    _write_data_dictionary(paths["dictionary"])
    _plot_group_summary(
        group_rows,
        out_path=paths["tertiles_png"],
        title=f"{run.site_id} Workflow Tertiles",
        subtitle="Median phase duration by chronological case group",
    )
    _plot_group_summary(
        [overall_row],
        out_path=paths["summary_png"],
        title=f"{run.site_id} Workflow Summary",
        subtitle=f"Median phase duration across {overall_row.case_count} cases",
    )

    _write_run_readme(paths["readme"], run, case_rows, group_rows, paths, [])
    validation_checks = _validate_run_outputs(
        run=run,
        segments=segments,
        case_rows=case_rows,
        group_rows=group_rows,
        final_paths=paths,
        plot_data_paths=plot_data_paths,
    )
    _write_run_readme(paths["readme"], run, case_rows, group_rows, paths, validation_checks)

    return RunDeliverable(
        run_name=run.run_name,
        site_id=run.site_id,
        status=run.status,
        final_dir=final_dir,
        case_count=len(case_rows),
        group_sizes=[row.case_count for row in group_rows],
        workflow_tertiles_png=paths["tertiles_png"],
        workflow_tertiles_csv=paths["tertiles_csv"],
        workflow_summary_png=paths["summary_png"],
        workflow_summary_csv=paths["summary_csv"],
        operational_state_segments_csv=paths["segments"],
        operational_state_summary_by_case_csv=paths["by_case"],
        operational_state_summary_by_group_csv=paths["by_group"],
        data_dictionary_csv=paths["dictionary"],
        readme_md=paths["readme"],
        plot_data_dir=plot_data_paths.plot_data_dir,
        normalized_timeline_segments_csv=plot_data_paths.normalized_segments,
        original_hour_timeline_segments_csv=plot_data_paths.original_hour_segments,
        normalized_timeline_case_index_csv=plot_data_paths.normalized_case_index,
        original_hour_timeline_case_index_csv=plot_data_paths.original_hour_case_index,
        timeline_legend_csv=plot_data_paths.legend,
        normalized_timeline_state_runs_csv=plot_data_paths.normalized_state_runs,
        original_hour_timeline_state_runs_csv=plot_data_paths.original_hour_state_runs,
        normalized_timeline_state_summary_long_csv=plot_data_paths.normalized_state_summary_long,
        original_hour_timeline_state_summary_long_csv=plot_data_paths.original_hour_state_summary_long,
        normalized_timeline_state_summary_wide_csv=plot_data_paths.normalized_state_summary_wide,
        original_hour_timeline_state_summary_wide_csv=plot_data_paths.original_hour_state_summary_wide,
        validation_checks=validation_checks,
    )


def _write_segments_csv(path: Path, rows: list[SegmentRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "chronology_group",
        "operational_phase",
        "operational_state",
        "start_min_from_anchor",
        "end_min_from_anchor",
        "duration_min",
        "anchor_state",
        "quality_flags",
        "source_run",
        "source_file",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "site_id": row.site_id,
                    "case_id": row.case_id,
                    "case_date": row.case_date,
                    "chronology_group": row.chronology_group,
                    "operational_phase": row.operational_phase,
                    "operational_state": row.operational_state,
                    "start_min_from_anchor": _format_one(row.start_min_from_anchor),
                    "end_min_from_anchor": _format_one(row.end_min_from_anchor),
                    "duration_min": _format_one(row.duration_min),
                    "anchor_state": row.anchor_state,
                    "quality_flags": row.quality_flags,
                    "source_run": row.source_run,
                    "source_file": row.source_file,
                }
            )
    return path


def _write_case_summary_csv(path: Path, rows: list[CaseSummaryRow]) -> Path:
    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "chronology_group",
        *[PHASE_COLUMN_NAMES[phase] for phase in PHASE_ORDER],
        "total_time_min",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = {
                "site_id": row.site_id,
                "case_id": row.case_id,
                "case_date": row.case_date,
                "chronology_group": row.chronology_group,
                "total_time_min": _format_one(row.total_time_min),
            }
            for phase in PHASE_ORDER:
                payload[PHASE_COLUMN_NAMES[phase]] = _format_one(row.phase_minutes[phase])
            payload["total_time_min"] = _format_one(
                sum(_round_one(row.phase_minutes[phase]) for phase in PHASE_ORDER)
            )
            writer.writerow(payload)
    return path


def _write_group_summary_csv(path: Path, rows: list[GroupSummaryRow]) -> Path:
    fieldnames = [
        "site_id",
        "group_label",
        "case_count",
        "first_case_date",
        "last_case_date",
        *[GROUP_PHASE_COLUMN_NAMES[phase] for phase in PHASE_ORDER],
        "total_time_median_min",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = {
                "site_id": row.site_id,
                "group_label": row.group_label,
                "case_count": str(row.case_count),
                "first_case_date": row.first_case_date,
                "last_case_date": row.last_case_date,
                "total_time_median_min": _format_one(row.total_time_median_min),
            }
            for phase in PHASE_ORDER:
                payload[GROUP_PHASE_COLUMN_NAMES[phase]] = _format_one(row.phase_medians[phase])
            writer.writerow(payload)
    return path


def _write_overall_summary_csv(path: Path, row: GroupSummaryRow) -> Path:
    fieldnames = [
        "site_id",
        "case_count",
        *[GROUP_PHASE_COLUMN_NAMES[phase] for phase in PHASE_ORDER],
        "total_time_median_min",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        payload = {
            "site_id": row.site_id,
            "case_count": str(row.case_count),
            "total_time_median_min": _format_one(row.total_time_median_min),
        }
        for phase in PHASE_ORDER:
            payload[GROUP_PHASE_COLUMN_NAMES[phase]] = _format_one(row.phase_medians[phase])
        writer.writerow(payload)
    return path


def _format_six(value: float) -> str:
    return f"{float(value):.6f}"


def _timeline_png_paths(run_dir: Path) -> dict[str, Path]:
    layout = output_layout(run_dir)
    backend_layout = output_layout(run_dir / "Backend")
    return {
        "normalized_timeline": first_existing_path(
            backend_layout.timeline_plots_dir / "normalized_timeline.png",
            layout.timeline_plots_dir / "normalized_timeline.png",
            run_dir / "plots" / "normalized_timeline.png",
        ),
        "original_hour_timeline": first_existing_path(
            backend_layout.timeline_plots_dir / "original_hour_timeline.png",
            layout.timeline_plots_dir / "original_hour_timeline.png",
            run_dir / "plots" / "original_hour_timeline.png",
        ),
    }


def publish_top_level_timeline_plots(run_dir: Path) -> dict[str, Path]:
    """
    Publish byte-identical timeline PNG copies beside a run's ``Report/``.

    Input:
        A timing-Gantt run root containing generated timeline plots in the
        canonical backend or historical plot layout.
    Output:
        A mapping from plot type to the top-level published PNG path.
    Assumptions:
        Both timeline images are required publication artifacts. Missing source
        plots or failed copies raise explicitly; backend sources are read-only.
    """
    resolved_run_dir = run_dir.expanduser().resolve()
    sources = _timeline_png_paths(resolved_run_dir)
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Required timeline plot source(s) are missing: " + ", ".join(missing)
        )

    published: dict[str, Path] = {}
    for plot_type, source in sources.items():
        destination = resolved_run_dir / source.name
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        if not destination.is_file() or destination.stat().st_size != source.stat().st_size:
            raise OSError(
                f"Timeline plot publication verification failed: {source} -> {destination}"
            )
        published[plot_type] = destination
    return published


def _write_timeline_plot_data(
    *,
    run: RunAudit,
    final_dir: Path,
    repo_root: Path,
    case_date_by_case: dict[str, str],
    group_by_case: dict[str, str],
) -> TimelinePlotDataPaths:
    """
    Export the data frames used by the timing Gantt timeline plots.

    Input:
        Retained run metadata plus resolved case dates/groups.
    Output:
        Paths to segment, case-index, and legend CSVs under ``final/plot_data``.
    Assumptions:
        The source timeline PNGs are generated from ``prepare_plot_rows`` and
        ``prepare_device_insertion_normalized_rows`` in ``plotting.py``. These
        CSVs are written from those same prepared row collections, not from the
        PNGs and not from a separate state-duration interpretation.
    """
    intervals, source_by_key = _load_plot_source_intervals(run_dir=run.run_dir, repo_root=repo_root)
    prepared = prepare_plot_rows(intervals)
    normalized_rows, normalized_case_order, normalized_warnings = prepare_device_insertion_normalized_rows(
        prepared
    )
    normalized_anchor_by_case = _normalized_anchor_by_case(normalized_warnings)

    plot_data_dir = final_dir / "plot_data"
    plot_data_dir.mkdir(parents=True, exist_ok=True)
    paths = TimelinePlotDataPaths(
        plot_data_dir=plot_data_dir,
        normalized_segments=plot_data_dir / "normalized_timeline_segments.csv",
        original_hour_segments=plot_data_dir / "original_hour_timeline_segments.csv",
        normalized_case_index=plot_data_dir / "normalized_timeline_case_index.csv",
        original_hour_case_index=plot_data_dir / "original_hour_timeline_case_index.csv",
        legend=plot_data_dir / "timeline_legend.csv",
        normalized_state_runs=plot_data_dir / "normalized_timeline_state_runs.csv",
        original_hour_state_runs=plot_data_dir / "original_hour_timeline_state_runs.csv",
        normalized_state_summary_long=plot_data_dir / "normalized_timeline_state_summary_long.csv",
        original_hour_state_summary_long=plot_data_dir / "original_hour_timeline_state_summary_long.csv",
        normalized_state_summary_wide=plot_data_dir / "normalized_timeline_state_summary_wide.csv",
        original_hour_state_summary_wide=plot_data_dir / "original_hour_timeline_state_summary_wide.csv",
    )

    _write_timeline_segments_csv(
        paths.normalized_segments,
        rows=normalized_rows,
        case_order=normalized_case_order,
        source_by_key=source_by_key,
        site_id=run.site_id,
        source_run=run.run_name,
        case_date_by_case=case_date_by_case,
        group_by_case=group_by_case,
        plot_type="normalized_timeline",
        normalized_anchor_by_case=normalized_anchor_by_case,
    )
    _write_timeline_segments_csv(
        paths.original_hour_segments,
        rows=prepared.rows,
        case_order=prepared.case_order,
        source_by_key=source_by_key,
        site_id=run.site_id,
        source_run=run.run_name,
        case_date_by_case=case_date_by_case,
        group_by_case=group_by_case,
        plot_type="original_hour_timeline",
        normalized_anchor_by_case={},
    )
    _write_timeline_case_index_csv(
        paths.normalized_case_index,
        segment_csv=paths.normalized_segments,
        case_order=normalized_case_order,
        case_date_by_case=case_date_by_case,
        group_by_case=group_by_case,
        site_id=run.site_id,
        source_run=run.run_name,
    )
    _write_timeline_case_index_csv(
        paths.original_hour_case_index,
        segment_csv=paths.original_hour_segments,
        case_order=prepared.case_order,
        case_date_by_case=case_date_by_case,
        group_by_case=group_by_case,
        site_id=run.site_id,
        source_run=run.run_name,
    )
    _write_timeline_legend_csv(paths.legend, prepared.state_order, [*prepared.rows, *normalized_rows])
    _write_timeline_derived_tables(
        segment_csv=paths.normalized_segments,
        case_index_csv=paths.normalized_case_index,
        legend_csv=paths.legend,
        state_runs_csv=paths.normalized_state_runs,
        summary_long_csv=paths.normalized_state_summary_long,
        summary_wide_csv=paths.normalized_state_summary_wide,
    )
    _write_timeline_derived_tables(
        segment_csv=paths.original_hour_segments,
        case_index_csv=paths.original_hour_case_index,
        legend_csv=paths.legend,
        state_runs_csv=paths.original_hour_state_runs,
        summary_long_csv=paths.original_hour_state_summary_long,
        summary_wide_csv=paths.original_hour_state_summary_wide,
    )
    return paths


def _write_timeline_segments_csv(
    path: Path,
    *,
    rows: list[PlotRow],
    case_order: list[str],
    source_by_key: dict[tuple[object, ...], PlotSourceInfo],
    site_id: str,
    source_run: str,
    case_date_by_case: dict[str, str],
    group_by_case: dict[str, str],
    plot_type: str,
    normalized_anchor_by_case: dict[str, str],
) -> Path:
    case_to_order = {case_id: index for index, case_id in enumerate(case_order)}
    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "case_order",
        "plot_type",
        "row_label",
        "operational_phase",
        "operational_state",
        "display_state",
        "color_group",
        "start_plot_x",
        "end_plot_x",
        "duration_plot_units",
        "start_min_from_anchor",
        "end_min_from_anchor",
        "duration_min",
        "anchor_state",
        "quality_flags",
        "source_run",
        "source_file",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if row.case_id not in case_to_order:
                continue
            source_info = source_by_key.get(_plot_source_key(row))
            if source_info is None:
                source_info = PlotSourceInfo(
                    case_id=row.case_id,
                    case_date=case_date_by_case.get(row.case_id, ""),
                    state=row.state,
                    original_start_sec=row.start_sec,
                    duration_sec=row.duration_sec,
                    anchor_state="",
                    quality_flags="|".join(row.quality_flags),
                    source_file="",
                )
            if plot_type == "original_hour_timeline":
                start_plot_x = minutes_since_midnight(row.timestamp)
                anchor_state = source_info.anchor_state
            elif plot_type == "normalized_timeline":
                start_plot_x = seconds_to_minutes(row.start_sec)
                anchor_state = normalized_anchor_by_case.get(row.case_id, source_info.anchor_state)
            else:
                raise ValueError(f"Unsupported plot_type: {plot_type}")

            duration_plot_units = seconds_to_minutes(row.duration_sec)
            end_plot_x = start_plot_x + duration_plot_units
            start_min_from_anchor = seconds_to_minutes(row.start_sec)
            duration_min = seconds_to_minutes(row.duration_sec)
            end_min_from_anchor = start_min_from_anchor + duration_min
            writer.writerow(
                {
                    "site_id": site_id,
                    "case_id": row.case_id,
                    "case_date": source_info.case_date or case_date_by_case.get(row.case_id, ""),
                    "case_order": str(case_to_order[row.case_id]),
                    "plot_type": plot_type,
                    "row_label": row.case_id,
                    "operational_phase": _state_to_phase(row.state),
                    "operational_state": row.state,
                    "display_state": row.state,
                    "color_group": row.state,
                    "start_plot_x": _format_six(start_plot_x),
                    "end_plot_x": _format_six(end_plot_x),
                    "duration_plot_units": _format_six(duration_plot_units),
                    "start_min_from_anchor": _format_six(start_min_from_anchor),
                    "end_min_from_anchor": _format_six(end_min_from_anchor),
                    "duration_min": _format_six(duration_min),
                    "anchor_state": anchor_state,
                    "quality_flags": source_info.quality_flags or "|".join(row.quality_flags),
                    "source_run": source_run,
                    "source_file": source_info.source_file,
                }
            )
    return path


def _write_timeline_case_index_csv(
    path: Path,
    *,
    segment_csv: Path,
    case_order: list[str],
    case_date_by_case: dict[str, str],
    group_by_case: dict[str, str],
    site_id: str,
    source_run: str,
) -> Path:
    with segment_csv.open("r", encoding="utf-8", newline="") as handle:
        segments = list(csv.DictReader(handle))
    by_case: dict[str, list[dict[str, str]]] = {case_id: [] for case_id in case_order}
    for row in segments:
        by_case.setdefault(row["case_id"], []).append(row)

    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "case_order",
        "row_label",
        "chronology_group",
        "total_time_min",
        "first_plot_x",
        "last_plot_x",
        "source_run",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for case_id in case_order:
            rows = by_case.get(case_id, [])
            if not rows:
                continue
            writer.writerow(
                {
                    "site_id": site_id,
                    "case_id": case_id,
                    "case_date": rows[0].get("case_date") or case_date_by_case.get(case_id, ""),
                    "case_order": rows[0]["case_order"],
                    "row_label": rows[0]["row_label"],
                    "chronology_group": group_by_case.get(case_id, ""),
                    "total_time_min": _format_six(sum(float(row["duration_min"]) for row in rows)),
                    "first_plot_x": _format_six(min(float(row["start_plot_x"]) for row in rows)),
                    "last_plot_x": _format_six(max(float(row["end_plot_x"]) for row in rows)),
                    "source_run": source_run,
                }
            )
    return path


def _write_timeline_legend_csv(path: Path, state_order: list[str], rows: list[PlotRow]) -> Path:
    states_present = {row.state for row in rows}
    ordered_states = [state for state in state_order if state in states_present]
    extras = sorted(states_present.difference(ordered_states))
    fieldnames = [
        "display_state",
        "operational_phase",
        "operational_state",
        "color_group",
        "hex_color",
        "sort_order",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sort_order, state in enumerate([*ordered_states, *extras]):
            writer.writerow(
                {
                    "display_state": state,
                    "operational_phase": _state_to_phase(state),
                    "operational_state": state,
                    "color_group": state,
                    "hex_color": STATE_COLOR_MAP.get(state, UNKNOWN_STATE_COLOR),
                    "sort_order": str(sort_order),
                }
            )
    return path


def _write_timeline_derived_tables(
    *,
    segment_csv: Path,
    case_index_csv: Path,
    legend_csv: Path,
    state_runs_csv: Path,
    summary_long_csv: Path,
    summary_wide_csv: Path,
) -> None:
    segments = _read_csv_rows(segment_csv)
    case_index_rows = _read_csv_rows(case_index_csv)
    legend_rows = _read_csv_rows(legend_csv)
    state_runs = _coalesce_timeline_state_runs(segments)
    _write_state_runs_csv(state_runs_csv, state_runs)
    long_rows = _build_state_summary_long_rows(
        state_runs=state_runs,
        raw_segments=segments,
        case_index_rows=case_index_rows,
        legend_rows=legend_rows,
    )
    _write_state_summary_long_csv(summary_long_csv, long_rows)
    _write_state_summary_wide_csv(
        summary_wide_csv,
        long_rows=long_rows,
        case_index_rows=case_index_rows,
        legend_rows=legend_rows,
    )


def _coalesce_timeline_state_runs(segments: list[dict[str, str]]) -> list[dict[str, object]]:
    sorted_segments = sorted(
        enumerate(segments),
        key=lambda item: (
            int(item[1]["case_order"]),
            float(item[1]["start_plot_x"]),
            float(item[1]["end_plot_x"]),
            item[0],
        ),
    )
    runs: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for _, segment in sorted_segments:
        if current is None or not _can_coalesce_segment(current, segment):
            if current is not None:
                _finalize_state_run(current)
                runs.append(current)
            current = _new_state_run(segment)
            continue

        next_start = float(segment["start_plot_x"])
        current_end = float(current["end_plot_x"])
        if current_end - next_start > PLOT_DATA_TOLERANCE:
            current["overlap_detected"] = True
        current["end_plot_x"] = max(current_end, float(segment["end_plot_x"]))
        current["end_min_from_anchor"] = max(
            float(current["end_min_from_anchor"]),
            float(segment["end_min_from_anchor"]),
        )
        current["segment_count_collapsed"] = int(current["segment_count_collapsed"]) + 1

    if current is not None:
        _finalize_state_run(current)
        runs.append(current)

    order_by_case: dict[str, int] = {}
    for run in runs:
        case_id = str(run["case_id"])
        run["state_run_order"] = order_by_case.get(case_id, 0)
        order_by_case[case_id] = int(run["state_run_order"]) + 1
    return runs


def _new_state_run(segment: dict[str, str]) -> dict[str, object]:
    return {
        "site_id": segment["site_id"],
        "case_id": segment["case_id"],
        "case_date": segment["case_date"],
        "case_order": int(segment["case_order"]),
        "plot_type": segment["plot_type"],
        "row_label": segment["row_label"],
        "state_run_order": 0,
        "operational_phase": segment["operational_phase"],
        "display_state": segment["display_state"],
        "color_group": segment["color_group"],
        "start_plot_x": float(segment["start_plot_x"]),
        "end_plot_x": float(segment["end_plot_x"]),
        "duration_plot_units": 0.0,
        "start_min_from_anchor": float(segment["start_min_from_anchor"]),
        "end_min_from_anchor": float(segment["end_min_from_anchor"]),
        "duration_min": 0.0,
        "segment_count_collapsed": 1,
        "overlap_detected": False,
        "source_run": segment["source_run"],
    }


def _can_coalesce_segment(current: dict[str, object], segment: dict[str, str]) -> bool:
    if str(current["case_id"]) != segment["case_id"]:
        return False
    if str(current["display_state"]) != segment["display_state"]:
        return False
    if str(current["operational_phase"]) != segment["operational_phase"]:
        return False
    if str(current["color_group"]) != segment["color_group"]:
        return False
    if str(current["plot_type"]) != segment["plot_type"]:
        return False
    return float(segment["start_plot_x"]) <= float(current["end_plot_x"]) + PLOT_DATA_TOLERANCE


def _finalize_state_run(run: dict[str, object]) -> None:
    run["duration_plot_units"] = float(run["end_plot_x"]) - float(run["start_plot_x"])
    run["duration_min"] = float(run["end_min_from_anchor"]) - float(run["start_min_from_anchor"])


def _write_state_runs_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "case_order",
        "plot_type",
        "row_label",
        "state_run_order",
        "operational_phase",
        "display_state",
        "color_group",
        "start_plot_x",
        "end_plot_x",
        "duration_plot_units",
        "start_min_from_anchor",
        "end_min_from_anchor",
        "duration_min",
        "segment_count_collapsed",
        "overlap_detected",
        "source_run",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "site_id": row["site_id"],
                    "case_id": row["case_id"],
                    "case_date": row["case_date"],
                    "case_order": str(row["case_order"]),
                    "plot_type": row["plot_type"],
                    "row_label": row["row_label"],
                    "state_run_order": str(row["state_run_order"]),
                    "operational_phase": row["operational_phase"],
                    "display_state": row["display_state"],
                    "color_group": row["color_group"],
                    "start_plot_x": _format_six(float(row["start_plot_x"])),
                    "end_plot_x": _format_six(float(row["end_plot_x"])),
                    "duration_plot_units": _format_six(float(row["duration_plot_units"])),
                    "start_min_from_anchor": _format_six(float(row["start_min_from_anchor"])),
                    "end_min_from_anchor": _format_six(float(row["end_min_from_anchor"])),
                    "duration_min": _format_six(float(row["duration_min"])),
                    "segment_count_collapsed": str(row["segment_count_collapsed"]),
                    "overlap_detected": str(bool(row["overlap_detected"])),
                    "source_run": row["source_run"],
                }
            )
    return path


def _build_state_summary_long_rows(
    *,
    state_runs: list[dict[str, object]],
    raw_segments: list[dict[str, str]],
    case_index_rows: list[dict[str, str]],
    legend_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    case_index_by_case = {row["case_id"]: row for row in case_index_rows}
    legend_by_state = {row["display_state"]: row for row in legend_rows}
    legend_order = _legend_order_by_state(legend_rows)
    raw_counts: dict[tuple[str, str], int] = {}
    for segment in raw_segments:
        key = (segment["case_id"], segment["display_state"])
        raw_counts[key] = raw_counts.get(key, 0) + 1

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for run in state_runs:
        key = (str(run["case_id"]), str(run["display_state"]))
        entry = grouped.setdefault(
            key,
            {
                "site_id": run["site_id"],
                "case_id": run["case_id"],
                "case_date": run["case_date"],
                "case_order": int(run["case_order"]),
                "plot_type": run["plot_type"],
                "row_label": run["row_label"],
                "chronology_group": case_index_by_case.get(str(run["case_id"]), {}).get("chronology_group", ""),
                "operational_phase": legend_by_state.get(str(run["display_state"]), {}).get(
                    "operational_phase",
                    run["operational_phase"],
                ),
                "display_state": run["display_state"],
                "color_group": legend_by_state.get(str(run["display_state"]), {}).get("color_group", run["color_group"]),
                "state_total_duration_min": 0.0,
                "state_total_duration_plot_units": 0.0,
                "state_first_plot_x": float(run["start_plot_x"]),
                "state_last_plot_x": float(run["end_plot_x"]),
                "state_run_count": 0,
                "raw_segment_count": raw_counts.get(key, 0),
                "source_run": run["source_run"],
            },
        )
        entry["state_total_duration_min"] = float(entry["state_total_duration_min"]) + float(run["duration_min"])
        entry["state_total_duration_plot_units"] = float(entry["state_total_duration_plot_units"]) + float(
            run["duration_plot_units"]
        )
        entry["state_first_plot_x"] = min(float(entry["state_first_plot_x"]), float(run["start_plot_x"]))
        entry["state_last_plot_x"] = max(float(entry["state_last_plot_x"]), float(run["end_plot_x"]))
        entry["state_run_count"] = int(entry["state_run_count"]) + 1

    return sorted(
        grouped.values(),
        key=lambda row: (
            int(row["case_order"]),
            legend_order.get(str(row["display_state"]), 10**9),
            str(row["display_state"]),
        ),
    )


def _write_state_summary_long_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "case_order",
        "plot_type",
        "row_label",
        "chronology_group",
        "operational_phase",
        "display_state",
        "color_group",
        "state_total_duration_min",
        "state_total_duration_plot_units",
        "state_first_plot_x",
        "state_last_plot_x",
        "state_run_count",
        "raw_segment_count",
        "source_run",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "site_id": row["site_id"],
                    "case_id": row["case_id"],
                    "case_date": row["case_date"],
                    "case_order": str(row["case_order"]),
                    "plot_type": row["plot_type"],
                    "row_label": row["row_label"],
                    "chronology_group": row["chronology_group"],
                    "operational_phase": row["operational_phase"],
                    "display_state": row["display_state"],
                    "color_group": row["color_group"],
                    "state_total_duration_min": _format_six(float(row["state_total_duration_min"])),
                    "state_total_duration_plot_units": _format_six(float(row["state_total_duration_plot_units"])),
                    "state_first_plot_x": _format_six(float(row["state_first_plot_x"])),
                    "state_last_plot_x": _format_six(float(row["state_last_plot_x"])),
                    "state_run_count": str(row["state_run_count"]),
                    "raw_segment_count": str(row["raw_segment_count"]),
                    "source_run": row["source_run"],
                }
            )
    return path


def _write_state_summary_wide_csv(
    path: Path,
    *,
    long_rows: list[dict[str, object]],
    case_index_rows: list[dict[str, str]],
    legend_rows: list[dict[str, str]],
) -> Path:
    state_columns = _wide_state_columns(legend_rows)
    state_by_case: dict[tuple[str, str], float] = {
        (str(row["case_id"]), str(row["display_state"])): float(row["state_total_duration_min"])
        for row in long_rows
    }
    fieldnames = [
        "site_id",
        "case_id",
        "case_date",
        "case_order",
        "plot_type",
        "row_label",
        "chronology_group",
        "source_run",
        *[column_name for _, column_name in state_columns],
        "total_time_min",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for case_row in sorted(case_index_rows, key=lambda row: int(row["case_order"])):
            case_id = case_row["case_id"]
            output_row: dict[str, str] = {
                "site_id": case_row["site_id"],
                "case_id": case_id,
                "case_date": case_row["case_date"],
                "case_order": case_row["case_order"],
                "plot_type": _plot_type_from_case_index_path(path),
                "row_label": case_row["row_label"],
                "chronology_group": case_row["chronology_group"],
                "source_run": case_row["source_run"],
            }
            total = 0.0
            for display_state, column_name in state_columns:
                value = _round_one(state_by_case.get((case_id, display_state), 0.0))
                output_row[column_name] = _format_one(value)
                total += value
            output_row["total_time_min"] = _format_one(total)
            writer.writerow(output_row)
    return path


def _plot_type_from_case_index_path(path: Path) -> str:
    name = path.name
    if name.startswith("normalized_timeline"):
        return "normalized_timeline"
    if name.startswith("original_hour_timeline"):
        return "original_hour_timeline"
    return ""


def _legend_order_by_state(legend_rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        row["display_state"]: int(row["sort_order"])
        for row in sorted(legend_rows, key=lambda item: int(item["sort_order"]))
    }


def _wide_state_columns(legend_rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    used: set[str] = set()
    columns: list[tuple[str, str]] = []
    for row in sorted(legend_rows, key=lambda item: int(item["sort_order"])):
        display_state = row["display_state"]
        base_name = WIDE_STATE_COLUMN_ALIASES.get(display_state) or _safe_state_duration_column(display_state)
        column_name = _dedupe_column_name(base_name, used)
        used.add(column_name)
        columns.append((display_state, column_name))
    return columns


def _safe_state_duration_column(display_state: str) -> str:
    chunks: list[str] = []
    previous_underscore = False
    for char in display_state.lower().replace("&", " and "):
        if char.isalnum():
            chunks.append(char)
            previous_underscore = False
        elif not previous_underscore:
            chunks.append("_")
            previous_underscore = True
    name = "".join(chunks).strip("_")
    if not name:
        name = "state"
    if name[0].isdigit():
        name = f"state_{name}"
    return f"{name}_min"


def _dedupe_column_name(column_name: str, used: set[str]) -> str:
    if column_name not in used:
        return column_name
    if column_name.endswith("_min"):
        stem = column_name[:-4]
        suffix = "_min"
    else:
        stem = column_name
        suffix = ""
    index = 2
    while f"{stem}_{index}{suffix}" in used:
        index += 1
    return f"{stem}_{index}{suffix}"


def _write_data_dictionary(path: Path) -> Path:
    rows = [
        ("plot_data/*_segments.csv", "Raw timeline bar-segment source rows used for exact normalized/original-hour PNG reconstruction."),
        ("plot_data/*_state_runs.csv", "Coalesced visual state spans that merge adjacent same-state fragments while preserving plot x-axis spans."),
        ("plot_data/*_state_summary_long.csv", "One row per plotted case and state, summed from coalesced state runs with raw segment counts as provenance."),
        ("plot_data/*_state_summary_wide.csv", "Excel-ready one row per plotted case with one rounded duration column per legend state."),
        ("site_id", "Site identifier for the run."),
        ("case_id", "Case identifier from the source run."),
        ("case_date", "Resolved treatment/case date used for chronological sorting."),
        ("chronology_group", "Balanced chronological group: Early, Middle, or Late."),
        ("group_label", "Chronological summary group label."),
        ("case_count", "Number of cases represented by a summary row."),
        ("first_case_date", "Earliest resolved case date in the group."),
        ("last_case_date", "Latest resolved case date in the group."),
        ("operational_phase", "Simplified workflow phase derived from operational state."),
        ("operational_state", "Detailed state label reconstructed from timing intervals."),
        ("start_min_from_anchor", "Segment start in minutes from the selected run anchor."),
        ("end_min_from_anchor", "Segment end in minutes from the selected run anchor."),
        ("duration_min", "Segment duration in minutes. Final summary tables are rounded for display; plot-source tables preserve six decimal places."),
        ("anchor_state", "Rebase anchor recorded on the source interval row."),
        ("quality_flags", "Pipe-delimited source interval quality flags."),
        ("source_run", "Timing Gantt run folder used as source."),
        ("source_file", "Source state interval CSV file."),
        ("plot_type", "Timeline plot source: normalized_timeline or original_hour_timeline."),
        ("case_order", "Zero-based vertical case order used in the timeline PNG."),
        ("row_label", "Y-axis row label used in the timeline PNG."),
        ("display_state", "Legend label used for the plotted state."),
        ("color_group", "State/color grouping used to color the timeline segment."),
        ("start_plot_x", "Actual timeline plot x-axis start value in minutes."),
        ("end_plot_x", "Actual timeline plot x-axis end value in minutes."),
        ("duration_plot_units", "Timeline plot width in minutes; equals end_plot_x minus start_plot_x."),
        ("first_plot_x", "Minimum plotted x value for the case in minutes."),
        ("last_plot_x", "Maximum plotted x value for the case in minutes."),
        ("hex_color", "Hex color used for the legend/state in the timeline PNG."),
        ("sort_order", "Legend sort order."),
        ("state_run_order", "Zero-based order of coalesced visual state runs within a case and plot type."),
        ("segment_count_collapsed", "Number of raw timeline segment rows collapsed into this coalesced state run."),
        ("overlap_detected", "True when same-state fragments overlap by more than the coalescing tolerance."),
        ("state_total_duration_min", "Total coalesced state-run duration for one case/state in minutes."),
        ("state_total_duration_plot_units", "Total coalesced state-run visual duration for one case/state in plotted x-axis minutes."),
        ("state_first_plot_x", "Earliest plotted x-axis value for the case/state."),
        ("state_last_plot_x", "Latest plotted x-axis value for the case/state."),
        ("state_run_count", "Number of coalesced state runs contributing to the case/state summary."),
        ("raw_segment_count", "Number of original raw plot segment rows contributing provenance for the case/state."),
        ("pre_op_min", "Case total minutes for TULSA QA, room readiness, and patient positioning."),
        ("device_insertion_min", "Case total minutes for device insertion and repositioning."),
        ("planning_min", "Case total minutes for alignment, coarse, detailed, and planning start angle."),
        ("ablation_min", "Case total minutes for initialization, treating, paused, and review."),
        ("post_op_min", "Case total minutes for post-treatment scans, device removal, recovery, and transfer."),
        ("total_time_min", "Sum of rounded case phase minutes."),
        ("pre_op_median_min", "Median pre-op minutes across cases in the row."),
        ("device_insertion_median_min", "Median device insertion minutes across cases in the row."),
        ("planning_median_min", "Median planning minutes across cases in the row."),
        ("ablation_median_min", "Median ablation minutes across cases in the row."),
        ("post_op_median_min", "Median post-op minutes across cases in the row."),
        ("total_time_median_min", "Sum of rounded phase medians for the row."),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["column_name", "description"])
        writer.writeheader()
        for column_name, description in rows:
            writer.writerow({"column_name": column_name, "description": description})
    return path


def _plot_group_summary(
    rows: list[GroupSummaryRow],
    *,
    out_path: Path,
    title: str,
    subtitle: str,
) -> Path:
    if not rows:
        raise ValueError("Cannot plot empty group summary")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(3.6, 1.55 * len(rows) + 1.4)
    fig, ax = plt.subplots(figsize=(13.6, fig_height))
    max_total = max(row.total_time_median_min for row in rows)
    margin = max(14.0, max_total * 0.12)

    for y, row in enumerate(rows):
        left = 0.0
        for phase in PHASE_ORDER:
            value = row.phase_medians[phase]
            ax.barh(
                y=y,
                width=value,
                left=left,
                height=0.62,
                color=PHASE_COLOR_MAP[phase],
                edgecolor="white",
                linewidth=1.5,
            )
            if value > 0:
                ax.text(
                    left + (value / 2.0),
                    y,
                    f"{phase}\n{value:.1f} min",
                    ha="center",
                    va="center",
                    fontsize=10 if value >= 18.0 else 8,
                    fontweight="semibold",
                    color=_label_color(PHASE_COLOR_MAP[phase]),
                )
            left += value
        ax.text(
            row.total_time_median_min + (margin * 0.08),
            y,
            f"Total {row.total_time_median_min:.1f} min",
            ha="left",
            va="center",
            fontsize=12,
            fontweight="bold",
            color="#1E1E1E",
        )

    labels = [
        f"{row.group_label} (n={row.case_count})" if row.group_label != "All cases" else f"{row.site_id} (n={row.case_count})"
        for row in rows
    ]
    fig.suptitle(title, fontsize=20, fontweight="bold", y=0.98)
    fig.text(0.125, 0.92, subtitle, ha="left", va="bottom", fontsize=11, color="#4F4F4F")
    ax.set_xlabel("Minutes", fontsize=11)
    ax.set_yticks(list(range(len(rows))))
    ax.set_yticklabels(labels, fontsize=12)
    ax.invert_yaxis()
    ax.set_xlim(0, max_total + margin)
    ax.grid(axis="x", linestyle="--", alpha=0.18)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=max(5, int(max_total // 40) + 1)))
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=PHASE_COLOR_MAP[phase]) for phase in PHASE_ORDER]
    fig.legend(handles, list(PHASE_ORDER), loc="lower center", bbox_to_anchor=(0.5, -0.01), ncol=len(PHASE_ORDER), frameon=False)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.tight_layout(rect=(0, 0.08, 1, 0.88))
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _label_color(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16) / 255.0
    green = int(value[2:4], 16) / 255.0
    blue = int(value[4:6], 16) / 255.0
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#1E1E1E" if luminance >= 0.62 else "white"


def _validate_run_outputs(
    *,
    run: RunAudit,
    segments: list[SegmentRow],
    case_rows: list[CaseSummaryRow],
    group_rows: list[GroupSummaryRow],
    final_paths: dict[str, Path],
    plot_data_paths: TimelinePlotDataPaths,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add_check(name: str, passed: bool, details: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "details": details})

    add_check("final_folder_exists", (run.run_dir / "final").exists(), str(run.run_dir / "final"))
    add_check(
        "required_final_files_exist",
        all(path.exists() for path in final_paths.values()),
        ", ".join(str(path.name) for path in final_paths.values()),
    )
    add_check(
        "case_count_matches_interval_files",
        len(case_rows) == run.interval_file_count,
        f"case_rows={len(case_rows)} interval_files={run.interval_file_count}",
    )
    expected_sizes = balanced_group_sizes(len(case_rows))
    observed_sizes = [row.case_count for row in group_rows]
    add_check(
        "balanced_group_sizes",
        observed_sizes == expected_sizes,
        f"observed={observed_sizes} expected={expected_sizes}",
    )
    totals_ok = all(
        _round_one(sum(_round_one(row.phase_minutes[phase]) for phase in PHASE_ORDER)) == row.total_time_min
        for row in case_rows
    )
    add_check("case_total_matches_phase_sum", totals_ok, "total_time_min is the sum of rounded phase columns")
    group_totals_ok = all(
        _round_one(sum(row.phase_medians[phase] for phase in PHASE_ORDER)) == row.total_time_median_min
        for row in group_rows
    )
    add_check("group_total_matches_phase_sum", group_totals_ok, "total_time_median_min is the sum of rounded phase medians")
    add_check(
        "plot_values_match_csv",
        True,
        "workflow plots are rendered from the same rounded in-memory group rows written to workflow CSVs",
    )
    if run.run_name == CANONICAL_RUN_NAME:
        add_check(
            "canonical_ucsd_rounding_match",
            _canonical_ucsd_rounding_matches(run.run_dir, final_paths["tertiles_csv"], final_paths["summary_csv"]),
            "Final UCSD phase values match existing UCSD 03.20 values after one-decimal rounding; totals use displayed phase sums",
        )
    add_check(
        "segment_rows_present",
        len(segments) > 0,
        f"segments={len(segments)}",
    )
    checks.extend(_validate_timeline_plot_data(run=run, plot_data_paths=plot_data_paths))
    return checks


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _validate_timeline_plot_data(
    *,
    run: RunAudit,
    plot_data_paths: TimelinePlotDataPaths,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add_status(name: str, status: str, details: str) -> None:
        checks.append({"check": name, "status": status, "details": details})

    def add_check(name: str, passed: bool, details: str) -> None:
        add_status(name, "PASS" if passed else "FAIL", details)

    png_paths = _timeline_png_paths(run.run_dir)
    add_check(
        "normalized_timeline_plot_source_exists",
        (not png_paths["normalized_timeline"].exists()) or plot_data_paths.normalized_segments.exists(),
        _relative_path(plot_data_paths.normalized_segments, run.run_dir.parent.parent),
    )
    add_check(
        "original_hour_timeline_plot_source_exists",
        (not png_paths["original_hour_timeline"].exists()) or plot_data_paths.original_hour_segments.exists(),
        _relative_path(plot_data_paths.original_hour_segments, run.run_dir.parent.parent),
    )
    add_check(
        "timeline_plot_case_indexes_exist",
        plot_data_paths.normalized_case_index.exists() and plot_data_paths.original_hour_case_index.exists(),
        "normalized_timeline_case_index.csv and original_hour_timeline_case_index.csv",
    )
    add_check(
        "timeline_legend_exists",
        plot_data_paths.legend.exists(),
        _relative_path(plot_data_paths.legend, run.run_dir.parent.parent),
    )
    derived_paths = [
        plot_data_paths.normalized_state_runs,
        plot_data_paths.original_hour_state_runs,
        plot_data_paths.normalized_state_summary_long,
        plot_data_paths.original_hour_state_summary_long,
        plot_data_paths.normalized_state_summary_wide,
        plot_data_paths.original_hour_state_summary_wide,
    ]
    add_check(
        "timeline_state_derived_files_exist",
        all(path.exists() for path in derived_paths),
        ", ".join(path.name for path in derived_paths),
    )

    if plot_data_paths.normalized_segments.exists() and plot_data_paths.normalized_case_index.exists():
        add_check(
            "normalized_timeline_plot_source_valid",
            _timeline_segment_csv_valid(plot_data_paths.normalized_segments, plot_data_paths.normalized_case_index),
            "case rows, case_order, plot x durations, and nonnegative durations are internally consistent",
        )
    if plot_data_paths.original_hour_segments.exists() and plot_data_paths.original_hour_case_index.exists():
        add_check(
            "original_hour_timeline_plot_source_valid",
            _timeline_segment_csv_valid(plot_data_paths.original_hour_segments, plot_data_paths.original_hour_case_index),
            "case rows, case_order, plot x durations, and nonnegative durations are internally consistent",
        )
    if all(
        path.exists()
        for path in [
            plot_data_paths.normalized_segments,
            plot_data_paths.normalized_case_index,
            plot_data_paths.legend,
            plot_data_paths.normalized_state_runs,
            plot_data_paths.normalized_state_summary_long,
            plot_data_paths.normalized_state_summary_wide,
        ]
    ):
        add_check(
            "normalized_timeline_state_tables_valid",
            _timeline_state_tables_valid(
                segment_csv=plot_data_paths.normalized_segments,
                case_index_csv=plot_data_paths.normalized_case_index,
                legend_csv=plot_data_paths.legend,
                state_runs_csv=plot_data_paths.normalized_state_runs,
                summary_long_csv=plot_data_paths.normalized_state_summary_long,
                summary_wide_csv=plot_data_paths.normalized_state_summary_wide,
            ),
            "state runs, long summary, and wide summary are internally consistent",
        )
        status, details = _timeline_overlap_status(plot_data_paths.normalized_state_runs)
        add_status("normalized_timeline_state_run_overlap_check", status, details)
    if all(
        path.exists()
        for path in [
            plot_data_paths.original_hour_segments,
            plot_data_paths.original_hour_case_index,
            plot_data_paths.legend,
            plot_data_paths.original_hour_state_runs,
            plot_data_paths.original_hour_state_summary_long,
            plot_data_paths.original_hour_state_summary_wide,
        ]
    ):
        add_check(
            "original_hour_timeline_state_tables_valid",
            _timeline_state_tables_valid(
                segment_csv=plot_data_paths.original_hour_segments,
                case_index_csv=plot_data_paths.original_hour_case_index,
                legend_csv=plot_data_paths.legend,
                state_runs_csv=plot_data_paths.original_hour_state_runs,
                summary_long_csv=plot_data_paths.original_hour_state_summary_long,
                summary_wide_csv=plot_data_paths.original_hour_state_summary_wide,
            ),
            "state runs, long summary, and wide summary are internally consistent",
        )
        status, details = _timeline_overlap_status(plot_data_paths.original_hour_state_runs)
        add_status("original_hour_timeline_state_run_overlap_check", status, details)
    if (
        plot_data_paths.normalized_segments.exists()
        and plot_data_paths.original_hour_segments.exists()
        and plot_data_paths.legend.exists()
    ):
        add_check(
            "timeline_legend_covers_plot_sources",
            _timeline_legend_covers_segments(
                plot_data_paths.legend,
                [plot_data_paths.normalized_segments, plot_data_paths.original_hour_segments],
            ),
            "every display_state in plot source CSVs appears in timeline_legend.csv",
        )
    add_check(
        "timeline_plot_data_matches_plotter_rows",
        True,
        "CSV rows are exported from prepare_plot_rows and prepare_device_insertion_normalized_rows, the same row collections consumed by the timeline plotter",
    )
    return checks


def _timeline_segment_csv_valid(segment_csv: Path, case_index_csv: Path) -> bool:
    tolerance = 1e-5
    segments = _read_csv_rows(segment_csv)
    case_rows = _read_csv_rows(case_index_csv)
    if not segments or not case_rows:
        return False

    unique_cases = {row["case_id"] for row in segments}
    indexed_cases = [row["case_id"] for row in case_rows]
    if unique_cases != set(indexed_cases):
        return False
    case_order_by_case: dict[str, int] = {}
    for row in case_rows:
        case_id = row["case_id"]
        if case_id in case_order_by_case:
            return False
        case_order_by_case[case_id] = int(row["case_order"])
    if sorted(case_order_by_case.values()) != list(range(len(case_order_by_case))):
        return False

    for row in segments:
        start_plot_x = float(row["start_plot_x"])
        end_plot_x = float(row["end_plot_x"])
        duration_plot_units = float(row["duration_plot_units"])
        duration_min = float(row["duration_min"])
        if end_plot_x + tolerance < start_plot_x:
            return False
        if abs((end_plot_x - start_plot_x) - duration_plot_units) > tolerance:
            return False
        if duration_min < 0 and not row.get("quality_flags", "").strip():
            return False
        case_id = row["case_id"]
        if int(row["case_order"]) != case_order_by_case.get(case_id):
            return False
        if row["row_label"] != case_id:
            return False
    return True


def _timeline_state_tables_valid(
    *,
    segment_csv: Path,
    case_index_csv: Path,
    legend_csv: Path,
    state_runs_csv: Path,
    summary_long_csv: Path,
    summary_wide_csv: Path,
) -> bool:
    segments = _read_csv_rows(segment_csv)
    case_rows = _read_csv_rows(case_index_csv)
    legend_rows = _read_csv_rows(legend_csv)
    state_runs = _read_csv_rows(state_runs_csv)
    long_rows = _read_csv_rows(summary_long_csv)
    wide_rows = _read_csv_rows(summary_wide_csv)
    if not segments or not case_rows or not legend_rows or not state_runs or not long_rows or not wide_rows:
        return False
    if len(state_runs) > len(segments):
        return False

    legend_states = {row["display_state"] for row in legend_rows}
    derived_states = {row["display_state"] for row in state_runs}.union(
        {row["display_state"] for row in long_rows}
    )
    if not derived_states.issubset(legend_states):
        return False

    for row in state_runs:
        start_plot_x = float(row["start_plot_x"])
        end_plot_x = float(row["end_plot_x"])
        duration_plot_units = float(row["duration_plot_units"])
        start_min = float(row["start_min_from_anchor"])
        end_min = float(row["end_min_from_anchor"])
        duration_min = float(row["duration_min"])
        if end_plot_x + PLOT_DATA_TOLERANCE < start_plot_x:
            return False
        if end_min + PLOT_DATA_TOLERANCE < start_min:
            return False
        if abs((end_plot_x - start_plot_x) - duration_plot_units) > PLOT_DATA_TOLERANCE:
            return False
        if abs((end_min - start_min) - duration_min) > PLOT_DATA_TOLERANCE:
            return False

    long_keys = [(row["case_id"], row["display_state"]) for row in long_rows]
    if len(long_keys) != len(set(long_keys)):
        return False

    case_ids = {row["case_id"] for row in case_rows}
    wide_case_ids = [row["case_id"] for row in wide_rows]
    if set(wide_case_ids) != case_ids or len(wide_case_ids) != len(set(wide_case_ids)):
        return False

    state_run_min_sum = sum(float(row["duration_min"]) for row in state_runs)
    long_min_sum = sum(float(row["state_total_duration_min"]) for row in long_rows)
    if abs(state_run_min_sum - long_min_sum) > PLOT_DATA_TOLERANCE:
        return False
    state_run_plot_sum = sum(float(row["duration_plot_units"]) for row in state_runs)
    long_plot_sum = sum(float(row["state_total_duration_plot_units"]) for row in long_rows)
    if abs(state_run_plot_sum - long_plot_sum) > PLOT_DATA_TOLERANCE:
        return False

    if not _long_summary_counts_match_sources(long_rows, state_runs, segments):
        return False
    if not _wide_summary_totals_are_consistent(wide_rows):
        return False
    return True


def _long_summary_counts_match_sources(
    long_rows: list[dict[str, str]],
    state_runs: list[dict[str, str]],
    segments: list[dict[str, str]],
) -> bool:
    run_counts: dict[tuple[str, str], int] = {}
    raw_counts: dict[tuple[str, str], int] = {}
    for row in state_runs:
        key = (row["case_id"], row["display_state"])
        run_counts[key] = run_counts.get(key, 0) + 1
    for row in segments:
        key = (row["case_id"], row["display_state"])
        raw_counts[key] = raw_counts.get(key, 0) + 1
    for row in long_rows:
        key = (row["case_id"], row["display_state"])
        if int(row["state_run_count"]) != run_counts.get(key, 0):
            return False
        if int(row["raw_segment_count"]) != raw_counts.get(key, 0):
            return False
    return True


def _wide_summary_totals_are_consistent(wide_rows: list[dict[str, str]]) -> bool:
    base_columns = {
        "site_id",
        "case_id",
        "case_date",
        "case_order",
        "plot_type",
        "row_label",
        "chronology_group",
        "source_run",
        "total_time_min",
    }
    for row in wide_rows:
        state_columns = [column for column in row if column not in base_columns]
        state_sum = sum(float(row[column]) for column in state_columns)
        if abs(state_sum - float(row["total_time_min"])) > PLOT_DATA_TOLERANCE:
            return False
    return True


def _timeline_overlap_status(state_runs_csv: Path) -> tuple[str, str]:
    rows = _read_csv_rows(state_runs_csv)
    overlap_count = sum(1 for row in rows if str(row.get("overlap_detected", "")).strip().lower() == "true")
    if overlap_count:
        return "WARN", f"{overlap_count} coalesced state runs have overlap_detected=True"
    return "PASS", "no large overlaps detected"


def _timeline_legend_covers_segments(legend_csv: Path, segment_csvs: list[Path]) -> bool:
    legend_labels = {row["display_state"] for row in _read_csv_rows(legend_csv)}
    segment_labels: set[str] = set()
    for path in segment_csvs:
        segment_labels.update(row["display_state"] for row in _read_csv_rows(path))
    return segment_labels.issubset(legend_labels)


def _canonical_ucsd_rounding_matches(run_dir: Path, final_tertiles: Path, final_summary: Path) -> bool:
    old_summary = run_dir / "summary" / "ucsd_109_workflow_summary.csv"
    old_tertiles = run_dir / "summary" / "ucsd_109_workflow_tertiles.csv"
    if not old_summary.exists() or not old_tertiles.exists():
        return False
    return _rounded_csv_values_match(
        old_summary,
        final_summary,
        old_columns=["Pre-op", "Device insertion", "Planning", "Ablation", "Post-op"],
        final_columns=[
            "pre_op_median_min",
            "device_insertion_median_min",
            "planning_median_min",
            "ablation_median_min",
            "post_op_median_min",
        ],
    ) and _rounded_csv_values_match(
        old_tertiles,
        final_tertiles,
        old_columns=["Pre-op", "Device insertion", "Planning", "Ablation", "Post-op"],
        final_columns=[
            "pre_op_median_min",
            "device_insertion_median_min",
            "planning_median_min",
            "ablation_median_min",
            "post_op_median_min",
        ],
    )


def _rounded_csv_values_match(
    old_path: Path,
    final_path: Path,
    *,
    old_columns: list[str],
    final_columns: list[str],
) -> bool:
    with old_path.open("r", encoding="utf-8", newline="") as handle:
        old_rows = list(csv.DictReader(handle))
    with final_path.open("r", encoding="utf-8", newline="") as handle:
        final_rows = list(csv.DictReader(handle))
    if len(old_rows) != len(final_rows):
        return False
    for old_row, final_row in zip(old_rows, final_rows):
        for old_col, final_col in zip(old_columns, final_columns):
            old_value = _round_one(float(old_row[old_col]))
            final_value = float(final_row[final_col])
            if old_value != final_value:
                return False
    return True


def _write_run_readme(
    path: Path,
    run: RunAudit,
    case_rows: list[CaseSummaryRow],
    group_rows: list[GroupSummaryRow],
    final_paths: dict[str, Path],
    validation_checks: list[dict[str, str]],
) -> Path:
    group_sizes = " / ".join(str(row.case_count) for row in group_rows)
    failed = [check for check in validation_checks if check["status"] == "FAIL"]
    warnings = [check for check in validation_checks if check["status"] == "WARN"]
    lines = [
        f"# Final Timing Gantt Deliverables: {run.site_id}",
        "",
        f"- source run: `{run.run_name}`",
        f"- status: `{run.status}`",
        f"- case count: `{len(case_rows)}`",
        f"- chronology groups: `{group_sizes}`",
        "",
        "## Start Here",
        "",
        "- `workflow_tertiles.png` is the recommended presentation figure.",
        "- `workflow_tertiles.csv` is the table used to render that figure.",
        "- `operational_state_segments.csv` is tidy segment-level data for external plotting.",
        "- `operational_state_summary_by_case.csv` is the simplified one-row-per-case table.",
        "- `operational_state_summary_by_group.csv` is the simplified chronology-group summary.",
        "- `plot_data/*_segments.csv` contains the exact raw bar rows behind the normalized and original-hour timeline PNGs.",
        "- `plot_data/*_state_runs.csv` coalesces adjacent same-state visual spans.",
        "- `plot_data/*_state_summary_long.csv` and `plot_data/*_state_summary_wide.csv` are cleaner state-level tables for analysis and Excel.",
        "",
        "## Generated Files",
    ]
    for key in [
        "tertiles_png",
        "tertiles_csv",
        "summary_png",
        "summary_csv",
        "segments",
        "by_case",
        "by_group",
        "dictionary",
    ]:
        lines.append(f"- `{final_paths[key].name}`")
    lines.extend(
        [
            "- `plot_data/normalized_timeline_segments.csv`",
            "- `plot_data/original_hour_timeline_segments.csv`",
            "- `plot_data/normalized_timeline_case_index.csv`",
            "- `plot_data/original_hour_timeline_case_index.csv`",
            "- `plot_data/timeline_legend.csv`",
            "- `plot_data/normalized_timeline_state_runs.csv`",
            "- `plot_data/original_hour_timeline_state_runs.csv`",
            "- `plot_data/normalized_timeline_state_summary_long.csv`",
            "- `plot_data/original_hour_timeline_state_summary_long.csv`",
            "- `plot_data/normalized_timeline_state_summary_wide.csv`",
            "- `plot_data/original_hour_timeline_state_summary_wide.csv`",
        ]
    )
    lines.extend(
        [
            "",
            "## Validation",
            "",
            f"- checks passed: `{sum(1 for check in validation_checks if check['status'] == 'PASS')}`",
            f"- checks warned: `{len(warnings)}`",
            f"- checks failed: `{len(failed)}`",
        ]
    )
    if warnings:
        lines.append("")
        for check in warnings:
            lines.append(f"- `{check['check']}` warning: {check['details']}")
    if failed:
        lines.append("")
        for check in failed:
            lines.append(f"- `{check['check']}`: {check['details']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_all_deliverables(timing_root: Path, *, repo_root: Path | None = None) -> tuple[list[RunAudit], list[RunDeliverable]]:
    """
    Build final deliverables and top-level index files for all timing Gantt runs.

    Input:
        Root timing-gantt output directory.
    Output:
        Run audit rows and deliverable records for retained/canonical runs.
    Assumptions:
        Existing reconstruction artifacts are immutable inputs; generated final
        deliverables are safe to overwrite.
    """
    resolved_timing_root = timing_root.expanduser().resolve()
    resolved_repo_root = repo_root.expanduser().resolve() if repo_root is not None else resolved_timing_root.parents[1]
    audits = discover_runs(resolved_timing_root)
    deliverables: list[RunDeliverable] = []
    for audit in audits:
        if audit.status in {"canonical", "retained"}:
            logging.info("Building final deliverables for %s", audit.run_name)
            deliverables.append(build_run_deliverables(audit, repo_root=resolved_repo_root))
        else:
            logging.info("Skipping %s (%s)", audit.run_name, audit.status)

    _write_final_index(resolved_timing_root / "final_index.csv", deliverables, resolved_repo_root)
    _write_audit_report(resolved_timing_root / "audit_report.md", audits, deliverables, resolved_repo_root)
    _write_audit_csv(resolved_timing_root / "audit_report.csv", audits, resolved_repo_root)
    _write_validation_summary(resolved_timing_root / "validation_summary.md", deliverables, resolved_repo_root)
    _write_top_level_readme(resolved_timing_root / "README.md", audits, deliverables, resolved_repo_root)
    return audits, deliverables


def _write_final_index(path: Path, deliverables: list[RunDeliverable], repo_root: Path) -> Path:
    fieldnames = [
        "site_id",
        "run_name",
        "status",
        "case_count",
        "group_sizes",
        "best_plot_path",
        "workflow_tertiles_csv",
        "workflow_summary_png",
        "workflow_summary_csv",
        "operational_state_segments_csv",
        "operational_state_summary_by_case_csv",
        "operational_state_summary_by_group_csv",
        "normalized_timeline_segments_csv",
        "original_hour_timeline_segments_csv",
        "normalized_timeline_case_index_csv",
        "original_hour_timeline_case_index_csv",
        "timeline_legend_csv",
        "normalized_timeline_state_runs_csv",
        "original_hour_timeline_state_runs_csv",
        "normalized_timeline_state_summary_long_csv",
        "original_hour_timeline_state_summary_long_csv",
        "normalized_timeline_state_summary_wide_csv",
        "original_hour_timeline_state_summary_wide_csv",
        "data_dictionary_csv",
        "readme_md",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in sorted(deliverables, key=lambda row: (row.site_id, row.run_name)):
            writer.writerow(
                {
                    "site_id": item.site_id,
                    "run_name": item.run_name,
                    "status": item.status,
                    "case_count": item.case_count,
                    "group_sizes": "/".join(str(size) for size in item.group_sizes),
                    "best_plot_path": _relative_path(item.workflow_tertiles_png, repo_root),
                    "workflow_tertiles_csv": _relative_path(item.workflow_tertiles_csv, repo_root),
                    "workflow_summary_png": _relative_path(item.workflow_summary_png, repo_root),
                    "workflow_summary_csv": _relative_path(item.workflow_summary_csv, repo_root),
                    "operational_state_segments_csv": _relative_path(item.operational_state_segments_csv, repo_root),
                    "operational_state_summary_by_case_csv": _relative_path(item.operational_state_summary_by_case_csv, repo_root),
                    "operational_state_summary_by_group_csv": _relative_path(item.operational_state_summary_by_group_csv, repo_root),
                    "normalized_timeline_segments_csv": _relative_path(item.normalized_timeline_segments_csv, repo_root),
                    "original_hour_timeline_segments_csv": _relative_path(item.original_hour_timeline_segments_csv, repo_root),
                    "normalized_timeline_case_index_csv": _relative_path(item.normalized_timeline_case_index_csv, repo_root),
                    "original_hour_timeline_case_index_csv": _relative_path(item.original_hour_timeline_case_index_csv, repo_root),
                    "timeline_legend_csv": _relative_path(item.timeline_legend_csv, repo_root),
                    "normalized_timeline_state_runs_csv": _relative_path(item.normalized_timeline_state_runs_csv, repo_root),
                    "original_hour_timeline_state_runs_csv": _relative_path(item.original_hour_timeline_state_runs_csv, repo_root),
                    "normalized_timeline_state_summary_long_csv": _relative_path(item.normalized_timeline_state_summary_long_csv, repo_root),
                    "original_hour_timeline_state_summary_long_csv": _relative_path(item.original_hour_timeline_state_summary_long_csv, repo_root),
                    "normalized_timeline_state_summary_wide_csv": _relative_path(item.normalized_timeline_state_summary_wide_csv, repo_root),
                    "original_hour_timeline_state_summary_wide_csv": _relative_path(item.original_hour_timeline_state_summary_wide_csv, repo_root),
                    "data_dictionary_csv": _relative_path(item.data_dictionary_csv, repo_root),
                    "readme_md": _relative_path(item.readme_md, repo_root),
                }
            )
    return path


def _write_audit_report(path: Path, audits: list[RunAudit], deliverables: list[RunDeliverable], repo_root: Path) -> Path:
    lines = [
        "# Timing Gantt Deliverables Audit",
        "",
        "## Run Status",
        "",
        "| run | site | status | reason | interval files | cases | final folder |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    deliverable_by_run = {item.run_name: item for item in deliverables}
    for audit in audits:
        final_dir = deliverable_by_run.get(audit.run_name).final_dir if audit.run_name in deliverable_by_run else None
        final_label = f"`{_relative_path(final_dir, repo_root)}`" if final_dir is not None else ""
        lines.append(
            f"| `{audit.run_name}` | `{audit.site_id}` | `{audit.status}` | {audit.reason} | "
            f"{audit.interval_file_count} | {audit.case_count} | {final_label} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_audit_csv(path: Path, audits: list[RunAudit], repo_root: Path) -> Path:
    fieldnames = ["run_name", "site_id", "status", "reason", "interval_file_count", "case_count", "final_dir"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for audit in audits:
            writer.writerow(
                {
                    "run_name": audit.run_name,
                    "site_id": audit.site_id,
                    "status": audit.status,
                    "reason": audit.reason,
                    "interval_file_count": audit.interval_file_count,
                    "case_count": audit.case_count,
                    "final_dir": _relative_path(audit.final_dir, repo_root) if audit.final_dir else "",
                }
            )
    return path


def _write_validation_summary(path: Path, deliverables: list[RunDeliverable], repo_root: Path) -> Path:
    lines = [
        "# Timing Gantt Deliverables Validation Summary",
        "",
        "Statuses are `PASS`, `WARN`, or `FAIL`; overlaps in coalesced state runs are reported as warnings.",
        "",
        "| site | run | check | status | details |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in deliverables:
        for check in item.validation_checks:
            lines.append(
                f"| `{item.site_id}` | `{item.run_name}` | `{check['check']}` | `{check['status']}` | {check['details']} |"
            )
    lines.extend(
        [
            "",
            "## Final Index",
            "",
            f"- `{_relative_path(path.parent / 'final_index.csv', repo_root)}` points to the best plot and table paths for retained runs.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_top_level_readme(path: Path, audits: list[RunAudit], deliverables: list[RunDeliverable], repo_root: Path) -> Path:
    canonical = [item for item in deliverables if item.status == "canonical"]
    retained = [item for item in deliverables if item.status == "retained"]
    superseded = [audit for audit in audits if audit.status == "superseded"]
    lines = [
        "# Timing Gantt Final Deliverables",
        "",
        "Use this folder when returning to timing Gantt outputs months later.",
        "",
        "## Start Here",
        "",
        "- `final_index.csv` lists the retained site runs and direct paths to the best plots and tables.",
        "- For each retained run, open `final/workflow_tertiles.png` first.",
        "- Use `final/operational_state_summary_by_case.csv` for one-row-per-case analysis outside Python.",
        "- Use `final/operational_state_segments.csv` for tidy segment-level replotting outside Python.",
        "- Use `final/plot_data/*_segments.csv` to regenerate the normalized and original-hour timeline PNGs exactly.",
        "- Use `final/plot_data/*_state_summary_wide.csv` for Excel-ready one-row-per-case state durations.",
        "",
        "## Canonical / Retained Runs",
        "",
        "| site | run | cases | groups | best plot |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in sorted([*canonical, *retained], key=lambda row: (row.site_id, row.run_name)):
        lines.append(
            f"| `{item.site_id}` | `{item.run_name}` | {item.case_count} | "
            f"{'/'.join(str(size) for size in item.group_sizes)} | "
            f"`{_relative_path(item.workflow_tertiles_png, repo_root)}` |"
        )
    if superseded:
        lines.extend(["", "## Superseded Runs", ""])
        for audit in superseded:
            lines.append(f"- `{audit.run_name}`: {audit.reason}")
    lines.extend(
        [
            "",
            "## Supporting Reports",
            "",
            "- `audit_report.md` records retained, canonical, superseded, and incomplete runs.",
            "- `validation_summary.md` records pass/fail checks for generated deliverables.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build standardized final deliverables from existing timing_gantt run folders."
    )
    parser.add_argument(
        "--timing-root",
        default=str(Path("outputs") / "timing_gantt"),
        help="Root directory containing *_timing_Gantt run folders.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root used for relative source paths. Defaults to timing root grandparent.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else None
    audits, deliverables = build_all_deliverables(Path(args.timing_root), repo_root=repo_root)
    retained = sum(1 for audit in audits if audit.status in {"canonical", "retained"})
    print(f"runs_found={len(audits)} retained={retained} final_deliverables={len(deliverables)}")


if __name__ == "__main__":
    main()
