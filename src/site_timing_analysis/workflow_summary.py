from __future__ import annotations

import argparse
import csv
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from .output_layout import first_existing_path, output_layout
from .plot_tables import export_plot_tables


PHASE_ORDER: tuple[str, ...] = (
    "Pre-op",
    "Device insertion",
    "Planning",
    "Ablation",
    "Post-op",
)

PHASE_STATE_MAP: dict[str, tuple[str, ...]] = {
    "Pre-op": (
        "TULSA QA",
        "Room ready",
        "Patient positioning & induction",
    ),
    "Device insertion": (
        "Device insertion",
        "Device repositioning",
    ),
    "Planning": (
        "Alignment",
        "Coarse",
        "Detailed",
        "Planning start angle",
    ),
    "Ablation": (
        "Initialization",
        "Treating",
        "Paused",
        "Review",
    ),
    "Post-op": (
        "Post-treatment scans & Device removal",
        "Patient recovery & transfer",
    ),
}

PHASE_COLOR_MAP: dict[str, str] = {
    "Pre-op": "#7B7E87",
    "Device insertion": "#6F9960",
    "Planning": "#2E5AAC",
    "Ablation": "#D5A017",
    "Post-op": "#9B8AA1",
}


@dataclass(slots=True)
class WorkflowSummary:
    site_id: str
    case_count: int
    phase_minutes: dict[str, float]
    total_time: float


@dataclass(slots=True)
class WorkflowSummaryGroup:
    site_id: str
    group_label: str
    row_label: str
    case_count: int
    case_ids: list[str]
    first_case_date: str | None
    last_case_date: str | None
    phase_minutes: dict[str, float]
    total_time: float


def _summary_slug(site_id: str) -> str:
    return site_id.strip().lower().replace(" ", "_")


def _parse_minutes(text: str | None) -> float:
    if text is None:
        return 0.0
    value = str(text).strip()
    if value == "":
        return 0.0
    return float(value)


def _load_per_case_summary(summary_path: Path) -> list[dict[str, str]]:
    if not summary_path.exists():
        raise FileNotFoundError(
            f"Missing per-case summary table: {summary_path}. "
            "Run site_timing_analysis.plot_tables first or provide a completed run directory."
        )
    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_case_manifest_rows(run_dir: Path) -> list[dict[str, str]]:
    layout = output_layout(run_dir)
    case_manifest_path = first_existing_path(layout.case_manifest_path, run_dir / "case_manifest.csv")
    if not case_manifest_path.exists():
        return []
    with case_manifest_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _ensure_per_case_summary(run_dir: Path) -> Path:
    summary_path = output_layout(run_dir).tables_dir / "per_case_summary.csv"
    if summary_path.exists():
        return summary_path
    logging.info("per_case_summary.csv missing; exporting plot tables from state_intervals")
    _, exported_summary_path = export_plot_tables(run_dir)
    return exported_summary_path


def _parse_case_date(text: str | None) -> str | None:
    value = str(text or "").strip()
    if value == "":
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(f"{value}T00:00:00").date().isoformat()
        except ValueError:
            return None


def _derive_case_date_from_state_intervals(run_dir: Path, case_id: str) -> str | None:
    layout = output_layout(run_dir)
    interval_path = first_existing_path(
        layout.state_intervals_dir / f"{case_id}_state_intervals.csv",
        run_dir / "state_intervals" / f"{case_id}_state_intervals.csv",
    )
    if not interval_path.exists():
        return None
    with interval_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            case_date = _parse_case_date(row.get("timestamp"))
            if case_date is not None:
                return case_date
    return None


def _resolve_case_dates(run_dir: Path, case_ids: list[str]) -> dict[str, str | None]:
    manifest_rows = _load_case_manifest_rows(run_dir)
    manifest_date_by_case: dict[str, str | None] = {}
    if manifest_rows:
        for row in manifest_rows:
            case_id = str(row.get("case_id", "")).strip()
            if case_id == "":
                continue
            manifest_date_by_case[case_id] = _parse_case_date(row.get("case_date"))

    case_date_by_case: dict[str, str | None] = {}
    for case_id in case_ids:
        case_date = manifest_date_by_case.get(case_id)
        if case_date is None:
            case_date = _derive_case_date_from_state_intervals(run_dir, case_id)
        case_date_by_case[case_id] = case_date
    return case_date_by_case


def _case_sort_key(row: dict[str, float | str | None]) -> tuple[object, ...]:
    case_date = str(row.get("case_date") or "").strip()
    case_id = str(row["case_id"])
    if case_date != "":
        return (0, case_date, case_id)
    return (1, case_id)


def compute_case_phase_minutes(case_row: dict[str, str]) -> dict[str, float]:
    """
    Roll one per-case state summary row into the presentation phase groups.

    Input:
        One row from ``per_case_summary.csv`` with minute totals by detailed state.
    Output:
        Phase-total minutes for the five requested workflow phases.
    Assumptions:
        Missing state columns are treated as zero so the rollup remains stable
        across runs with sparse state presence.
    """
    phase_minutes: dict[str, float] = {}
    for phase in PHASE_ORDER:
        phase_minutes[phase] = sum(_parse_minutes(case_row.get(state)) for state in PHASE_STATE_MAP[phase])
    return phase_minutes


def compute_workflow_summary(run_dir: Path, site_id: str) -> tuple[WorkflowSummary, list[dict[str, float]]]:
    """
    Compute median phase durations for one site run using existing per-case data.

    Input:
        Completed run directory and the site identifier to display/export.
    Output:
        The aggregated summary row plus per-case phase durations used to compute it.
    Assumptions:
        The displayed ``total_time`` equals the sum of the displayed phase medians
        so the exported row matches the stacked-bar width exactly.
    """
    summary_path = _ensure_per_case_summary(run_dir)
    per_case_rows = _load_per_case_summary(summary_path)
    if not per_case_rows:
        raise ValueError(f"No case rows found in {summary_path}")

    case_date_by_case = _resolve_case_dates(run_dir, [row["case_id"] for row in per_case_rows])
    per_case_phase_rows: list[dict[str, float]] = []
    for row in per_case_rows:
        phase_minutes = compute_case_phase_minutes(row)
        phase_minutes["case_id"] = row["case_id"]
        phase_minutes["case_date"] = case_date_by_case.get(row["case_id"]) or ""
        phase_minutes["total_time"] = sum(float(phase_minutes[phase]) for phase in PHASE_ORDER)
        per_case_phase_rows.append(phase_minutes)

    summary_phase_minutes = {
        phase: float(median([float(row[phase]) for row in per_case_phase_rows]))
        for phase in PHASE_ORDER
    }
    total_time = sum(summary_phase_minutes[phase] for phase in PHASE_ORDER)
    return (
        WorkflowSummary(
            site_id=site_id,
            case_count=len(per_case_phase_rows),
            phase_minutes=summary_phase_minutes,
            total_time=total_time,
        ),
        per_case_phase_rows,
    )


def compute_workflow_tertiles(run_dir: Path, site_id: str) -> tuple[list[WorkflowSummaryGroup], list[dict[str, float]]]:
    """
    Compute chronological tertile workflow summaries for one completed site run.

    Input:
        Completed run directory and the site identifier to display/export.
    Output:
        Three grouped median-summary rows plus the sorted per-case phase rows used.
    Assumptions:
        Cases are ordered by ``case_date`` when available, then by earliest
        interval timestamp date, and finally by ``case_id`` for deterministic
        fallback ordering.
    """
    _, per_case_phase_rows = compute_workflow_summary(run_dir, site_id)
    ordered_rows = sorted(per_case_phase_rows, key=_case_sort_key)

    tertile_specs: tuple[tuple[str, int, int | None], ...] = (
        ("Early", 0, 10),
        ("Mid", 10, 20),
        ("Late", 20, None),
    )
    groups: list[WorkflowSummaryGroup] = []
    for group_label, start, stop in tertile_specs:
        subset = ordered_rows[start:stop]
        if not subset:
            continue
        phase_minutes = {
            phase: float(median([float(row[phase]) for row in subset]))
            for phase in PHASE_ORDER
        }
        total_time = sum(phase_minutes[phase] for phase in PHASE_ORDER)
        groups.append(
            WorkflowSummaryGroup(
                site_id=site_id,
                group_label=group_label,
                row_label=f"{site_id} {group_label} (n={len(subset)})",
                case_count=len(subset),
                case_ids=[str(row["case_id"]) for row in subset],
                first_case_date=str(subset[0].get("case_date") or "").strip() or None,
                last_case_date=str(subset[-1].get("case_date") or "").strip() or None,
                phase_minutes=phase_minutes,
                total_time=total_time,
            )
        )
    return groups, ordered_rows


def compute_workflow_by_year(run_dir: Path, site_id: str) -> tuple[list[WorkflowSummaryGroup], list[dict[str, float]]]:
    """
    Compute calendar-year workflow summaries for one completed site run.

    Input:
        Completed run directory and the site identifier to display/export.
    Output:
        Year-grouped median-summary rows plus the per-case phase rows used.
    Assumptions:
        Each case must resolve to a calendar date via explicit ``case_date`` or
        earliest interval timestamp; unresolved cases are treated as an error.
    """
    _, per_case_phase_rows = compute_workflow_summary(run_dir, site_id)
    missing_case_dates = [
        str(row["case_id"])
        for row in per_case_phase_rows
        if str(row.get("case_date") or "").strip() == ""
    ]
    if missing_case_dates:
        details = ", ".join(missing_case_dates[:10])
        raise ValueError(
            "Cannot compute workflow-by-year summary because these cases have no "
            f"resolved case date: {details}"
        )

    rows_by_year: dict[str, list[dict[str, float]]] = {}
    for row in sorted(per_case_phase_rows, key=_case_sort_key):
        year = str(row["case_date"])[:4]
        rows_by_year.setdefault(year, []).append(row)

    groups: list[WorkflowSummaryGroup] = []
    for year in sorted(rows_by_year):
        subset = rows_by_year[year]
        phase_minutes = {
            phase: float(median([float(row[phase]) for row in subset]))
            for phase in PHASE_ORDER
        }
        total_time = sum(phase_minutes[phase] for phase in PHASE_ORDER)
        groups.append(
            WorkflowSummaryGroup(
                site_id=site_id,
                group_label=year,
                row_label=f"{site_id} {year} (n={len(subset)})",
                case_count=len(subset),
                case_ids=[str(row["case_id"]) for row in subset],
                first_case_date=str(subset[0].get("case_date") or "").strip() or None,
                last_case_date=str(subset[-1].get("case_date") or "").strip() or None,
                phase_minutes=phase_minutes,
                total_time=total_time,
            )
        )
    return groups, per_case_phase_rows


def _format_minutes(value: float) -> str:
    return f"{float(value):.6f}"


def _luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16) / 255.0
    green = int(value[2:4], 16) / 255.0
    blue = int(value[4:6], 16) / 255.0
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _label_color(hex_color: str) -> str:
    return "#1E1E1E" if _luminance(hex_color) >= 0.62 else "white"


def export_workflow_summary_csv(summary: WorkflowSummary, out_path: Path) -> Path:
    """
    Write the one-row workflow summary table used by the presentation plot.

    Input:
        Aggregated site-level workflow summary and the target CSV path.
    Output:
        The written CSV path.
    Assumptions:
        ``total_time`` is the sum of the exported phase columns.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["site_id", "case_count", *PHASE_ORDER, "total_time"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        row = {
            "site_id": summary.site_id,
            "case_count": str(summary.case_count),
            "total_time": _format_minutes(summary.total_time),
        }
        for phase in PHASE_ORDER:
            row[phase] = _format_minutes(summary.phase_minutes[phase])
        writer.writerow(row)
    return out_path


def export_workflow_tertiles_csv(groups: list[WorkflowSummaryGroup], out_path: Path) -> Path:
    """
    Write the chronological-tertile workflow summary table used by the plot.

    Input:
        Grouped median summaries and the target CSV path.
    Output:
        The written CSV path.
    Assumptions:
        Each row's ``total_time`` is the sum of that row's exported phase values.
    """
    return export_workflow_groups_csv(groups, out_path)


def export_workflow_groups_csv(groups: list[WorkflowSummaryGroup], out_path: Path) -> Path:
    """
    Write grouped workflow summary rows used by the presentation plots.

    Input:
        Grouped median summaries and the target CSV path.
    Output:
        The written CSV path.
    Assumptions:
        Each row's ``total_time`` is the sum of that row's exported phase values.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "site_id",
            "group_label",
            "case_count",
            "case_ids",
            "first_case_date",
            "last_case_date",
            *PHASE_ORDER,
            "total_time",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for group in groups:
            row = {
                "site_id": group.site_id,
                "group_label": group.group_label,
                "case_count": str(group.case_count),
                "case_ids": "|".join(group.case_ids),
                "first_case_date": group.first_case_date or "",
                "last_case_date": group.last_case_date or "",
                "total_time": _format_minutes(group.total_time),
            }
            for phase in PHASE_ORDER:
                row[phase] = _format_minutes(group.phase_minutes[phase])
            writer.writerow(row)
    return out_path


def plot_workflow_summary(summary: WorkflowSummary, out_path: Path) -> Path:
    """
    Render a one-row stacked workflow summary figure for presentation use.

    Input:
        Aggregated site-level workflow summary and the target PNG path.
    Output:
        The written plot path.
    Assumptions:
        Phase widths are measured in minutes and match the exported CSV exactly.
    """
    return plot_workflow_groups(
        groups=[
            WorkflowSummaryGroup(
                site_id=summary.site_id,
                group_label="All cases",
                row_label=summary.site_id,
                case_count=summary.case_count,
                case_ids=[],
                first_case_date=None,
                last_case_date=None,
                phase_minutes=dict(summary.phase_minutes),
                total_time=summary.total_time,
            )
        ],
        title=f"{summary.site_id} Workflow Summary",
        subtitle=f"Median phase duration across {summary.case_count} cases",
        out_path=out_path,
    )


def plot_workflow_groups(
    groups: list[WorkflowSummaryGroup],
    *,
    title: str,
    subtitle: str,
    out_path: Path,
) -> Path:
    """
    Render one or more workflow summary rows as a stacked horizontal bar figure.

    Input:
        Ordered workflow summary groups, figure title/subtitle, and output path.
    Output:
        The written plot path.
    Assumptions:
        Group order is already the desired top-to-bottom display order.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(3.6, 1.55 * len(groups) + 1.4)
    fig, ax = plt.subplots(figsize=(13.6, fig_height))

    max_total_time = max(group.total_time for group in groups)
    total_margin = max(14.0, max_total_time * 0.12)
    y_positions = list(range(len(groups)))

    for y, group in zip(y_positions, groups):
        left = 0.0
        for phase in PHASE_ORDER:
            value = float(group.phase_minutes[phase])
            color = PHASE_COLOR_MAP[phase]
            ax.barh(
                y=y,
                width=value,
                left=left,
                height=0.62,
                color=color,
                edgecolor="white",
                linewidth=1.5,
            )
            fontsize = 11 if value >= 18.0 else 9
            ax.text(
                left + (value / 2.0),
                y,
                f"{phase}\n{int(round(value))} min",
                ha="center",
                va="center",
                color=_label_color(color),
                fontsize=fontsize,
                fontweight="semibold",
            )
            left += value

        ax.text(
            group.total_time + (total_margin * 0.08),
            y,
            f"Total {int(round(group.total_time))} min",
            ha="left",
            va="center",
            fontsize=12,
            fontweight="bold",
            color="#1E1E1E",
        )

    fig.suptitle(title, fontsize=20, fontweight="bold", y=0.98)
    fig.text(
        0.125,
        0.92,
        subtitle,
        ha="left",
        va="bottom",
        fontsize=11,
        color="#4F4F4F",
    )
    ax.set_xlabel("Minutes", fontsize=11)
    ax.set_yticks(y_positions)
    ax.set_yticklabels([group.row_label for group in groups], fontsize=12)
    ax.invert_yaxis()
    ax.set_xlim(0, max_total_time + total_margin)
    ax.grid(axis="x", linestyle="--", alpha=0.18)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=max(5, math.ceil(max_total_time / 40.0))))

    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=PHASE_COLOR_MAP[phase]) for phase in PHASE_ORDER]
    fig.legend(
        handles,
        list(PHASE_ORDER),
        loc="lower center",
        bbox_to_anchor=(0.5, -0.01),
        ncol=len(PHASE_ORDER),
        frameon=False,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.tight_layout(rect=(0, 0.08, 1, 0.88))
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out_path


def export_workflow_summary(run_dir: Path, site_id: str) -> tuple[Path, Path, WorkflowSummary, list[dict[str, float]]]:
    """
    Export the workflow summary CSV and PNG for one completed run.

    Input:
        Completed run directory and the site identifier to display/export.
    Output:
        CSV path, PNG path, summary row, and the per-case phase rows used.
    Assumptions:
        Output filenames follow the lowercased site identifier naming convention.
    """
    summary_dir = output_layout(run_dir).reports_dir / "workflow_summary"
    slug = _summary_slug(site_id)
    summary_csv = summary_dir / f"{slug}_workflow_summary.csv"
    summary_png = summary_dir / f"{slug}_workflow_summary.png"

    summary, per_case_phase_rows = compute_workflow_summary(run_dir, site_id)
    export_workflow_summary_csv(summary, summary_csv)
    plot_workflow_summary(summary, summary_png)
    return summary_csv, summary_png, summary, per_case_phase_rows


def export_workflow_tertiles(
    run_dir: Path,
    site_id: str,
) -> tuple[Path, Path, list[WorkflowSummaryGroup], list[dict[str, float]]]:
    """
    Export the chronological-tertile workflow summary CSV and PNG for one run.

    Input:
        Completed run directory and the site identifier to display/export.
    Output:
        CSV path, PNG path, grouped summaries, and the sorted per-case phase rows used.
    Assumptions:
        Output filenames follow the lowercased site identifier naming convention.
    """
    summary_dir = output_layout(run_dir).reports_dir / "workflow_summary"
    slug = _summary_slug(site_id)
    tertile_csv = summary_dir / f"{slug}_workflow_tertiles.csv"
    tertile_png = summary_dir / f"{slug}_workflow_tertiles.png"

    groups, ordered_rows = compute_workflow_tertiles(run_dir, site_id)
    export_workflow_tertiles_csv(groups, tertile_csv)
    plot_workflow_groups(
        groups,
        title=f"{site_id} Workflow Tertiles",
        subtitle="Median phase duration by chronological tertile",
        out_path=tertile_png,
    )
    return tertile_csv, tertile_png, groups, ordered_rows


def export_workflow_by_year(
    run_dir: Path,
    site_id: str,
) -> tuple[Path, Path, list[WorkflowSummaryGroup], list[dict[str, float]]]:
    """
    Export the calendar-year workflow summary CSV and PNG for one run.

    Input:
        Completed run directory and the site identifier to display/export.
    Output:
        CSV path, PNG path, grouped summaries, and the per-case phase rows used.
    Assumptions:
        Output filenames follow the lowercased site identifier naming convention.
    """
    summary_dir = output_layout(run_dir).reports_dir / "workflow_summary"
    slug = _summary_slug(site_id)
    year_csv = summary_dir / f"{slug}_workflow_by_year.csv"
    year_png = summary_dir / f"{slug}_workflow_by_year.png"

    groups, per_case_phase_rows = compute_workflow_by_year(run_dir, site_id)
    export_workflow_groups_csv(groups, year_csv)
    plot_workflow_groups(
        groups,
        title=f"{site_id} Workflow by Year",
        subtitle="Median phase duration by calendar year",
        out_path=year_png,
    )
    return year_csv, year_png, groups, per_case_phase_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a site-level workflow summary plot from existing timing exports."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Completed timing-gantt run directory containing tables/per_case_summary.csv.",
    )
    parser.add_argument(
        "--site-id",
        required=True,
        help="Site identifier to display in the exported summary, for example UCSD_109.",
    )
    parser.add_argument(
        "--mode",
        choices=("summary", "tertiles", "by-year"),
        default="summary",
        help="Summary mode to export. Default: summary.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if args.mode == "tertiles":
        tertile_csv, tertile_png, groups, _ = export_workflow_tertiles(run_dir, args.site_id)
        print(f"tertile_csv={tertile_csv}")
        print(f"tertile_png={tertile_png}")
        print(f"group_sizes={','.join(str(group.case_count) for group in groups)}")
    elif args.mode == "by-year":
        year_csv, year_png, groups, _ = export_workflow_by_year(run_dir, args.site_id)
        print(f"year_csv={year_csv}")
        print(f"year_png={year_png}")
        print(f"years={','.join(group.group_label for group in groups)}")
        print(f"group_sizes={','.join(str(group.case_count) for group in groups)}")
    else:
        summary_csv, summary_png, summary, _ = export_workflow_summary(run_dir, args.site_id)
        print(f"summary_csv={summary_csv}")
        print(f"summary_png={summary_png}")
        print(f"case_count={summary.case_count}")
        print(f"total_time={summary.total_time:.6f}")


if __name__ == "__main__":
    main()
