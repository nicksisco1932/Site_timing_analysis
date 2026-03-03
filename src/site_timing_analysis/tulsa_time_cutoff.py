#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_time_cutoff.py  (v0.1)
----------------------------
Assess which cases extend beyond or cross a configurable time-of-day cutoff.

Input:
    auditlogs_<site>_states.csv  (from tulsa_state_machine.py)

Output:
    time_cutoff_<site>_<HHMM>.csv in the specified --outdir

For each PtId, using the procedural window (CurrentState != ""):
    - proc_first_ts
    - proc_last_ts
    - proc_duration_min
    - any_after_cutoff      (any event at/after cutoff)
    - crossed_cutoff        (first < cutoff, last >= cutoff)
"""

import argparse
from pathlib import Path
from datetime import datetime, time

import pandas as pd

from .tulsa_timebase import parse_time_column


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Assess which cases extend beyond or cross a configurable "
            "time-of-day cutoff."
        )
    )
    p.add_argument(
        "--states-csv",
        required=True,
        help="Path to auditlogs_<site>_states.csv (from tulsa_state_machine.py)",
    )
    p.add_argument(
        "--outdir",
        required=True,
        help="Directory where time_cutoff_<site>_<HHMM>.csv will be written.",
    )
    p.add_argument(
        "--cutoff",
        required=True,
        help=(
            "Local time-of-day cutoff as 'HH:MM' or 'HH:MM:SS', e.g. '12:00' or '13:30'. "
            "Used against procedural timestamps (CurrentState != '')."
        ),
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


def parse_cutoff_time(s: str) -> time:
    """
    Parse a string 'HH:MM' or 'HH:MM:SS' into a datetime.time.
    """
    s = s.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Could not parse cutoff time '{s}'. Expected HH:MM or HH:MM:SS.")


def build_cutoff_table(df: pd.DataFrame, cutoff_t: time, tz: str | None = None) -> pd.DataFrame:
    """
    Compute per-PtId metrics relative to a time-of-day cutoff, using
    only procedural events (CurrentState != '') if available.
    """
    required_cols = ["PtId", "TimeStamp"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in states CSV: {missing}")

    has_state = "CurrentState" in df.columns

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

    records = []

    for ptid, g_all in df.groupby("PtId"):
        # Procedural subset if available
        if has_state:
            g = g_all[g_all["CurrentState"].astype(str) != ""].copy()
        else:
            g = g_all.copy()

        if g.empty:
            # No procedural events; record minimal info
            records.append(
                {
                    "PtId": ptid,
                    "proc_first_ts": pd.NaT,
                    "proc_last_ts": pd.NaT,
                    "proc_duration_min": float("nan"),
                    "any_after_cutoff": False,
                    "crossed_cutoff": False,
                }
            )
            continue

        g = g.sort_values("ts")
        first_ts = g["ts"].iloc[0]
        last_ts = g["ts"].iloc[-1]

        duration_min = (last_ts - first_ts).total_seconds() / 60.0

        any_after = (g["ts"].dt.time >= cutoff_t).any()
        crossed = (first_ts.time() < cutoff_t) and (last_ts.time() >= cutoff_t)

        records.append(
            {
                "PtId": ptid,
                "proc_first_ts": first_ts,
                "proc_last_ts": last_ts,
                "proc_duration_min": duration_min,
                "any_after_cutoff": bool(any_after),
                "crossed_cutoff": bool(crossed),
            }
        )

    out = pd.DataFrame.from_records(records)
    out = out.sort_values(["PtId", "proc_first_ts"]).reset_index(drop=True)
    return out


def main():
    args = parse_args()

    states_path = Path(args.states_csv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not states_path.exists():
        raise FileNotFoundError(f"States CSV not found: {states_path}")

    cutoff_t = parse_cutoff_time(args.cutoff)

    print(f"Reading states CSV:\n  {states_path}")
    df = pd.read_csv(states_path)

    print(f"Building cutoff table for cutoff: {args.cutoff} ...")
    cutoff_df = build_cutoff_table(df, cutoff_t=cutoff_t, tz=args.tz)

    # Infer site name from filename: auditlogs_<site>_states.csv
    stem = states_path.stem  # e.g., auditlogs_Stanford_064_states
    site = stem.replace("auditlogs_", "").replace("_states", "")

    # For filename, make '12:30' -> '1230'
    cutoff_tag = args.cutoff.replace(":", "")
    outfile = outdir / f"time_cutoff_{site}_{cutoff_tag}.csv"
    cutoff_df.to_csv(outfile, index=False)

    print(f"\nSaved cutoff summary to:\n  {outfile}")
    print(f"Rows (patients): {len(cutoff_df)}")

    n_any = cutoff_df["any_after_cutoff"].sum()
    n_crossed = cutoff_df["crossed_cutoff"].sum()

    print("\nHigh-level counts for this site:")
    print(f"  Cases with any procedural events at/after {args.cutoff}: {n_any}")
    print(f"  Cases that cross {args.cutoff} (start <, end >=):       {n_crossed}")


if __name__ == "__main__":
    main()
