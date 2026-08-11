#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tulsa_state_machine.py

Add workflow states and per-row timings to collected AuditLogRecords.

This version is aimed at timeline reconstruction for Gantt output:
- persistent workflow state across intermediate audit rows
- state ordering aligned with the legacy end product
- normalized start_sec rebased around the intra-MRI workflow anchor
"""

# Project: Site Timing Analysis
# File: src/site_timing_analysis/tulsa_state_machine.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Implements the legacy-compatible TULSA state machine workflow script.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .tulsa_timebase import add_relative_times, parse_time_column
from .tulsa_workflow import STATE_ORDER


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


TRANSITION_MAP = {
    "SetupWorkflowRecord": "TULSA QA",
    "SetupUnlockWorkflowRecord": "Room ready",
    "AnesthesiaStart": "Patient positioning & induction",
    "Ready4Urology": "Patient positioning & induction",
    "DeviceInsertionBegins": "Device insertion",
    "DeviceInsertionEnds": "Device insertion",
    "InitialImaging": "Device repositioning",
    "AlignmentWorkflowRecord": "Alignment",
    "CoarseWorkflowRecord": "Coarse",
    "CoarseUnlockWorkflowRecord": "Coarse",
    "DetailedWorkflowRecord": "Detailed",
    "PlanReadyWorkflowRecord": "Planning start angle",
    "PlanReadyCompleteWorkflowRecord": "Planning start angle",
    "PlanReadyUserStoppedInitializationWorkflowRecord": "Planning start angle",
    "DeliveryInitializingWorkflowRecord": "Initialization",
    "DeliveryInterruptedWorkflowRecord": "Review",
    "ReviewWorkflowRecord": "Post-treatment scans & Device removal",
    "DevicesRemovalStarts": "Post-treatment scans & Device removal",
    "DevicesRemovalEnds": "Post-treatment scans & Device removal",
    "PatientTransferBegins": "Patient recovery & transfer",
    "PatientTransferEnds": "Patient recovery & transfer",
}


TREATING_TYPES = {
    "DeliveryWorkflowRecord",
    "DeliveryResumedWorkflowRecord",
    "TreatmentRecord",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "TreatmentId" in out.columns and "SegmentId" not in out.columns:
        out = out.rename(columns={"TreatmentId": "SegmentId"})

    for col in ["SignalHelpKey", "FirstActiveElement"]:
        if col in out.columns:
            out = out.drop(columns=col)

    return out


def _remove_duplicate_alignment_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "AuditRecordBase_Type" not in df.columns or "TimeStamp" not in df.columns:
        return df

    prev_type = df["AuditRecordBase_Type"].shift(1)
    prev_time = df["TimeStamp"].shift(1)
    mask = (
        (df["AuditRecordBase_Type"] == "AlignmentWorkflowRecord")
        & (prev_type == "CoarseWorkflowRecord")
        & (df["TimeStamp"] == prev_time)
    )
    return df.loc[~mask].reset_index(drop=True)


def _segment_date_mismatch(row: pd.Series) -> bool:
    segment_id = row.get("SegmentId")
    ts = row.get("TimeStamp")
    if pd.isna(segment_id) or pd.isna(ts):
        return False

    segment_text = str(segment_id).strip()
    ts_text = str(ts).strip()
    if len(segment_text) < 10 or "-" not in segment_text or len(ts_text) < 10:
        return False

    return segment_text[:10] != ts_text[:10]


def _map_states_for_case(case_df: pd.DataFrame) -> pd.DataFrame:
    out = case_df.copy().sort_values("TimeStamp").reset_index(drop=True)
    curr_state = ""
    patient_prep_started = False
    states: list[str] = []

    for _, row in out.iterrows():
        audit_type = str(row.get("AuditRecordBase_Type", ""))
        event_kind = row.get("EventKind")
        next_state = curr_state

        if audit_type == "UATestRecord" and not patient_prep_started:
            next_state = "Room ready"
        elif audit_type in TRANSITION_MAP:
            next_state = TRANSITION_MAP[audit_type]
        elif "DeliveryPaused" in audit_type:
            next_state = "Paused"
        elif audit_type in TREATING_TYPES:
            next_state = "Treating"

        if next_state == "Patient positioning & induction":
            patient_prep_started = True

        if next_state == "Post-treatment scans & Device removal" and (
            audit_type == "MriConnectionRecord"
            or (audit_type == "SessionEventRecord" and event_kind == 1)
            or (audit_type == "SegmentEventRecord" and event_kind == 2)
        ):
            next_state = ""
        elif _segment_date_mismatch(row):
            next_state = ""

        states.append(next_state)
        curr_state = next_state

    out["CurrentState"] = states
    return out


def _apply_setup_adjustments(case_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    out = case_df.copy().reset_index(drop=True)
    audit_types = out["AuditRecordBase_Type"].fillna("")
    states = out["CurrentState"].fillna("").tolist()

    alignment_idxs = audit_types[audit_types == "AlignmentWorkflowRecord"].index.tolist()
    if not alignment_idxs:
        out["CurrentState"] = states
        return out, None
    alignment_idx = alignment_idxs[0]

    ps_tests = audit_types[audit_types == "PSTestRecord"].index.tolist()
    ua_tests = audit_types[audit_types == "UATestRecord"].index.tolist()
    ua_homes = audit_types[audit_types == "PSHomingRecord"].index.tolist()
    setup_idxs = audit_types[audit_types == "SetupWorkflowRecord"].index.tolist()
    init_imaging_idxs = audit_types[audit_types == "InitialImaging"].index.tolist()
    device_insert_end_idxs = audit_types[audit_types == "DeviceInsertionEnds"].index.tolist()

    last_ps_test = 0
    ps_before_alignment = [idx for idx in ps_tests if idx < alignment_idx]
    ua_before_alignment = [idx for idx in ua_tests if idx < alignment_idx]
    if ps_before_alignment:
        last_ps_test = max(ps_before_alignment)
    if ua_before_alignment:
        last_ps_test = max(last_ps_test, max(ua_before_alignment))
    if last_ps_test <= 1:
        if len(ua_homes) > 1:
            last_ps_test = ua_homes[0]
        elif setup_idxs:
            last_ps_test = setup_idxs[0]

    ua_after_last_ps = [idx for idx in ua_homes if idx > last_ps_test]
    ua_before_alignment = [idx for idx in ua_homes if idx < alignment_idx]
    last_ua_homing = max(ua_before_alignment) if ua_before_alignment else None
    init_imaging_start = init_imaging_idxs[0] if init_imaging_idxs else None
    device_insertion_end = device_insert_end_idxs[0] if device_insert_end_idxs else None

    if (
        device_insertion_end is not None
        and init_imaging_start is not None
        and device_insertion_end <= init_imaging_start
    ):
        for idx in range(device_insertion_end, init_imaging_start + 1):
            states[idx] = "Device insertion"

    rebase_anchor = None
    if ua_after_last_ps:
        if init_imaging_start is None:
            if last_ua_homing is not None and last_ua_homing < alignment_idx:
                for idx in range(last_ua_homing, alignment_idx):
                    states[idx] = "Device repositioning"
                rebase_anchor = "LastUAHoming"
        else:
            if init_imaging_start < alignment_idx:
                for idx in range(init_imaging_start, alignment_idx):
                    states[idx] = "Device repositioning"
                rebase_anchor = "InitialImaging"
    else:
        rebase_anchor = "Alignment"

    out["CurrentState"] = states
    return out, rebase_anchor


def map_states(df: pd.DataFrame) -> pd.DataFrame:
    out = _normalize_columns(df)

    if "AuditRecordBase_Type" not in out.columns:
        out["CurrentState"] = ""
        out["RebaseAnchor"] = None
        return out

    out = out[out["AuditRecordBase_Type"] != "SignalRecord"].copy()
    out = out.sort_values("TimeStamp").reset_index(drop=True)
    out = _remove_duplicate_alignment_rows(out)

    group_cols = [col for col in ["Pt", "PtId"] if col in out.columns]
    mapped_cases: list[pd.DataFrame] = []

    if not group_cols:
        mapped = _map_states_for_case(out)
        mapped, anchor = _apply_setup_adjustments(mapped)
        mapped["RebaseAnchor"] = anchor
        mapped_cases.append(mapped)
    else:
        for _, case_df in out.groupby(group_cols, sort=False, dropna=False):
            mapped = _map_states_for_case(case_df)
            mapped, anchor = _apply_setup_adjustments(mapped)
            mapped["RebaseAnchor"] = anchor
            mapped_cases.append(mapped)

    out = pd.concat(mapped_cases, ignore_index=True)
    out = out[out["CurrentState"] != ""].copy()
    out["CurrentState"] = pd.Categorical(
        out["CurrentState"],
        categories=STATE_ORDER,
        ordered=True,
    )
    return out


def add_times(df: pd.DataFrame, tz: str | None = None) -> pd.DataFrame:
    if "TimeStamp" not in df.columns:
        raise ValueError("Input dataframe has no TimeStamp column.")

    df_ts = parse_time_column(
        df,
        source_col="TimeStamp",
        target_col="ts",
        tz=tz,
        drop_bad=True,
        verbose=True,
    )

    if "Pt" in df_ts.columns:
        group_key = "Pt"
    elif "PtId" in df_ts.columns:
        group_key = "PtId"
    else:
        group_key = None

    if group_key is not None:
        df_rel = add_relative_times(
            df_ts,
            ts_col="ts",
            group_col=group_key,
            start_col="start_sec",
            dur_col="duration_sec",
        )
        df_rel["first_ts"] = df_rel.groupby(group_key)["ts"].transform("min")
        df_rel["last_ts"] = df_rel.groupby(group_key)["ts"].transform("max")
    else:
        df_rel = add_relative_times(
            df_ts,
            ts_col="ts",
            group_col=None,
            start_col="start_sec",
            dur_col="duration_sec",
        )
        df_rel["first_ts"] = df_rel["ts"].min()
        df_rel["last_ts"] = df_rel["ts"].max()

    if "RebaseAnchor" not in df_rel.columns:
        return df_rel

    if group_key is None:
        grouped = [(None, df_rel)]
    else:
        grouped = list(df_rel.groupby(group_key, sort=False, dropna=False))

    adjusted_cases: list[pd.DataFrame] = []
    for _, case_df in grouped:
        case_out = case_df.copy()
        anchor = (
            case_out["RebaseAnchor"].dropna().iloc[0]
            if case_out["RebaseAnchor"].notna().any()
            else None
        )

        anchor_start = None
        if anchor == "InitialImaging":
            mask = case_out["AuditRecordBase_Type"] == "InitialImaging"
            if mask.any():
                anchor_start = float(case_out.loc[mask, "start_sec"].iloc[0])
        elif anchor == "LastUAHoming":
            mask = case_out["AuditRecordBase_Type"] == "PSHomingRecord"
            if mask.any():
                anchor_start = float(case_out.loc[mask, "start_sec"].iloc[-1])
        elif anchor == "Alignment":
            mask = case_out["AuditRecordBase_Type"] == "AlignmentWorkflowRecord"
            if mask.any():
                anchor_start = float(case_out.loc[mask, "start_sec"].iloc[0])

        if anchor_start is not None:
            case_out["start_sec"] = case_out["start_sec"] - anchor_start

        adjusted_cases.append(case_out)

    return pd.concat(adjusted_cases, ignore_index=True)


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

    site = "site"
    stem = infile.stem
    if stem.startswith("auditlogs_"):
        site = stem.replace("auditlogs_", "")

    outfile = outdir / f"auditlogs_{site}_states.csv"
    df.to_csv(outfile, index=False)

    print(f"Saved state-enriched auditlog to: {outfile}")
    print(f"Rows: {len(df)}")


if __name__ == "__main__":
    main()
