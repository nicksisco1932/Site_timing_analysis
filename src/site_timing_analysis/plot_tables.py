from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from .models import StateInterval
from .output_layout import first_existing_path, output_layout
from .plotting import prepare_plot_rows


def _parse_optional_int(text: str) -> int | None:
    value = str(text).strip()
    if value == "":
        return None
    return int(value)


def _parse_quality_flags(text: str) -> list[str]:
    value = str(text).strip()
    if value == "":
        return []
    return [flag for flag in value.split("|") if flag]


def load_state_intervals(intervals_dir: Path) -> list[StateInterval]:
    """
    Load exported state-interval CSVs for one completed run.

    Input:
        Directory containing ``*_state_intervals.csv`` files.
    Output:
        Parsed ``StateInterval`` rows across all cases.
    Assumptions:
        Files were written by ``write_state_intervals_csv`` and therefore use the
        staged-pipeline interval schema.
    """
    interval_paths = sorted(intervals_dir.glob("*_state_intervals.csv"))
    if not interval_paths:
        raise FileNotFoundError(f"No state interval CSVs found in {intervals_dir}")

    intervals: list[StateInterval] = []
    for interval_path in interval_paths:
        with interval_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                intervals.append(
                    StateInterval(
                        case_id=row["case_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        state=row["state"].strip() or None,
                        start_sec=float(row["start_sec"]),
                        duration_sec=float(row["duration_sec"]),
                        rebase_anchor=row["rebase_anchor"].strip() or None,
                        origin_event_type=row["origin_event_type"],
                        source=row["source"],
                        is_synthetic=str(row["is_synthetic"]).strip().lower() == "true",
                        source_detail=row["source_detail"],
                        row_number=_parse_optional_int(row["row_number"]),
                        state_assignment_rule=row["state_assignment_rule"].strip() or None,
                        cleanup_rule_applied=row["cleanup_rule_applied"].strip() or None,
                        quality_flags=_parse_quality_flags(row["quality_flags"]),
                        segment_id=row["segment_id"].strip() or None,
                        event_kind=_parse_optional_int(row["event_kind"]),
                        drop_reason=row["drop_reason"].strip() or None,
                        insertion_rule=row["insertion_rule"].strip() or None,
                        raw_payload={},
                    )
                )
    return intervals


def export_plot_tables(run_dir: Path) -> tuple[Path, Path]:
    """
    Export the numeric tables behind the plot-ready state rows for one run.

    Input:
        Completed run directory containing ``state_intervals`` exports.
    Output:
        Paths to ``per_case_state_durations.csv`` and ``per_case_summary.csv``.
    Assumptions:
        Plot bars are derived from ``prepare_plot_rows`` and should therefore be
        exported from the same filtered rows rather than from raw intervals.
    """
    layout = output_layout(run_dir)
    intervals_dir = first_existing_path(layout.state_intervals_dir, run_dir / "state_intervals")
    tables_dir = layout.tables_dir
    tables_dir.mkdir(parents=True, exist_ok=True)

    prepared = prepare_plot_rows(load_state_intervals(intervals_dir))

    per_segment_path = tables_dir / "per_case_state_durations.csv"
    with per_segment_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["case_id", "state", "start_sec", "end_sec", "duration_min"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in prepared.rows:
            writer.writerow(
                {
                    "case_id": row.case_id,
                    "state": row.state,
                    "start_sec": f"{float(row.start_sec):.6f}",
                    "end_sec": f"{float(row.start_sec + row.duration_sec):.6f}",
                    "duration_min": f"{float(row.duration_sec) / 60.0:.6f}",
                }
            )

    summary_rows: dict[str, dict[str, float]] = {case_id: {} for case_id in prepared.case_order}
    for row in prepared.rows:
        case_totals = summary_rows.setdefault(row.case_id, {})
        case_totals[row.state] = case_totals.get(row.state, 0.0) + (float(row.duration_sec) / 60.0)

    summary_path = tables_dir / "per_case_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["case_id", *prepared.state_order, "total_time"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for case_id in prepared.case_order:
            case_totals = summary_rows.get(case_id, {})
            output_row = {"case_id": case_id}
            total_time = 0.0
            for state in prepared.state_order:
                value = case_totals.get(state, 0.0)
                output_row[state] = f"{value:.6f}"
                total_time += value
            output_row["total_time"] = f"{total_time:.6f}"
            writer.writerow(output_row)

    return per_segment_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export numeric tables backing the plot-ready state-duration timelines."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Completed run directory containing state_intervals and plots.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    per_segment_path, summary_path = export_plot_tables(run_dir)
    print(f"per_case_state_durations={per_segment_path}")
    print(f"per_case_summary={summary_path}")


if __name__ == "__main__":
    main()
