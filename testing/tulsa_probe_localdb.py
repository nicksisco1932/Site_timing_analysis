#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tulsa_probe_localdb.py

Minimal probe script to verify we can:
- Find local.db for each case under a site
- Open it with sqlite3
- Read from AuditLogRecords (if present)

No Excel. No year filtering. `local.db` only.
"""

# Project: Site Timing Analysis
# File: testing/tulsa_probe_localdb.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Provides a development/testing utility for TULSA probe localdb analysis.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

import argparse
import os
import glob
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# Default root under your user profile
DEFAULT_ROOT = Path(f"C:/Users/{os.environ.get('USERNAME', 'NicholasSisco')}/Profound Medical")


# --------------------------- CLI & PATH HELPERS --------------------------- #

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--site", required=True, help="Site folder name")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Root directory containing site folders")
    parser.add_argument(
        "--timing-subdir",
        default="Clinical Science Team - Genius Services/Timing Data",
        help="Relative path to timing data under root",
    )
    parser.add_argument(
        "--limit-cases",
        type=int,
        default=None,
        help="Limit number of cases to probe",
    )

    # NEW: targeted case + extra event inspection
    parser.add_argument(
        "--case-id",
        default=None,
        help="If provided, only probe this single case folder (e.g., 064_01-080)",
    )
    parser.add_argument(
        "--show-event-types",
        action="store_true",
        help="Print event type counts and any *Treat*-related AuditLogRecords rows",
    )

    return parser.parse_args()


def resolve_root(root_arg: str | None) -> Path:
    if root_arg is not None:
        return Path(root_arg)

    username = os.environ.get("USERNAME", "NicholasSisco")
    default_root = Path(f"C:/Users/{username}/Profound Medical")
    return default_root


def find_site_root(root_dir: Path, timing_subdir: str, site: str) -> Path:
    timing_path = root_dir / timing_subdir
    site_root = timing_path / site

    if not site_root.exists():
        raise FileNotFoundError(
            f"Site root not found: {site_root}\n"
            f"Check --root, --timing-subdir, and --site."
        )

    return site_root


def list_case_folders(site_root: Path) -> list[Path]:
    case_dirs = [p for p in site_root.iterdir() if p.is_dir()]
    case_dirs.sort()
    return case_dirs


# ------------------------------ DB FINDING --------------------------------- #

def find_db_path(case_dir: Path, tempfolder: Path) -> Path | None:
    """
    Locate local.db for a case:

    1) If unzipped local.db exists in common patterns, return its path directly.
    2) Otherwise, search zipped sessions and extract local.db into a
       case-specific temp subfolder, then return that path.

    No copying, no renaming, just use the extracted file where it lands.
    """
    # 1) Unzipped candidates
    patterns = [
        case_dir / "*" / "_*" / "local.db",
        case_dir / "_*" / "local.db",
        case_dir / "local.db",
    ]

    for pattern in patterns:
        matches = glob.glob(str(pattern))
        if matches:
            return Path(matches[0])

    # 2) Zipped sessions
    print(f"      No unzipped local.db found, searching zip in {case_dir}...")
    zipped_session = glob.glob(str(case_dir / "TDC Sessions" / "_*.zip"))
    if not zipped_session:
        zipped_session = glob.glob(str(case_dir / "_201*.zip"))
    if not zipped_session:
        zipped_session = glob.glob(str(case_dir / "*" / "_201*.zip"))
    if not zipped_session:
        zipped_session = glob.glob(str(case_dir / "Session*.zip"))

    if not zipped_session:
        print("      ...Could not find zipped session for this case.")
        return None

    import zipfile

    # Make a case-specific temp dir to avoid file collisions
    case_temp = tempfolder / case_dir.name
    case_temp.mkdir(parents=True, exist_ok=True)

    # Try the first zip; if it fails, we can extend later
    zip_path = Path(zipped_session[0])
    print(f"      Searching {zip_path} for localdb...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        db_names = [n for n in names if n.lower().endswith("local.db")]

        if not db_names:
            print("      ...No local.db inside this zip.")
            return None

        member_name = db_names[0]
        zf.extract(member_name, case_temp)
        extracted = case_temp / member_name
        return extracted


# ------------------------------ PROBE LOGIC -------------------------------- #

def probe_db(db_path: Path, show_event_types: bool = False):
    """
    Open the db, list tables, and if AuditLogRecords exists:
    - print row count
    - print first few rows
    - optionally summarize event types and treatment-related records
    """
    print(f"      Opening DB: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        print(f"      Tables: {tables}")

        if "AuditLogRecords" in tables:
            n_rows = pd.read_sql_query(
                "SELECT COUNT(*) AS n FROM AuditLogRecords", conn
            )["n"].iloc[0]
            print(f"      AuditLogRecords rows: {n_rows}")

            head_df = pd.read_sql_query(
                "SELECT * FROM AuditLogRecords LIMIT 5", conn
            )
            print("      First few AuditLogRecords rows:")
            cols_to_show = [
                c for c in head_df.columns
                if c in ["Id", "TimeStamp", "AuditRecordBase_Type", "SegmentId"]
            ]
            if cols_to_show:
                print(head_df[cols_to_show])
            else:
                print(head_df)

            if show_event_types:
                # 1) Distribution of AuditRecordBase_Type
                df_types = pd.read_sql_query(
                    "SELECT AuditRecordBase_Type, COUNT(*) AS n "
                    "FROM AuditLogRecords "
                    "GROUP BY AuditRecordBase_Type "
                    "ORDER BY n DESC",
                    conn,
                )
                print("\n      AuditRecordBase_Type counts:")
                print(df_types)

                # 2) If EventKind exists, show its distribution as well
                col_info = list(conn.execute("PRAGMA table_info(AuditLogRecords)"))
                cols = [row[1] for row in col_info]
                if "EventKind" in cols:
                    df_ev = pd.read_sql_query(
                        "SELECT EventKind, COUNT(*) AS n "
                        "FROM AuditLogRecords "
                        "GROUP BY EventKind "
                        "ORDER BY n DESC",
                        conn,
                    )
                    print("\n      EventKind counts:")
                    print(df_ev)

                # 3) Show any rows where the type name suggests treatment
                df_treat = pd.read_sql_query(
                    "SELECT * FROM AuditLogRecords "
                    "WHERE AuditRecordBase_Type LIKE '%Treat%' "
                    "ORDER BY TimeStamp "
                    "LIMIT 50",
                    conn,
                )
                if not df_treat.empty:
                    print("\n      First treatment-related AuditLogRecords rows "
                          "(AuditRecordBase_Type LIKE '%Treat%'):")
                    cols_to_show = [
                        c for c in df_treat.columns
                        if c in ["Id", "TimeStamp", "AuditRecordBase_Type", "EventKind", "UserAction"]
                    ]
                    print(df_treat[cols_to_show] if cols_to_show else df_treat)
                else:
                    print("\n      No AuditLogRecords rows with "
                          "AuditRecordBase_Type LIKE '%Treat%'.")
        else:
            print("      No AuditLogRecords table found in this DB.")

    finally:
        conn.close()


# ----------------------------------- MAIN ----------------------------------- #

def main():
    args = parse_args()

    root_dir = resolve_root(str(args.root) if args.root is not None else None)
    site_root = find_site_root(root_dir, args.timing_subdir, args.site)

    # Temp root under Timing Data/temp
    timing_root = root_dir / args.timing_subdir
    tempfolder = timing_root / "temp_probe"
    tempfolder.mkdir(parents=True, exist_ok=True)

    print(f"Root dir:   {root_dir}")
    print(f"Site:       {args.site}")
    print(f"Site root:  {site_root}")
    print(f"Temp root:  {tempfolder}")

    # Step 1: find all case folders
    case_folders = sorted([p for p in site_root.iterdir() if p.is_dir()])

    # If a specific case-id is requested, filter down to only that folder
    if args.case_id:
        matches = [p for p in case_folders if p.name.endswith(args.case_id)]
        if not matches:
            print(f"[ERROR] Could not find case-id {args.case_id}")
            sys.exit(1)
        case_folders = matches
    elif args.limit_cases:
        case_folders = case_folders[:args.limit_cases]

    print(f"Found {len(case_folders)} case folders to probe.\n")

    for ii, case_dir in enumerate(case_folders, start=1):
        print(f"#---  Case {ii} of {len(case_folders)}  ---#")
        print(f"    Case directory: {case_dir}")

        db_path = find_db_path(case_dir, tempfolder)
        if db_path is None or not db_path.exists():
            print("    [skip] local.db not found for this case.\n")
            continue

        try:
            probe_db(db_path, show_event_types=args.show_event_types)
        except Exception as e:
            print(f"    [ERROR] Failed to read DB: {e}")

        print()  # blank line between cases


if __name__ == "__main__":
    main()
