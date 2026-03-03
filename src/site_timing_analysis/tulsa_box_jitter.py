#!/usr/bin/env python
"""
tulsa_box_jitter.py

Create a box + jitter plot of per-phase timings from a timing_summary_*.csv file.

Example:
    python tulsa_box_jitter.py \
        --summary-csv "C:\\path\\to\\timing_summary_Stanford_064.csv" \
        --outdir "C:\\path\\to\\figures"
"""

import os
import argparse

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from .tulsa_workflow import PLOTTED_STATES, STATE_COLORS as SHARED_STATE_COLORS

# -------------------------------------------------------------------------
# Shared theme: phase order and colors
# -------------------------------------------------------------------------

# Ordered to match the conceptual TULSA workflow.
PHASE_ORDER = PLOTTED_STATES

# Color theme – consistent across figures.
# If your Gantt script already has a PHASE_COLORS dict, you can copy these
# there as well so everything matches visually.
PHASE_COLORS = SHARED_STATE_COLORS

# Matplotlib theming to keep figures consistent and readable.
plt.rcParams.update({
    "figure.figsize": (12, 6),
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "axes.grid": True,
    "grid.linestyle": "--",
    "grid.alpha": 0.35,
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "axes.spines.top": False,
    "axes.spines.right": False,
})


# -------------------------------------------------------------------------
# Core plotting function
# -------------------------------------------------------------------------


def make_box_jitter_plot(summary_csv: str,
                         out_png: str,
                         title: str | None = None,
                         dpi: int = 300) -> None:
    """
    Creates a box + jitter plot of phase durations across cases.

    Parameters
    ----------
    summary_csv : str
        Path to timing_summary_*.csv, e.g., timing_summary_Stanford_064.csv.
        Must contain columns:
            PtId, Alignment, Coarse, Detailed, Paused,
            Planning start angle,
            Post-treatment scans & Device removal,
            Review, Room ready, TULSA QA, Treating, TotalMinutes
    out_png : str
        Output filename (full path) for the saved PNG figure.
    title : str or None
        Optional plot title. If None, a default is used.
    dpi : int
        Resolution of the saved figure.
    """

    # ---- Load data
    df = pd.read_csv(summary_csv)

    if "PtId" not in df.columns:
        raise ValueError("Expected 'PtId' column in timing summary file.")

    # Determine which columns are phases: everything except PtId + TotalMinutes.
    phase_cols = [c for c in df.columns if c not in ("PtId", "TotalMinutes")]

    # Restrict to PHASE_ORDER but keep only phases actually present in the file.
    phases = [p for p in PHASE_ORDER if p in phase_cols]
    if not phases:
        raise ValueError(
            "No recognized phase columns found. "
            f"Found columns: {list(df.columns)}"
        )

    # Melt wide → long to make it easier to filter and handle.
    long_df = df.melt(
        id_vars="PtId",
        value_vars=phases,
        var_name="Phase",
        value_name="Minutes",
    )

    # Construct list-of-arrays for the boxplot backend.
    data_by_phase = []
    for phase in phases:
        vals = long_df.loc[long_df["Phase"] == phase, "Minutes"].dropna().values
        data_by_phase.append(vals)

    # ---- Plot
    fig, ax = plt.subplots()

    positions = np.arange(1, len(phases) + 1)

    # Boxplot base
    bp = ax.boxplot(
        data_by_phase,
        positions=positions,
        widths=0.55,
        patch_artist=True,
        showmeans=False,
        showfliers=False,  # swarm handles extremes nicely
        medianprops=dict(linewidth=1.4, color="black"),
    )

    # Color boxes to match PHASE_COLORS
    for ii, box in enumerate(bp["boxes"]):
        phase = phases[ii]
        color = PHASE_COLORS.get(phase, "#B0B0B0")  # fallback gray
        box.set_facecolor(color)
        box.set_alpha(0.7)
        box.set_edgecolor("black")
        box.set_linewidth(1.0)

    # Whiskers & caps style
    for key in ("whiskers", "caps"):
        for line in bp[key]:
            line.set_color("black")
            line.set_linewidth(1.0)

    # Jittered points (swarm)
    rng = np.random.default_rng(seed=42)  # deterministic jitter
    for ii, phase in enumerate(phases):
        vals = data_by_phase[ii]
        if len(vals) == 0:
            continue

        x_center = positions[ii]
        x_jitter = rng.normal(loc=x_center, scale=0.07, size=len(vals))

        ax.scatter(
            x_jitter,
            vals,
            s=25,
            alpha=0.8,
            edgecolors="black",
            linewidths=0.4,
            zorder=3,
        )

    # ---- Axes and labels
    ax.set_xticks(positions)
    ax.set_xticklabels(phases, rotation=40, ha="right")
    ax.set_ylabel("Duration (minutes)")

    if title is None:
        title = "Per-phase timing distribution across cases"
    ax.set_title(title)

    # Ensure grid is behind the points
    ax.set_axisbelow(True)

    # Reasonable y-limit padding
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(bottom=0, top=ymax * 1.05)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, dpi=dpi)
    plt.close(fig)


# -------------------------------------------------------------------------
# CLI plumbing
# -------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create box + jitter plots from TULSA timing summary CSV."
    )
    parser.add_argument(
        "--summary-csv",
        required=True,
        help="Path to timing_summary_*.csv file.",
    )
    parser.add_argument(
        "--outdir",
        default=".",
        help="Output directory for the figure PNG.",
    )
    parser.add_argument(
        "--basename",
        default="timing_boxjitter",
        help="Base filename (without extension) for the figure.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional custom plot title.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Figure resolution (DPI). Default 300.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    out_png = os.path.join(args.outdir, f"{args.basename}.png")

    make_box_jitter_plot(
        summary_csv=args.summary_csv,
        out_png=out_png,
        title=args.title,
        dpi=args.dpi,
    )


if __name__ == "__main__":
    main()
