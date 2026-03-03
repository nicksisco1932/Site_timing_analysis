#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_state_histograms.py  (v0.1)
---------------------------------
Create histograms of per-case durations for each workflow state
using timing_summary_<site>.csv.

Input:
    timing_summary_<site>.csv  (from tulsa_build_timing_summary.py)

Output (in plots/ under analysis root):
    site_<site>_hist_<phase>.png
"""

import argparse
from pathlib import Path
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from .tulsa_workflow import PLOTTED_STATES


# ------------------------ Helpers ------------------------ #

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_phase_columns(df: pd.DataFrame):
    """
    Infer phase columns from known names.
    Adjust here if you add/remove columns in timing_summary.
    """
    candidate_cols = [
        *PLOTTED_STATES,
        "MRITotal",
        "ProcedureTotal",
        "TotalMinutes",
    ]
    return [c for c in candidate_cols if c in df.columns]


def coerce_numeric_with_cap(series: pd.Series,
                            max_minutes: float | None = None) -> pd.Series:
    """
    Convert to numeric; optionally treat any values > max_minutes as NaN.
    """
    s = pd.to_numeric(series, errors="coerce")
    if max_minutes is not None:
        mask_bad = s > max_minutes
        if mask_bad.any():
            n_bad = int(mask_bad.sum())
            print(f"  [INFO] {series.name}: {n_bad} values > {max_minutes} min "
                  f"set to NaN (likely DB artifacts).")
            s[mask_bad] = np.nan
    return s


def safe_name(name: str) -> str:
    """
    Turn a phase name like 'Post-treatment scans & Device removal'
    into 'Post_treatment_scans_Device_removal' for filenames.
    """
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^0-9A-Za-z_]", "", name)
    return name


# ------------------------ Main logic ------------------------ #

def build_histograms(summary_path: Path,
                     site: str,
                     outdir: Path,
                     max_minutes: float = 1000.0,
                     bins: int = 20):
    print(f"Reading timing summary: {summary_path}")
    df = pd.read_csv(summary_path)

    ensure_dir(outdir)

    phases = get_phase_columns(df)
    if not phases:
        raise RuntimeError("No recognizable phase columns found in timing summary.")

    print(f"Found phase columns: {phases}")

    for phase in phases:
        series = df[phase]
        series_num = coerce_numeric_with_cap(series, max_minutes=max_minutes)
        series_num = series_num.dropna()
        series_num = series_num[series_num > 0]  # drop zeros (no time in that phase)

        if series_num.empty:
            print(f"  [WARN] No valid data for {phase}, skipping histogram.")
            continue

        safe_phase = safe_name(phase)
        outpath = outdir / f"site_{site}_hist_{safe_phase}.png"

        plt.figure(figsize=(8, 5))
        plt.hist(series_num.values, bins=bins, edgecolor="black", alpha=0.7)
        plt.title(f"{site}: {phase} duration distribution")
        plt.xlabel("Duration (minutes)")
        plt.ylabel("Number of cases")
        plt.grid(True, axis="y", linestyle="--", alpha=0.4)
        plt.tight_layout()
        plt.savefig(outpath, dpi=200)
        plt.close()

        print(f"  Saved histogram for {phase}: {outpath}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create per-state duration histograms from timing_summary_<site>.csv"
    )
    parser.add_argument(
        "--site",
        required=True,
        help="Site name, e.g. Stanford_064",
    )
    parser.add_argument(
        "--analysis-root",
        required=True,
        help="Directory containing timing_summary_<site>.csv",
    )
    parser.add_argument(
        "--summary-file",
        default=None,
        help="Optional override for timing summary filename.",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=1000.0,
        help="Values above this are treated as NaN (DB artifacts).",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=20,
        help="Number of histogram bins.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    site = args.site
    analysis_root = Path(args.analysis_root)

    if args.summary_file is not None:
        summary_path = analysis_root / args.summary_file
    else:
        summary_path = analysis_root / f"timing_summary_{site}.csv"

    if not summary_path.exists():
        raise FileNotFoundError(f"Timing summary file not found: {summary_path}")

    plots_dir = analysis_root / "plots"
    build_histograms(summary_path, site, plots_dir,
                     max_minutes=args.max_minutes,
                     bins=args.bins)
    print("Done generating histograms.")


if __name__ == "__main__":
    main()
