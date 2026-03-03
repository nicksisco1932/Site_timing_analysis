#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_collect_auditlogs.py  (v0.1)

Goal:
    For a given site, iterate all case folders, locate local.db
    (unzipped or in a zip), read AuditLogRecords, and aggregate them
    into a single CSV:

        auditlogs_<site>.csv

No Excel timing sheets, no state machine, no plotting.
Just raw AuditLogRecords + basic identifiers.

Usage examples:
    python tulsa_collect_auditlogs.py --site Stanford_064
    python tulsa_collect_auditlogs.py --site Stanford_064 --years 2021
"""

import argparse
import os
import glob
import sqlite3
from pathlib import Path

import pandas as pd


# --------------------------- CLI & PATH HELPERS --------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect raw AuditLogRecords for a given site into one CSV."
    )

    parser.add_argument(
        "--site",
        required=True,
        help="Site folder name under Timing Data, e.g., 'Stanford_064', 'MayoRoch_075'.",
    )

    parser.add_argument(
        "--years",
        default="All",
        help="Year selection: All, CurrentYear, PastYears, or a specific year (e.g., 2021).",
    )

    parser.add_argument(
        "--root",
        default=None,
        help="Root directory where 'Profound Medical' lives. "
             "Default: C:/Users/<USERNAME>/Profound Medical",
    )

    parser.add_argument(
        "--timing-subdir",
        default="Clinical Science Team - Genius Services/Timing Data",
        help="Subdirectory under root containing timing folders.",
    )

    parser.add_argument(
        "--outdir",
        required=True,
        help="Directory where all output (CSV, plots, etc.) will be written.",
    )

    parser.add_argument(
        "--limit-cases",
        type=int,
        default=None,
        help="Optional: only process the first N cases.",
    )

    return parser.parse_args()



def resolve_root(root_arg: str | None) -> Path:
    if root_arg is not None:
        return Path(root_arg)

    username = os.environ.get("USERNAME", "NicholasSisco")
    return Path(f"C:/Users/{username}/Profound Medical")


def build_year_list(years_arg: str):
    years_arg = str(years_arg)
    this_year = pd.Timestamp.today().year

    if years_arg == "All":
        return list(range(2016, this_year + 1))
    if years_arg == "CurrentYear":
        return [this_year]
    if years_arg == "PastYears":
        return list(range(2016, this_year))
    try:
        return [int(years_arg)]
    except ValueError:
        raise ValueError(f"Invalid --years option: {years_arg}")


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

    case_temp = tempfolder / case_dir.name
    case_temp.mkdir(parents=True, exist_ok=True)

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


def read_auditlog_from_db(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM AuditLogRecords", conn)
    finally:
        conn.close()
    return df


# ------------------------------ MAIN LOGIC --------------------------------- #

def main():
    args = parse_args()

    root_dir = resolve_root(args.root)
    yearlist = build_year_list(args.years)
    site_root = find_site_root(root_dir, args.timing_subdir, args.site)

    timing_root = root_dir / args.timing_subdir
    tempfolder = timing_root / "temp_collect"
    tempfolder.mkdir(parents=True, exist_ok=True)

    print(f"Root dir:   {root_dir}")
    print(f"Site:       {args.site}")
    print(f"Years:      {yearlist}")
    print(f"Site root:  {site_root}")
    print(f"Temp root:  {tempfolder}")

    case_folders = list_case_folders(site_root)
    if args.limit_cases is not None:
        case_folders = case_folders[:args.limit_cases]

    print(f"Found {len(case_folders)} case folders to process.\n")

    all_logs: list[pd.DataFrame] = []
    included_cases = 0

    for ii, case_dir in enumerate(case_folders, start=1):
        print(f"#---  Case {ii} of {len(case_folders)}  ---#")
        print(f"    Case directory: {case_dir}")

        db_path = find_db_path(case_dir, tempfolder)
        if db_path is None or not db_path.exists():
            print("    [skip] local.db not found for this case.\n")
            continue

        try:
            auditlog = read_auditlog_from_db(db_path)
        except Exception as e:
            print(f"    [ERROR] Failed to read AuditLogRecords: {e}\n")
            continue

        if auditlog.empty:
            print("    [skip] AuditLogRecords table is empty.\n")
            continue

        # Determine treatment year from first TimeStamp (string-based, like R)
        if "TimeStamp" not in auditlog.columns:
            print("    [skip] No TimeStamp column in AuditLogRecords.\n")
            continue

        ts0 = str(auditlog.iloc[0]["TimeStamp"])
        if len(ts0) < 4 or not ts0[:4].isdigit():
            print(f"    [skip] Cannot parse year from first TimeStamp: {ts0}\n")
            continue

        treatment_year = int(ts0[:4])
        if treatment_year not in yearlist:
            print(f"    [exclude] Treatment year {treatment_year} not in {yearlist}\n")
            continue

        # Attach simple identifiers
        pt_id = case_dir.name  # use folder name as PtId (cleaner than R's substring hacks)
        auditlog["Site"] = args.site
        auditlog["PtId"] = pt_id
        auditlog["Pt"] = ii
        auditlog["CaseFolder"] = str(case_dir)

        # Optionally drop SignalRecord rows now (R did this later)
        # auditlog = auditlog[auditlog["AuditRecordBase_Type"] != "SignalRecord"]

        all_logs.append(auditlog)
        included_cases += 1
        print(f"    [include] Treatment year {treatment_year}, rows: {len(auditlog)}\n")

    if not all_logs:
        print("No cases passed filters / produced audit logs. Nothing to write.")
        return

    combined = pd.concat(all_logs, ignore_index=True)

    # Make sure the output directory exists
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    out_name = f"auditlogs_{args.site}.csv"
    out_path = outdir / out_name
    combined.to_csv(out_path, index=False)

    print(f"Collected {included_cases} cases.")
    print(f"Total rows in combined auditlog: {len(combined)}")
    print(f"Saved to: {out_path}")


    print(f"Collected {included_cases} cases.")
    print(f"Total rows in combined auditlog: {len(combined)}")
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
