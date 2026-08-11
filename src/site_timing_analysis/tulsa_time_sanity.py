#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tulsa_time_sanity.py  (v0.3)
----------------------------
Stand-alone, per-site time integrity check.

Input:
    auditlogs_<site>_states.csv  (from tulsa_state_machine.py)

Output:
    time_sanity_<site>.csv

For each PtId, reports:
    LOG-LEVEL (all events for that PtId, including housekeeping):
        - n_events
        - first_ts, last_ts
        - duration_min
        - any_after_noon
        - crossed_noon
        - has_non_monotonic
        - max_backward_sec
        - multi_day_log  (log events span multiple calendar days)

    PROCEDURAL (only rows with non-empty CurrentState, if available):
        - proc_first_ts, proc_last_ts
        - proc_duration_min
        - proc_any_after_noon
        - proc_crossed_noon
        - proc_multi_day

Changes in v0.3
---------------
- Distinguish between log-window multi-day (multi_day_log) and
  procedural multi-day (proc_multi_day).
- Procedural metrics use only rows with CurrentState != "" when that
  column is present; otherwise they are left NaN/False.
"""

# Project: Site Timing Analysis
# File: src/site_timing_analysis/tulsa_time_sanity.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Implements the legacy-compatible TULSA time sanity workflow script.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

import argparse
from pathlib import Path
from datetime import time

import pandas as pd

from .tulsa_timebase import parse_time_column


def parse_args():
    p = argparse.ArgumentParser(
        description="Per-site time sanity check for auditlogs_<site>_states.csv"
    )
    p.add_argument(
        "--states-csv",
        required=True,
        help="Path to auditlogs_<site>_states.csv (from tulsa_state_machine.py)",
    )
    p.add_argument(
        "--outdir",
        required=True,
        help="Directory where time_sanity_<site>.csv will be written.",
    )
    p.add_argument(
        "--tz",
        default=None,
        help=(
            "Optional timezone (e.g., 'America/Los_Angeles'). If provided and the "
            "states CSV does not already contain a 'ts' column, TimeStamp is "
            "interpreted as local time in this TZ."
        ),
    )
    return p.parse_args()


def build_time_sanity(df: pd.DataFrame, tz: str | None = None) -> pd.DataFrame:
    """Compute per-PtId time-integrity metrics.

    Expected columns in df:
        - PtId
        - TimeStamp  (ISO-like local datetime string)
    Optionally:
        - CurrentState  (used to define procedural window)
    """

    required_cols = ["PtId", "TimeStamp"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in states CSV: {missing}")

    # Canonical timestamp parsing
    df = parse_time_column(
        df,
        source_col="TimeStamp",
        target_col="ts",
        tz=tz,
        drop_bad=True,
        verbose=True,
    )

    if df.empty:
        raise ValueError("No valid timestamps after parsing TimeStamp.")

    has_state = "CurrentState" in df.columns
    noon_t = time(12, 0, 0)

    records = []

    for ptid, g_all in df.groupby("PtId"):
        g_all = g_all.sort_values("ts")
        n_events = len(g_all)

        first_ts = g_all["ts"].iloc[0]
        last_ts = g_all["ts"].iloc[-1]
        duration_min = (last_ts - first_ts).total_seconds() / 60.0

        # Log-window noon flags
        any_after_noon = (g_all["ts"].dt.time >= noon_t).any()
        crossed_noon = (first_ts.time() < noon_t) and (last_ts.time() >= noon_t)

        # Monotonicity: look at diffs within PtId
        diffs = g_all["ts"].diff().dropna()
        backwards = diffs[diffs < pd.Timedelta(0)]
        has_non_monotonic = not backwards.empty
        if has_non_monotonic:
            max_backward = backwards.min()  # most negative timedelta
            max_backward_sec = max_backward.total_seconds()
        else:
            max_backward_sec = 0.0

        # Log-window multi-day indicator
        multi_day_log = first_ts.date() != last_ts.date()

        # ---------------- Procedural window (CurrentState != "") ----------------
        proc_first_ts = pd.NaT
        proc_last_ts = pd.NaT
        proc_duration_min = float("nan")
        proc_any_after_noon = False
        proc_crossed_noon = False
        proc_multi_day = False

        if has_state:
            g_proc = g_all[g_all["CurrentState"].astype(str) != ""].copy()
            if not g_proc.empty:
                g_proc = g_proc.sort_values("ts")
                proc_first_ts = g_proc["ts"].iloc[0]
                proc_last_ts = g_proc["ts"].iloc[-1]
                proc_duration_min = (
                    (proc_last_ts - proc_first_ts).total_seconds() / 60.0
                )

                proc_any_after_noon = (g_proc["ts"].dt.time >= noon_t).any()
                proc_crossed_noon = (
                    proc_first_ts.time() < noon_t
                    and proc_last_ts.time() >= noon_t
                )
                proc_multi_day = proc_first_ts.date() != proc_last_ts.date()

        records.append(
            {
                "PtId": ptid,
                # LOG-WINDOW METRICS
                "n_events": n_events,
                "first_ts": first_ts,
                "last_ts": last_ts,
                "duration_min": duration_min,
                "any_after_noon": bool(any_after_noon),
                "crossed_noon": bool(crossed_noon),
                "has_non_monotonic": bool(has_non_monotonic),
                "max_backward_sec": max_backward_sec,
                "multi_day_log": bool(multi_day_log),
                # PROCEDURAL METRICS
                "proc_first_ts": proc_first_ts,
                "proc_last_ts": proc_last_ts,
                "proc_duration_min": proc_duration_min,
                "proc_any_after_noon": bool(proc_any_after_noon),
                "proc_crossed_noon": bool(proc_crossed_noon),
                "proc_multi_day": bool(proc_multi_day),
            }
        )

    out = pd.DataFrame.from_records(records)

    # Sort for readability: by PtId, then first_ts
    out = out.sort_values(["PtId", "first_ts"]).reset_index(drop=True)

    return out


def main():
    args = parse_args()

    states_path = Path(args.states_csb) if hasattr(args, "states_csb") else Path(args.states_csv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not states_path.exists():
        raise FileNotFoundError(f"States CSV not found: {states_path}")

    print(f"Reading states CSV:\n  {states_path}")
    df = pd.read_csv(states_path)

    print("Building time sanity table...")
    sanity_df = build_time_sanity(df, tz=args.tz)

    # Infer site name from filename: auditlogs_<site>_states.csv
    stem = states_path.stem  # e.g., auditlogs_Stanford_064_states
    site = stem.replace("auditlogs_", "").replace("_states", "")

    outfile = outdir / f"time_sanity_{site}.csv"
    sanity_df.to_csv(outfile, index=False)

    print(f"\nSaved time sanity summary to:\n  {outfile}")
    print(f"Rows (patients): {len(sanity_df)}")

    # Quick console overview
    n_any_after_noon = sanity_df["any_after_noon"].sum()
    n_crossed_noon = sanity_df["crossed_noon"].sum()
    n_non_mono = sanity_df["has_non_monotonic"].sum()
    n_multi_log = sanity_df["multi_day_log"].sum()
    n_multi_proc = sanity_df["proc_multi_day"].sum()

    print("\nHigh-level counts for this site:")
    print(f"  Cases with any events after noon (log window): {n_any_after_noon}")
    print(f"  Cases that cross noon (log window)          : {n_crossed_noon}")
    print(f"  Cases with non-monotonic time               : {n_non_mono}")
    print(f"  Cases with log multi-day span               : {n_multi_log}")
    print(f"  Cases with procedural multi-day span        : {n_multi_proc}")


if __name__ == "__main__":
    main()
