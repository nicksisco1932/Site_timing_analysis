#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_gantt_plots.py

Create Gantt-style horizontal stacked bar plots of per-case workflow times
from a timing summary CSV (one row per PtId).

Expected input columns (some may be missing and will just be treated as 0):

    PtId
    TULSA QA
    Room ready
    Patient positioning & induction
    Device insertion
    Device repositioning
    Alignment
    Coarse
    Detailed
    Planning start angle
    Initialization
    Treating
    Paused
    Review
    Post–treatment scans & Device removal
    Patient recovery & transfer
    TotalMinutes

We enforce a fixed clinical stage order so colors and stacking match the
clinical workflow, regardless of column order in the CSV.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ------------------------ STAGE ORDER & COLORS ------------------------ #

STAGE_ORDER = [
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
    "Post–treatment scans & Device removal",
    "Patient recovery & transfer",
    "NA",
]

# Colors chosen to match your legend as closely as possible
STAGE_COLORS = {
    "TULSA QA":                          "#e0e0e0",  # light grey
    "Room ready":                        "#b0b0b0",  # medium grey
    "Patient positioning & induction":   "#777777",  # dark grey
    "Device insertion":                  "#9ccc65",  # light green
    "Device repositioning":              "#558b2f",  # darker green
    "Alignment":                         "#b3e5fc",  # light blue
    "Coarse":                            "#4169e1",  # royal blue
    "Detailed":                          "#1f3a93",  # deep blue
    "Planning start angle":              "#00008b",  # navy
    "Initialization":                    "#f4e19c",  # pale yellow
    "Treating":                          "#d99a00",  # warm gold
    "Paused":                            "#b8860b",  # darker gold
    "Review":                            "#8b6914",  # brownish gold
    "Post–treatment scans & Device removal": "#c8ffb0",  # light mint
    "Patient recovery & transfer":       "#7e6a8c",  # muted purple
    "NA":                                "#ffffff",  # white
}


# ------------------------------ HELPERS ------------------------------ #

def parse_args():
    p = argparse.ArgumentParser(
        description="Create Gantt-style plots from timing summary CSV."
    )
    p.add_argument(
        "--summary-csv",
        required=True,
        help="Path to timing summary CSV (e.g., timing_summary_Stanford_064.csv)",
    )
    p.add_argument(
        "--outdir",
        default=None,
        help="Output directory for PNGs. "
             "Default: sibling 'plots' folder next to summary CSV.",
    )
    p.add_argument(
        "--segments",
        action="store_true",
        help="Also create early/mid/late segment Gantts: 1–50, 51–75, 76+.",
    )
    return p.parse_args()


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure required baseline columns exist. Missing stage columns are created
    and filled with 0 so plotting logic is robust.
    """
    if "PtId" not in df.columns:
        raise ValueError("Expected 'PtId' column in timing summary CSV.")

    # Create 1-based patient index if not present
    if "Pt" not in df.columns:
        df = df.copy()
        df.insert(0, "Pt", np.arange(1, len(df) + 1))

    # Add missing stage columns as zeros
    for stage in STAGE_ORDER:
        if stage in ("NA",):  # 'NA' is not an actual column in summary
            continue
        if stage not in df.columns:
            df[stage] = 0.0

    return df


def melt_for_gantt(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert wide timing summary into a long-format dataframe suitable
    for Gantt plotting: one row per (Pt, stage) with start and duration.
    """
    records = []

    # Only stages that correspond to columns (exclude 'NA' pseudo-stage)
    # Only include stages actually in the timing summary
    plot_stages = [s for s in STAGE_ORDER if s in df.columns]


    for _, row in df.iterrows():
        pt_idx = int(row["Pt"])
        ptid = row["PtId"]
        t0 = 0.0

        for stage in plot_stages:
            dur = float(row.get(stage, 0.0) or 0.0)
            if dur <= 0:
                continue

            records.append(
                {
                    "Pt": pt_idx,
                    "PtId": ptid,
                    "stage": stage,
                    "start": t0,
                    "duration": dur,
                }
            )
            t0 += dur

    return pd.DataFrame.from_records(records)


def plot_gantt(df_slice: pd.DataFrame, title_suffix: str, out_png: Path):
    """
    Create a Gantt-style horizontal stacked bar plot for a slice of patients.
    df_slice must already have Pt (1-based) and PtId columns.
    """
    if df_slice.empty:
        print(f"[WARN] No rows for {title_suffix}, skipping Gantt.")
        return

    long_df = melt_for_gantt(df_slice)
    if long_df.empty:
        print(f"[WARN] No non-zero durations for {title_suffix}, skipping Gantt.")
        return

    # Sort by Pt index for plotting order
    long_df = long_df.sort_values(["Pt", "start"])
    pts = sorted(long_df["Pt"].unique())
    ptid_map = (
        df_slice.set_index("Pt")["PtId"].to_dict()
    )  # Pt index -> PtId label

    fig, ax = plt.subplots(figsize=(14, max(4, len(pts) * 0.15)))

    for pt in pts:
        sub = long_df[long_df["Pt"] == pt]
        y = pt  # use Pt index as the y position

        for _, r in sub.iterrows():
            stage = r["stage"]
            color = STAGE_COLORS.get(stage, "#cccccc")
            ax.barh(
                y=y,
                width=r["duration"],
                left=r["start"],
                color=color,
                edgecolor="none",
            )

    # Y-axis labels as PtId
    ax.set_yticks(pts)
    ax.set_yticklabels([ptid_map[p] for p in pts])
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Case (PtId)")
    ax.set_title(f"TULSA workflow per case {title_suffix}")

    # Legend in fixed clinical order
    handles = []
    labels = []
    plotted_stages = sorted(long_df["stage"].unique(),
                            key=lambda s: STAGE_ORDER.index(s))

    for stage in plotted_stages:
        color = STAGE_COLORS.get(stage, "#cccccc")
        h = ax.barh(y=-1, width=0, left=0, color=color)  # dummy
        handles.append(h[0])
        labels.append(stage)

    ax.legend(
        handles,
        labels,
        title="Workflow state",
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
        borderaxespad=0.0,
    )

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=200)
    plt.close(fig)
    print(f"Saved Gantt: {out_png}")


# ------------------------------- MAIN ------------------------------- #

def main():
    args = parse_args()

    summary_path = Path(args.summary_csv)
    if not summary_path.exists():
        raise FileNotFoundError(f"Timing summary not found: {summary_path}")

    print("Reading timing summary:")
    print(f"  {summary_path}")
    df = pd.read_csv(summary_path)
    df = ensure_columns(df)

    # Determine default outdir (…/plots) if not provided
    if args.outdir is None:
        outdir = summary_path.parent / "plots"
    else:
        outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # ---------------------- All cases Gantt ---------------------- #
    plot_gantt(df, "(all cases)",
               outdir / "gantt_all_cases.png")

    # ------------------- Optional segmented Gantts ------------------- #
    if args.segments:
        n = len(df)
        print(f"Total cases: {n}")

        # Early: 1–50
        early = df[(df["Pt"] >= 1) & (df["Pt"] <= 50)]
        plot_gantt(early, "(cases 1–50)",
                   outdir / "gantt_cases_001_050.png")

        # Mid: 51–75
        mid = df[(df["Pt"] >= 51) & (df["Pt"] <= 75)]
        plot_gantt(mid, "(cases 51–75)",
                   outdir / "gantt_cases_051_075.png")

        # Late: 76+
        late = df[df["Pt"] >= 76]
        plot_gantt(late, "(cases 76+)",
                   outdir / "gantt_cases_076_plus.png")


if __name__ == "__main__":
    main()
