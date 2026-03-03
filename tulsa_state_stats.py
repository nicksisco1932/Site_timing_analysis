#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_state_stats.py  (v0.1)
----------------------------
Compute per-state summary statistics from timing_summary_<site>.csv.

Input:
    timing_summary_<site>.csv  (from tulsa_build_timing_summary.py)

Output (in analysis dir):
    state_stats_<site>.csv

Columns:
    State, N, MeanMinutes, MedianMinutes, StdMinutes
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def get_phase_columns(df: pd.DataFrame):
    """
    Infer phase columns from known names.
    Adjust here if you add/remove columns in timing_summary.
    """
    candidate_cols = [
        "Alignment",
        "Coarse",
        "Detailed",
        "Initialization",
        "Paused",
        "Planning start angle",
        "Post-treatment scans & Device removal",
        "Review",
        "Room ready",
        "TULSA QA",
        "Treating",
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


def build_state_stats(summary_path: Path,
                      site: str,
                      max_minutes: float = 1000.0) -> pd.DataFrame:
    """
    Compute N, mean, median, std (minutes) for each phase/state column.
    """
    print(f"Reading timing summary: {summary_path}")
    df = pd.read_csv(summary_path)

    phases = get_phase_columns(df)
    if not phases:
        raise RuntimeError("No recognizable phase columns found in timing summary.")

    print(f"Found phase columns: {phases}")

    rows = []
    for phase in phases:
        series = df[phase]
        series_num = coerce_numeric_with_cap(series, max_minutes=max_minutes)
        # Drop NaNs and zeros (no time in that phase)
        series_num = series_num.dropna()
        series_num = series_num[series_num > 0]

        n = int(series_num.shape[0])
        if n == 0:
            print(f"  [WARN] No valid data for {phase}, skipping stats.")
            continue

        mean_val = float(series_num.mean())
        median_val = float(series_num.median())
        std_val = float(series_num.std(ddof=1)) if n > 1 else float("nan")

        rows.append(
            {
                "State": phase,
                "N": n,
                "MeanMinutes": mean_val,
                "MedianMinutes": median_val,
                "StdMinutes": std_val,
            }
        )

    stats_df = pd.DataFrame(rows).sort_values("State").reset_index(drop=True)
    return stats_df


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compute per-state summary statistics from timing_summary_<site>.csv"
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

    stats_df = build_state_stats(summary_path, site, max_minutes=args.max_minutes)

    outfile = analysis_root / f"state_stats_{site}.csv"
    stats_df.to_csv(outfile, index=False)

    print(f"\nSaved per-state stats to:\n  {outfile}")
    print(f"States summarized: {len(stats_df)}")


if __name__ == "__main__":
    main()
