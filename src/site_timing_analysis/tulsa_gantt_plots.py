#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_gantt_plots.py

Create Gantt-style horizontal stacked bar plots from timing_summary CSVs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .tulsa_workflow import STATE_COLORS, STATE_ORDER


STAGE_ORDER = STATE_ORDER
STAGE_COLORS = STATE_COLORS


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
        help="Output directory for PNGs. Default: sibling 'plots' folder next to summary CSV.",
    )
    p.add_argument(
        "--segments",
        action="store_true",
        help="Also create early/mid/late segment Gantts: 1-50, 51-75, 76+.",
    )
    return p.parse_args()


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "PtId" not in df.columns:
        raise ValueError("Expected 'PtId' column in timing summary CSV.")

    if "Pt" not in df.columns:
        df = df.copy()
        df.insert(0, "Pt", np.arange(1, len(df) + 1))

    for stage in STAGE_ORDER:
        if stage == "NA":
            continue
        if stage not in df.columns:
            df[stage] = 0.0

    return df


def melt_for_gantt(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    plot_stages = [stage for stage in STAGE_ORDER if stage in df.columns and stage != "NA"]

    for _, row in df.iterrows():
        pt_idx = int(row["Pt"])
        ptid = row["PtId"]
        start = 0.0

        for stage in plot_stages:
            dur = float(row.get(stage, 0.0) or 0.0)
            if dur <= 0:
                continue

            records.append(
                {
                    "Pt": pt_idx,
                    "PtId": ptid,
                    "stage": stage,
                    "start": start,
                    "duration": dur,
                }
            )
            start += dur

    return pd.DataFrame.from_records(records)


def plot_gantt(df_slice: pd.DataFrame, title_suffix: str, out_png: Path):
    if df_slice.empty:
        print(f"[WARN] No rows for {title_suffix}, skipping Gantt.")
        return

    long_df = melt_for_gantt(df_slice)
    if long_df.empty:
        print(f"[WARN] No non-zero durations for {title_suffix}, skipping Gantt.")
        return

    long_df = long_df.sort_values(["Pt", "start"])
    pts = sorted(long_df["Pt"].unique())
    ptid_map = df_slice.set_index("Pt")["PtId"].to_dict()

    fig, ax = plt.subplots(figsize=(14, max(4, len(pts) * 0.15)))

    for pt in pts:
        sub = long_df[long_df["Pt"] == pt]
        for _, row in sub.iterrows():
            stage = row["stage"]
            ax.barh(
                y=pt,
                width=row["duration"],
                left=row["start"],
                color=STAGE_COLORS.get(stage, "#cccccc"),
                edgecolor="none",
            )

    ax.set_yticks(pts)
    ax.set_yticklabels([ptid_map[p] for p in pts])
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Case (PtId)")
    ax.set_title(f"TULSA workflow per case {title_suffix}")

    handles = []
    labels = []
    plotted_stages = sorted(long_df["stage"].unique(), key=lambda s: STAGE_ORDER.index(s))
    for stage in plotted_stages:
        handle = ax.barh(y=-1, width=0, left=0, color=STAGE_COLORS.get(stage, "#cccccc"))
        handles.append(handle[0])
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


def main():
    args = parse_args()

    summary_path = Path(args.summary_csv)
    if not summary_path.exists():
        raise FileNotFoundError(f"Timing summary not found: {summary_path}")

    print("Reading timing summary:")
    print(f"  {summary_path}")
    df = pd.read_csv(summary_path)
    df = ensure_columns(df)

    outdir = summary_path.parent / "plots" if args.outdir is None else Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    plot_gantt(df, "(all cases)", outdir / "gantt_all_cases.png")

    if args.segments:
        early = df[(df["Pt"] >= 1) & (df["Pt"] <= 50)]
        plot_gantt(early, "(cases 1-50)", outdir / "gantt_cases_001_050.png")

        mid = df[(df["Pt"] >= 51) & (df["Pt"] <= 75)]
        plot_gantt(mid, "(cases 51-75)", outdir / "gantt_cases_051_075.png")

        late = df[df["Pt"] >= 76]
        plot_gantt(late, "(cases 76+)", outdir / "gantt_cases_076_plus.png")


if __name__ == "__main__":
    main()
