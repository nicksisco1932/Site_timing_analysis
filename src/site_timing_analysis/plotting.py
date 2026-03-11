from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from .models import StateInterval


STATE_DISPLAY_ORDER: tuple[str, ...] = (
    "TULSA QA",
    "Room ready",
    "Patient positioning & induction",
    "Device insertion",
    "Device repositioning",
    "Alignment",
    "Coarse",
    "Detailed",
    "Planning start angle",
    "Initialization",
    "Treating",
    "Paused",
    "Review",
    "Post-treatment scans & Device removal",
    "Patient recovery & transfer",
    "NA",
)

STATE_COLOR_MAP: dict[str, str] = {
    "TULSA QA": "#D9D9D9",
    "Room ready": "#B3B3B3",
    "Patient positioning & induction": "#8C8C8C",
    "Device insertion": "#9BCD9B",
    "Device repositioning": "#698B69",
    "Alignment": "#ADD8E6",
    "Coarse": "#4169E1",
    "Detailed": "#27408B",
    "Planning start angle": "#000080",
    "Initialization": "#EEDD82",
    "Treating": "#DAA520",
    "Paused": "#B8860B",
    "Review": "#8B6508",
    "Post-treatment scans & Device removal": "#C1FFC1",
    "Patient recovery & transfer": "#8B7B8B",
    "NA": "#FFFFFF",
}

UNKNOWN_STATE_COLOR = "slategray"


@dataclass(slots=True)
class PlotRow:
    case_id: str
    timestamp: datetime
    state: str
    start_sec: float
    duration_sec: float
    color: str
    row_number: int | None
    quality_flags: list[str]


@dataclass(slots=True)
class PlotPreparation:
    rows: list[PlotRow]
    case_order: list[str]
    state_order: list[str]
    warnings: list[str]


def get_plot_output_paths(output_dir: Path) -> dict[str, Path]:
    plots_dir = output_dir.resolve() / "plots"
    return {
        "plots_dir": plots_dir,
        "normalized_timeline": plots_dir / "normalized_timeline.png",
        "original_hour_timeline": plots_dir / "original_hour_timeline.png",
    }


def seconds_to_minutes(value_sec: float) -> float:
    return float(value_sec) / 60.0


def minutes_since_midnight(ts: datetime) -> float:
    return float(ts.hour * 60 + ts.minute) + (float(ts.second) / 60.0) + (float(ts.microsecond) / 60_000_000.0)


def minutes_to_hhmm_label(minutes: float) -> str:
    total_minutes = int(round(float(minutes)))
    sign = ""
    if total_minutes < 0:
        sign = "-"
        total_minutes = abs(total_minutes)
    clock_minutes = total_minutes % (24 * 60)
    hours = clock_minutes // 60
    mins = clock_minutes % 60
    return f"{sign}{hours:02d}:{mins:02d}"


def choose_tick_spacing_minutes(min_minute: float, max_minute: float) -> int:
    span = float(max_minute) - float(min_minute)
    return 30 if span <= 360 else 60


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if percentile <= 0:
        return values[0]
    if percentile >= 100:
        return values[-1]
    rank = (percentile / 100.0) * (len(values) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return values[low]
    weight = rank - low
    return values[low] + (values[high] - values[low]) * weight


def compute_normalized_axis_window_seconds(
    rows: Iterable[PlotRow],
    *,
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
    margin_sec: float = 300.0,
) -> tuple[float, float] | None:
    starts = [float(row.start_sec) for row in rows]
    if not starts:
        return None
    ends = [float(row.start_sec) + float(row.duration_sec) for row in rows]
    values = sorted([*starts, *ends])
    lower = _percentile(values, lower_percentile) - float(margin_sec)
    upper = _percentile(values, upper_percentile) + float(margin_sec)
    if upper <= lower:
        upper = lower + max(1.0, float(margin_sec) * 2.0)
    return lower, upper


def _interval_sort_key(item: StateInterval) -> tuple[object, ...]:
    row_rank = item.row_number if item.row_number is not None else 10**12
    return (item.case_id, item.timestamp, row_rank, item.origin_event_type)


def _is_empty_state(state: str | None) -> bool:
    if state is None:
        return True
    text = state.strip()
    return text == "" or text == "NA"


def prepare_plot_rows(state_intervals: Iterable[StateInterval]) -> PlotPreparation:
    ordered = sorted(list(state_intervals), key=_interval_sort_key)
    warnings: list[str] = []
    rows: list[PlotRow] = []
    unknown_states_in_order: list[str] = []
    warned_unknown: set[str] = set()

    for item in ordered:
        if _is_empty_state(item.state):
            warnings.append(f"{item.case_id}:plot_excluded_empty_state:row={item.row_number}")
            continue
        if item.duration_sec <= 0:
            warnings.append(
                f"{item.case_id}:plot_excluded_nonpositive_duration:row={item.row_number}:"
                f"duration_sec={item.duration_sec}"
            )
            continue

        state = str(item.state)
        if state in STATE_COLOR_MAP:
            color = STATE_COLOR_MAP[state]
        else:
            color = UNKNOWN_STATE_COLOR
            if state not in warned_unknown:
                warnings.append(f"{item.case_id}:plot_unknown_state_appended:{state}")
                warned_unknown.add(state)
            if state not in unknown_states_in_order:
                unknown_states_in_order.append(state)

        if item.quality_flags:
            warnings.append(
                f"{item.case_id}:plot_row_quality_flags:row={item.row_number}:"
                f"flags={','.join(item.quality_flags)}"
            )

        rows.append(
            PlotRow(
                case_id=item.case_id,
                timestamp=item.timestamp,
                state=state,
                start_sec=float(item.start_sec),
                duration_sec=float(item.duration_sec),
                color=color,
                row_number=item.row_number,
                quality_flags=list(item.quality_flags),
            )
        )

    case_order = sorted({row.case_id for row in rows})
    if not case_order:
        case_order = sorted({item.case_id for item in ordered})

    states_present = {row.state for row in rows}
    known_present = [state for state in STATE_DISPLAY_ORDER if state in states_present]
    state_order = [*known_present, *[state for state in unknown_states_in_order if state in states_present]]

    if not rows:
        warnings.append("plot:no_plottable_rows")

    return PlotPreparation(
        rows=rows,
        case_order=case_order,
        state_order=state_order,
        warnings=warnings,
    )


def _build_legend(fig: plt.Figure, ax: plt.Axes, state_order: list[str], rows: list[PlotRow]) -> None:
    plotted_states = {row.state for row in rows}
    legend_states = [state for state in state_order if state in plotted_states]
    if not legend_states:
        return
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=STATE_COLOR_MAP.get(state, UNKNOWN_STATE_COLOR))
        for state in legend_states
    ]
    # Keep legend outside the axes (below), centered, and in readable columns.
    ncols = max(3, min(6, math.ceil(len(legend_states) / 2)))
    fig.legend(
        handles,
        legend_states,
        title="State",
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        ncol=ncols,
        frameon=False,
        borderaxespad=0.0,
        columnspacing=1.2,
        handlelength=1.4,
        handletextpad=0.5,
    )


def _plot_normalized(prepared: PlotPreparation, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(3.0, 0.6 * max(1, len(prepared.case_order)) + 1.5)
    fig, ax = plt.subplots(figsize=(12, fig_height))

    case_to_y = {case_id: idx for idx, case_id in enumerate(prepared.case_order)}
    for row in prepared.rows:
        y = case_to_y[row.case_id]
        ax.barh(
            y=y,
            width=seconds_to_minutes(row.duration_sec),
            left=seconds_to_minutes(row.start_sec),
            height=0.8,
            color=row.color,
            edgecolor="none",
        )

    axis_window_sec = compute_normalized_axis_window_seconds(prepared.rows)
    if axis_window_sec is not None:
        min_sec, max_sec = axis_window_sec
        ax.set_xlim(seconds_to_minutes(min_sec), seconds_to_minutes(max_sec))

    ax.set_title("Normalized Timeline (Rebased)")
    ax.set_xlabel("Rebased Time (minutes)")
    ax.set_ylabel("Case")
    ax.set_yticks(list(case_to_y.values()))
    ax.set_yticklabels(prepared.case_order)
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    _build_legend(fig, ax, prepared.state_order, prepared.rows)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def _plot_original_hour(prepared: PlotPreparation, out_path: Path) -> list[str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(3.0, 0.6 * max(1, len(prepared.case_order)) + 1.5)
    fig, ax = plt.subplots(figsize=(12, fig_height))
    warnings: list[str] = []
    plot_start_minutes: list[float] = []
    plot_end_minutes: list[float] = []

    case_to_y = {case_id: idx for idx, case_id in enumerate(prepared.case_order)}
    by_case: dict[str, list[PlotRow]] = {case_id: [] for case_id in prepared.case_order}
    for row in prepared.rows:
        by_case[row.case_id].append(row)
        y = case_to_y[row.case_id]
        start_minute = minutes_since_midnight(row.timestamp)
        duration_minute = seconds_to_minutes(row.duration_sec)
        end_minute = start_minute + duration_minute
        plot_start_minutes.append(start_minute)
        plot_end_minutes.append(end_minute)
        ax.barh(
            y=y,
            width=duration_minute,
            left=start_minute,
            height=0.8,
            color=row.color,
            edgecolor="none",
        )

    for case_id, rows in by_case.items():
        for row in rows:
            end_ts = row.timestamp + timedelta(seconds=row.duration_sec)
            if end_ts.date() != row.timestamp.date():
                warnings.append(
                    f"{case_id}:plot_original_hour_crosses_midnight:row={row.row_number}:"
                    f"start={row.timestamp.isoformat()}:end={end_ts.isoformat()}"
                )
                break

    ax.set_title("Original-Hour Timeline")
    ax.set_xlabel("Absolute Clock Time")
    ax.set_ylabel("Case")
    ax.set_yticks(list(case_to_y.values()))
    ax.set_yticklabels(prepared.case_order)
    ax.invert_yaxis()
    if plot_start_minutes and plot_end_minutes:
        min_minute = min(plot_start_minutes)
        max_minute = max(plot_end_minutes)
        spacing = choose_tick_spacing_minutes(min_minute, max_minute)
        start_tick = int(math.floor(min_minute / spacing) * spacing)
        end_tick = int(math.ceil(max_minute / spacing) * spacing)
        ticks = list(range(start_tick, end_tick + spacing, spacing))
        ax.set_xticks(ticks)
        ax.set_xlim(start_tick, end_tick)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: minutes_to_hhmm_label(value)))
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    _build_legend(fig, ax, prepared.state_order, prepared.rows)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return warnings


def generate_timeline_plots(
    state_intervals: Iterable[StateInterval],
    output_dir: Path,
) -> tuple[dict[str, Path], list[str]]:
    prepared = prepare_plot_rows(state_intervals)
    paths = get_plot_output_paths(output_dir)

    _plot_normalized(prepared, paths["normalized_timeline"])
    original_hour_warnings = _plot_original_hour(prepared, paths["original_hour_timeline"])

    warnings = [*prepared.warnings, *original_hour_warnings]
    return paths, warnings
