#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_state_machine.py  (v0.2)

Add workflow states and per-row timings (absolute + relative) to collected
AuditLogRecords.

Input:
    CSV from tulsa_collect_auditlogs.py, e.g. auditlogs_Stanford_064.csv

Output:
    auditlogs_<site>_states.csv in the chosen --outdir

Key additions in v0.2
---------------------
- Use tulsa_timebase.parse_time_column for canonical datetime parsing
  of TimeStamp (full ISO-like local times from local.db).
- Attach per-case first_ts and last_ts (wall-clock) in addition to
  start_sec and duration_sec.
"""

import argparse
from pathlib import Path

import pandas as pd

from tulsa_timebase import parse_time_column, add_relative_times


# --------------------------- CLI HELPERS --------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Attach workflow states and timings to AuditLogRecords."
    )

    parser.add_argument(
        "--infile",
        required=True,
        help="Input CSV (combined AuditLogRecords), e.g. auditlogs_Stanford_064.csv",
    )

    parser.add_argument(
        "--outdir",
        required=True,
        help="Directory where output CSV will be written.",
    )

    parser.add_argument(
        "--tz",
        default=None,
        help=(
            "Optional timezone string (e.g., 'America/Los_Angeles'). "
            "If provided, TimeStamp is interpreted as local time in this TZ."
        ),
    )

    return parser.parse_args()


TREATING_TYPES = {
    "DeliveryWorkflowRecord",
    "DeliveryInitializingWorkflowRecord",
    "DeliveryPausedUserWorkflowRecord",
    "DeliveryTerminatingWorkflowRecord",
    "TreatmentRecord",
}


# ----------------------- STATE MACHINE LOGIC ----------------------- #

def map_states(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map AuditRecordBase_Type to higher-level workflow states.

    This is a first-pass, simplified port of the R logic WITHOUT Excel timing
    sheets. We can refine this mapping later as needed.
    """

    state_map = {
        # Setup / QA / room
        "SetupWorkflowRecord": "TULSA QA",
        "SetupUnlockWorkflowRecord": "Room ready",
        "UATestRecord": "Room ready",

        # Alignment / coarse / detailed
        "AlignmentWorkflowRecord": "Alignment",
        "CoarseWorkflowRecord": "Coarse",
        "CoarseUnlockWorkflowRecord": "Coarse",
        "DetailedWorkflowRecord": "Detailed",

        # Planning
        "PlanReadyWorkflowRecord": "Planning start angle",
        "PlanReadyCompleteWorkflowRecord": "Planning start angle",
        "PlanReadyUserStoppedInitializationWorkflowRecord": "Planning start angle",

        # Review / post-treatment
        "DeliveryInterruptedWorkflowRecord": "Review",
        "ReviewWorkflowRecord": "Post-treatment scans & Device removal",

        # Patient / device handling (if present as types)
        "DevicesRemovalStarts": "Post-treatment scans & Device removal",
        "DevicesRemovalEnds": "Post-treatment scans & Device removal",
        "PatientTransferBegins": "Patient recovery & transfer",
        "PatientTransferEnds": "Patient recovery & transfer",
    }

    df = df.copy()
    df["CurrentState"] = ""

    if "AuditRecordBase_Type" not in df.columns:
        return df

    # Direct map where exact string matches
    df["CurrentState"] = df["AuditRecordBase_Type"].map(state_map).fillna("")

    # Treating states: anything in TREATING_TYPES
    mask_treating = df["AuditRecordBase_Type"].isin(TREATING_TYPES)
    df.loc[mask_treating, "CurrentState"] = "Treating"

    # Handle any DeliveryPaused* types as "Paused" (overrides Treating)
    mask_paused = df["AuditRecordBase_Type"].astype(str).str.contains(
        "DeliveryPaused", na=False
    )
    df.loc[mask_paused, "CurrentState"] = "Paused"

    # Optionally drop SignalRecord rows now (they don't carry state)
    df = df[df.get("AuditRecordBase_Type") != "SignalRecord"]

    return df


def add_times(df: pd.DataFrame, tz: str | None = None) -> pd.DataFrame:
    """
    Compute per-row absolute and relative timings per case.

    Adds:
        - ts          : parsed datetime from TimeStamp (optionally tz-localized)
        - start_sec   : seconds from first ts in that Pt / PtId
        - duration_sec: time until the next event in that Pt / PtId
        - first_ts    : case-level earliest ts (wall-clock)
        - last_ts     : case-level latest ts (wall-clock)
    """
    if "TimeStamp" not in df.columns:
        raise ValueError("Input dataframe has no TimeStamp column.")

    # 1) Canonical datetime parsing (full ISO-like local times from local.db)
    df_ts = parse_time_column(
        df,
        source_col="TimeStamp",
        target_col="ts",
        tz=tz,
        drop_bad=True,
        verbose=True,
    )

    # 2) Decide grouping key for "case"
    if "Pt" in df_ts.columns:
        group_key = "Pt"
    elif "PtId" in df_ts.columns:
        group_key = "PtId"
    else:
        group_key = None

    # 3) Relative seconds per case
    if group_key is not None:
        df_rel = add_relative_times(
            df_ts,
            ts_col="ts",
            group_col=group_key,
            start_col="start_sec",
            dur_col="duration_sec",
        )
        # Case-level absolute bounds
        df_rel["first_ts"] = df_rel.groupby(group_key)["ts"].transform("min")
        df_rel["last_ts"] = df_rel.groupby(group_key)["ts"].transform("max")
    else:
        # Fallback: treat entire dataframe as one case
        df_rel = add_relative_times(
            df_ts,
            ts_col="ts",
            group_col=None,
            start_col="start_sec",
            dur_col="duration_sec",
        )
        df_rel["first_ts"] = df_rel["ts"].min()
        df_rel["last_ts"] = df_rel["ts"].max()

    return df_rel


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

    print("Mapping workflow states...")
    df = map_states(df)

    print("Adding absolute and relative timings...")
    df = add_times(df, tz=args.tz)

    # Optionally keep only rows with a non-empty CurrentState for downstream analysis
    df_states = df.copy()
    # df_states = df_states[df_states["CurrentState"] != ""]

    # Infer site from filename if possible
    site = "site"
    stem = infile.stem  # e.g., auditlogs_Stanford_064
    if stem.startswith("auditlogs_"):
        site = stem.replace("auditlogs_", "")

    outfile = outdir / f"auditlogs_{site}_states.csv"
    df_states.to_csv(outfile, index=False)

    print(f"Saved state-enriched auditlog to: {outfile}")
    print(f"Rows: {len(df_states)}")


if __name__ == "__main__":
    main()
