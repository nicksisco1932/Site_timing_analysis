#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_plot_timing.py

Read:
  - timing_summary_<site>.csv  (per-patient durations in minutes)
  - auditlogs_<site>_states.csv (optional, per-event states with start_sec, duration_sec)

Generate:
  - Per-patient stacked bar plot (x-axis = PtId)
  - Boxplots for phase distributions
  - Histograms for Treating / MRITotal / ProcedureTotal
  - Gantt-style timeline across patients from states CSV

Outputs PNGs into --outdir.
"""

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

from .tulsa_workflow import PLOTTED_STATES, STATE_COLORS


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot timing summary and Gantt-style timelines."
    )
    parser.add_argument(
        "--summary-csv",
        required=True,
        help="Path to timing_summary_<site>.csv",
    )
    parser.add_argument(
        "--outdir",
        required=True,
        help="Directory to write plots into.",
    )
    parser.add_argument(
        "--site",
        default=None,
        help="Optional site label for figure titles, for example Stanford_064.",
    )
    parser.add_argument(
        "--states-csv",
        default=None,
        help="Optional path to auditlogs_<site>_states.csv for Gantt plots.",
    )
    return parser.parse_args()


# Core workflow phases in the summary CSV
PHASE_COLS = PLOTTED_STATES


def load_summary(path_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(path_csv)

    # Sort by Pt or PtId to keep case order stable
    if "Pt" in df.columns:
        df = df.sort_values("Pt")
    elif "PtId" in df.columns:
        df = df.sort_values("PtId")

    if "PtId" in df.columns:
        df["PtId"] = df["PtId"].astype(str)
    else:
        df["PtId"] = df["Pt"].astype(str)

    return df


def load_states(path_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(path_csv)

    # Require these to build a Gantt
    required = {"PtId", "CurrentState", "start_sec", "duration_sec"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            f"States CSV is missing columns: {', '.join(sorted(missing))}"
        )

    df["PtId"] = df["PtId"].astype(str)
    return df


def plot_per_patient_stacked(df: pd.DataFrame, outdir: Path, site_label: str | None):
    cols_present = [c for c in PHASE_COLS if c in df.columns]
    if not cols_present:
        print("[WARN] No expected phase columns found in summary CSV.")
        return

    n_pts = len(df)
    x_vals = range(n_pts)

    width = max(12, n_pts * 0.15)
    fig, ax = plt.subplots(figsize=(width, 6))

    bottom = pd.Series([0.0] * n_pts, index=df.index)

    for col in cols_present:
        ax.bar(x_vals, df[col].values, bottom=bottom.values, label=col)
        bottom = bottom + df[col].fillna(0)

    ax.set_xlabel("Patient ID")
    ax.set_ylabel("Minutes")
    title = "Per-patient workflow durations"
    if site_label:
        title += f" – {site_label}"
    ax.set_title(title)

    ax.set_xticks(list(x_vals))
    ax.set_xticklabels(df["PtId"].tolist(), rotation=90, fontsize=6)

    ax.legend(fontsize=7, ncol=2, loc="upper right")
    fig.tight_layout()

    outfile = outdir / "per_patient_stacked_phases.png"
    fig.savefig(outfile, dpi=200)
    plt.close(fig)
    print(f"[PLOT] Saved stacked per-patient phases: {outfile}")


def plot_phase_boxplots(df: pd.DataFrame, outdir: Path, site_label: str | None):
    cols_present = [c for c in PHASE_COLS if c in df.columns]
    if not cols_present:
        return

    data = [df[c].dropna().values for c in cols_present]

    fig, ax = plt.subplots(figsize=(max(10, len(cols_present) * 0.8), 5))
    ax.boxplot(data, showfliers=True)

    ax.set_xticks(range(1, len(cols_present) + 1))
    ax.set_xticklabels(cols_present, rotation=45, ha="right")
    ax.set_ylabel("Minutes")

    title = "Phase duration distributions"
    if site_label:
        title += f" – {site_label}"
    ax.set_title(title)

    fig.tight_layout()
    outfile = outdir / "phase_duration_boxplots.png"
    fig.savefig(outfile, dpi=200)
    plt.close(fig)
    print(f"[PLOT] Saved phase boxplots: {outfile}")


def plot_histograms(df: pd.DataFrame, outdir: Path, site_label: str | None):
    hist_cols = []
    for candidate in ["Treating", "MRITotal", "ProcedureTotal"]:
        if candidate in df.columns:
            hist_cols.append(candidate)

    if not hist_cols:
        return

    for col in hist_cols:
        series = df[col].dropna()

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(series.values, bins=20)

        ax.set_xlabel("Minutes")
        ax.set_ylabel("Number of patients")

        title = f"{col} distribution"
        if site_label:
            title += f" – {site_label}"
        ax.set_title(title)

        fig.tight_layout()
        outfile = outdir / f"hist_{col}.png"
        fig.savefig(outfile, dpi=200)
        plt.close(fig)
        print(f"[PLOT] Saved histogram for {col}: {outfile}")


def plot_gantt_from_states(
    states_df: pd.DataFrame, outdir: Path, site_label: str | None, max_pts: int = 60
):
    """
    Gantt-style plot across patients.

    y-axis: PtId
    x-axis: minutes from first event in that case
    color: workflow state (CurrentState)
    """

    df = states_df.copy()

    # Keep only events that belong to a named workflow state and have positive duration
    df = df[df["CurrentState"].astype(str) != ""]
    df = df[df["duration_sec"] > 0]

    # Convert seconds to minutes
    df["start_min"] = df["start_sec"] / 60.0
    df["dur_min"] = df["duration_sec"] / 60.0

    # Limit number of patients to keep the figure readable
    pts = sorted(df["PtId"].unique())
    if len(pts) > max_pts:
        pts = pts[:max_pts]
        df = df[df["PtId"].isin(pts)]

    if not pts:
        print("[WARN] No patients available for Gantt plot.")
        return

    # Map PtId to y positions
    pt_to_y = {pt: ii for ii, pt in enumerate(pts)}

    # Order states for legend
    unique_states = list(df["CurrentState"].unique())
    ordered_states = [s for s in PHASE_COLS if s in unique_states]
    for s in unique_states:
        if s not in ordered_states:
            ordered_states.append(s)

    fig_height = max(6, 0.25 * len(pts))
    fig, ax = plt.subplots(figsize=(12, fig_height))

    # Draw bars by state to get grouped legend entries
    for state in ordered_states:
        sdf = df[df["CurrentState"] == state]
        if sdf.empty:
            continue

        # Suppress repeated legend entries
        first = True
        for _, row in sdf.iterrows():
            label = state if first else None
            first = False
            y_val = pt_to_y[row["PtId"]]
            ax.barh(
                y_val,
                row["dur_min"],
                left=row["start_min"],
                color=STATE_COLORS.get(state, "#cccccc"),
                edgecolor="none",
                label=label,
            )

    ax.set_yticks(range(len(pts)))
    ax.set_yticklabels(pts, fontsize=6)
    ax.set_xlabel("Minutes from first TULSA event")
    title = "Workflow timeline by patient"
    if site_label:
        title += f" – {site_label}"
    ax.set_title(title)

    ax.invert_yaxis()  # top patient at top
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    fig.tight_layout()

    outfile = outdir / "gantt_all_patients.png"
    fig.savefig(outfile, dpi=200)
    plt.close(fig)
    print(f"[PLOT] Saved Gantt-style timeline: {outfile}")


def main():
    args = parse_args()

    summary_path = Path(args.summary_csv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    site_label = args.site if args.site else summary_path.stem

    print(f"Reading timing summary: {summary_path}")
    df_summary = load_summary(summary_path)

    print("Generating summary plots...")
    plot_per_patient_stacked(df_summary, outdir, site_label)
    plot_phase_boxplots(df_summary, outdir, site_label)
    plot_histograms(df_summary, outdir, site_label)

    # Optional Gantt from states CSV
    if args.states_csv:
        states_path = Path(args.states_csv)
        if not states_path.exists():
            print(f"[WARN] States CSV not found for Gantt: {states_path}")
        else:
            print(f"Reading states CSV for Gantt: {states_path}")
            df_states = load_states(states_path)
            plot_gantt_from_states(df_states, outdir, site_label)

    print("Done.")


if __name__ == "__main__":
    main()
