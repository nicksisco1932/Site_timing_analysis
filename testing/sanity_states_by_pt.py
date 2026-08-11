#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Project: Site Timing Analysis
# File: testing/sanity_states_by_pt.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Provides a development/testing utility for sanity states by pt analysis.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

import argparse
from pathlib import Path

import pandas as pd


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--states-csv", required=True,
                   help="Path to auditlogs_<site>_states.csv")
    p.add_argument("--ptid", required=True,
                   help="PtId to inspect, e.g. 064_01-076")
    return p.parse_args()


def pick_column(df, candidates, label):
    """
    Try to pick the first existing column from a list of candidates.
    If none found, print available columns and exit.
    """
    for col in candidates:
        if col in df.columns:
            return col
    print(f"[ERROR] Could not find a {label} column. Tried: {candidates}")
    print("Available columns:")
    print(df.columns.tolist())
    raise SystemExit(1)


def main():
    args = parse_args()
    states_path = Path(args.states_csv)

    df = pd.read_csv(states_path)

    # --- PtId column ---
    ptid_col = pick_column(
        df,
        candidates=["PtId", "PtID", "ptid", "PatientId", "patient_id"],
        label="PtId"
    )

    # --- State / workflow label column ---
    state_col = pick_column(
        df,
        candidates=["workflow_state", "state", "State", "phase", "Phase", "CurrentState"],
        label="workflow_state/state"
    )

    # --- Duration column ---
    duration_col = pick_column(
        df,
        candidates=["duration_sec", "Duration_sec", "duration", "Duration"],
        label="duration"
    )

    df_pt = df[df[ptid_col] == args.ptid].copy()
    if df_pt.empty:
        print(f"No rows for {ptid_col} == {args.ptid}")
        return

    print(f"Rows for {ptid_col} == {args.ptid}: {len(df_pt)}")
    print(f"Using state column: {state_col}")
    print(f"Using duration column: {duration_col}")

    # Sum durations per state, convert seconds -> minutes
    summary = (
        df_pt.groupby(state_col)[duration_col]
        .sum()
        .sort_values(ascending=False)
        / 60.0
    )

    print(f"\nTotal minutes per {state_col} for this PtId:")
    print(summary.to_string(float_format=lambda x: f"{x:0.3f}"))

    treating_min = summary.get("Treating", 0.0)
    print(f"\nTreating total (min) if a 'Treating' state exists: {treating_min:0.3f}")


if __name__ == "__main__":
    main()
