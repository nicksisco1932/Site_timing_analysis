#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tulsa_case_summary.py  (v0.1)

Summarize per-case durations by workflow state.

Input:
    auditlogs_<site>_states.csv  (from tulsa_state_machine.py)

Output:
    timing_summary_<site>.csv in --outdir
"""

# Project: Site Timing Analysis
# File: testing/tulsa_case_summary.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Provides a development/testing utility for TULSA case summary analysis.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

import argparse
from pathlib import Path

import pandas as pd


# --------------------------- CLI HELPERS --------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Summarize per-case durations by workflow state."
    )

    parser.add_argument(
        "--infile",
        required=True,
        help="Input CSV with CurrentState, start_sec, duration_sec.",
    )

    parser.add_argument(
        "--outdir",
        required=True,
        help="Directory where timing summary CSV will be written.",
    )

    return parser.parse_args()


# ------------------------ SUMMARY LOGIC ---------------------------- #

def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate duration_sec per PtId and CurrentState, then pivot wide.

    Durations are converted to minutes.
    """

    required_cols = {"PtId", "duration_sec", "CurrentState"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Input dataframe is missing required columns: {missing}")

    # Filter to rows with a defined state and positive duration
    mask_valid = (df["CurrentState"] != "") & (df["duration_sec"] > 0)
    df_valid = df[mask_valid].copy()

    # Group by PtId, Pt, CurrentState
    group_cols = []
    if "Pt" in df_valid.columns:
        group_cols = ["Pt", "PtId", "CurrentState"]
    else:
        group_cols = ["PtId", "CurrentState"]

    agg = (
        df_valid.groupby(group_cols, dropna=False)["duration_sec"]
        .sum()
        .reset_index()
    )

    # Convert to minutes
    agg["duration_min"] = agg["duration_sec"] / 60.0

    # Pivot wide: one row per PtId, columns per CurrentState
    pivot_index = ["PtId"]
    if "Pt" in agg.columns:
        pivot_index.insert(0, "Pt")

    timing_wide = agg.pivot_table(
        index=pivot_index,
        columns="CurrentState",
        values="duration_min",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # Flatten column MultiIndex if needed
    timing_wide.columns = [
        c if isinstance(c, str) else c[1] for c in timing_wide.columns
    ]

    # Try to reconstruct high-level groupings similar to the R script
    cols = timing_wide.columns

    def has(col_name: str) -> bool:
        return col_name in cols

    # MRITotal: intra-MRI phases (approximation)
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
        timing_wide["MRITotal"] = timing_wide[mri_components].sum(axis=1)

    # ProcedureTotal: TULSA QA + all intra-MRI stages
    procedure_components = ["TULSA QA", "Room ready"] + mri_components
    procedure_components = [c for c in procedure_components if has(c)]
    if procedure_components:
        timing_wide["ProcedureTotal"] = timing_wide[procedure_components].sum(axis=1)

    return timing_wide


# ------------------------------- MAIN ------------------------------- #

def main():
    args = parse_args()

    infile = Path(args.infile)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not infile.exists():
        raise FileNotFoundError(f"Input file not found: {infile}")

    print(f"Reading: {infile}")
    df = pd.read_csv(infile)

    print("Building timing summary...")
    timing_summary = build_summary(df)

    # Infer site from filename
    site = "site"
    stem = infile.stem  # e.g., auditlogs_Stanford_064_states
    if stem.startswith("auditlogs_") and stem.endswith("_states"):
        site = stem.replace("auditlogs_", "").replace("_states", "")

    outfile = outdir / f"timing_summary_{site}.csv"
    timing_summary.to_csv(outfile, index=False)

    print(f"Saved timing summary to: {outfile}")
    print(f"Rows (patients): {len(timing_summary)}")


if __name__ == "__main__":
    main()
