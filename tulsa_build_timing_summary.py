#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_build_timing_summary.py  (v0.2)
------------------------------------
Builds per-patient timing summaries from the state-enriched auditlog CSV.

Input:
    auditlogs_<site>_states.csv  (from tulsa_state_machine.py)

Output:
    timing_summary_<site>.csv

Author:
    N. J. Sisco
"""

import argparse
from pathlib import Path

import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build per-patient timing summary from state-enriched auditlog file."
    )

    parser.add_argument(
        "--states-csv",
        required=True,
        help="Path to auditlogs_<site>_states.csv",
    )

    parser.add_argument(
        "--outdir",
        required=True,
        help="Where timing_summary_<site>.csv should be written",
    )

    parser.add_argument(
        "--filter-outliers",
        action="store_true",
        help="Remove rows with duration_sec > 6 hours (21600 sec)",
    )

    return parser.parse_args()


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a dataframe:

        Pt, PtId, <each state>, MRITotal, ProcedureTotal, TotalMinutes

    Notes
    -----
    - Uses Pt if available (from tulsa_collect_auditlogs.py), otherwise just PtId.
    - Aggregates duration_sec per Pt / PtId / CurrentState (minutes).
    - MRITotal and ProcedureTotal mirror the logic in tulsa_case_summary.py.
    """

    required_cols = {"PtId", "CurrentState", "duration_sec"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Input dataframe is missing required columns: {missing}")

    # Keep only rows with a state
    df = df[df["CurrentState"] != ""].copy()

    # Convert duration to minutes
    df["minutes"] = df["duration_sec"] / 60.0

    # Group by Pt (if present) + PtId + CurrentState
    if "Pt" in df.columns:
        group_cols = ["Pt", "PtId", "CurrentState"]
    else:
        group_cols = ["PtId", "CurrentState"]

    agg = (
        df.groupby(group_cols, dropna=False)["minutes"]
          .sum()
          .reset_index()
    )

    # Pivot: rows = Pt/PtId, columns = CurrentState
    pivot_index = ["PtId"]
    if "Pt" in agg.columns:
        pivot_index.insert(0, "Pt")

    summary = agg.pivot_table(
        index=pivot_index,
        columns="CurrentState",
        values="minutes",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # Flatten possible MultiIndex columns
    summary.columns = [
        c if isinstance(c, str) else c[1] for c in summary.columns
    ]

    cols = summary.columns

    def has(name: str) -> bool:
        return name in cols

    # Intra-MRI components (aligned with tulsa_case_summary.py)
    mri_components = [
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
    ]
    mri_components = [c for c in mri_components if has(c)]
    if mri_components:
        summary["MRITotal"] = summary[mri_components].sum(axis=1)

    # ProcedureTotal: TULSA QA + Room ready + all intra-MRI pieces
    procedure_components = ["TULSA QA", "Room ready"] + mri_components
    procedure_components = [c for c in procedure_components if has(c)]
    if procedure_components:
        summary["ProcedureTotal"] = summary[procedure_components].sum(axis=1)

    # TotalMinutes = sum of *state columns only* (no derived totals)
    non_state_cols = {"Pt", "PtId", "MRITotal", "ProcedureTotal"}
    state_cols = [c for c in summary.columns if c not in non_state_cols]
    summary["TotalMinutes"] = summary[state_cols].sum(axis=1)

    return summary


def main():
    args = parse_args()

    states_csv = Path(args.states_csv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Reading states CSV:\n  {states_csv}")
    df = pd.read_csv(states_csv)

    if args.filter_outliers:
        before = len(df)
        df = df[df["duration_sec"] < 21600]  # 6 hours
        after = len(df)
        print(f"Filtered outliers: removed {before - after} rows > 6 hours")

    print("Building timing summary...")
    summary = build_summary(df)

    # Extract site from filename
    stem = states_csv.stem  # auditlogs_Stanford_064_states
    site = stem.replace("auditlogs_", "").replace("_states", "")

    outfile = outdir / f"timing_summary_{site}.csv"
    summary.to_csv(outfile, index=False)

    print(f"\nSaved timing summary to:\n  {outfile}")
    print(f"Rows (patients): {len(summary)}")


if __name__ == "__main__":
    main()
