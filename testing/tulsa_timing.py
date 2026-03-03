#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_timing.py  (v0.2)

New, less brittle entry point for TULSA timing analysis.

Current behavior:
- CLI-driven (no GUI selects).
- Enumerates case folders under a site.
- For each case:
    * Locates local.db (direct or inside zipped sessions).
    * Optionally merges local2.db if present.
    * Reads AuditLogRecords.
    * Determines treatment year from first TimeStamp.
    * Includes or skips case based on --years selection.

Next step (later): port the full CurrentState + timing_summary logic into
a separate function once we’re happy this core discovery is solid.
"""

import argparse
import os
import glob
from pathlib import Path
import sqlite3

import pandas as pd


# --------------------------- CLI & CONFIG HELPERS --------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="TULSA timing analysis (new CLI-driven version)."
    )

    parser.add_argument(
        "--site",
        required=True,
        help="Site folder name under Timing Data, e.g., 'Stanford_064', 'MayoRoch_075'.",
    )

    parser.add_argument(
        "--years",
        default="All",
        help="Year selection: All, CurrentYear, PastYears, or a specific year (e.g., 2023).",
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

    return parser.parse_args()


def resolve_root(root_arg: str | None) -> Path:
    if root_arg is not None:
        return Path(root_arg)

    username = os.environ.get("USERNAME", "NicholasSisco")
    default_root = Path(f"C:/Users/{username}/Profound Medical")
    return default_root


def build_year_list(years_arg: str):
    years_arg = str(years_arg)
    this_year = pd.Timestamp.today().year

    if years_arg == "All":
        return list(range(2016, this_year + 1))
    if years_arg == "CurrentYear":
        return [this_year]
    if years_arg == "PastYears":
        return list(range(2016, this_year))
    # explicit year
    try:
        year_int = int(years_arg)
        return [year_int]
    except ValueError:
        raise ValueError(f"Invalid --years option: {years_arg}")


def find_site_root(root_dir: Path, timing_subdir: str, site: str) -> Path:
    """
    Default pattern:
        <root_dir>/<timing_subdir>/<site>/
    e.g.,
        C:/Users/NicholasSisco/Profound Medical/
            Clinical Science Team - Genius Services/Timing Data/Stanford_064
    """
    timing_path = root_dir / timing_subdir
    site_root = timing_path / site

    if not site_root.exists():
        raise FileNotFoundError(
            f"Site root not found: {site_root}\n"
            f"Check --root, --timing-subdir, and --site."
        )

    return site_root


def list_case_folders(site_root: Path) -> list[Path]:
    """
    Non-recursive listing of case folders under the site root.

    For Stanford_064, you might have:
        064_01-112/
        064_01-113/
        ...
        STA_01-003/
        STA_01-004/
    All of these are treated as “cases” for now.
    """
    case_dirs: list[Path] = [
        p for p in site_root.iterdir() if p.is_dir()
    ]
    case_dirs.sort()
    return case_dirs


# ----------------------------- DB / IO HELPERS ------------------------------ #

def read_auditlog_from_db(dbfile: Path) -> pd.DataFrame:
    """Read AuditLogRecords table from a SQLite DB."""
    conn = sqlite3.connect(dbfile)
    try:
        df = pd.read_sql_query("SELECT * FROM AuditLogRecords", conn)
    finally:
        conn.close()
    return df


def merge_local2_if_present(case_dir: Path, tempfolder: Path, auditlog: pd.DataFrame) -> pd.DataFrame:
    """
    If local2.db exists in the case_dir, copy and merge its AuditLogRecords.
    """
    local2_candidates = glob.glob(str(case_dir / "local2.db"))
    if not local2_candidates:
        return auditlog

    local2_src = Path(local2_candidates[0])
    local2_dst = tempfolder / "local2.db"

    if not local2_dst.exists():
        local2_dst.write_bytes(local2_src.read_bytes())

    conn2 = sqlite3.connect(local2_dst)
    try:
        auditlog2 = pd.read_sql_query("SELECT * FROM AuditLogRecords", conn2)
    finally:
        conn2.close()

    if not auditlog2.empty:
        auditlog = pd.concat([auditlog, auditlog2], ignore_index=True)

    return auditlog


def find_or_extract_db(case_dir: Path, tempfolder: Path) -> Path | None:
    """
    Locate local.db for a case:
    1) Unzipped in various common patterns
    2) Inside a zipped session (TDC Sessions / *_201*.zip / Session*.zip)

    If found inside a zip, extract into tempfolder.

    Returns the path to a usable local.db, or None if not found.
    """
    # 1) Try unzipped local.db
    patterns = [
        case_dir / "*" / "_*" / "local.db",
        case_dir / "_*" / "local.db",
        case_dir / "local.db",
    ]

    unzipped_dbfiles: list[str] = []
    for pattern in patterns:
        matches = glob.glob(str(pattern))
        if matches:
            unzipped_dbfiles = matches
            break

    if unzipped_dbfiles:
        # Copy first found db to tempfolder/local.db (overwrite is fine)
        src = Path(unzipped_dbfiles[0])
        dst = tempfolder / "local.db"
        dst.write_bytes(src.read_bytes())
        return dst

    # 2) No unzipped db: search zipped session
    print(f"      Searching {case_dir} for zipped session...")
    zipped_session = glob.glob(str(case_dir / "TDC Sessions" / "_*.zip"))
    if not zipped_session:
        zipped_session = glob.glob(str(case_dir / "_201*.zip"))
    if not zipped_session:
        zipped_session = glob.glob(str(case_dir / "*" / "_201*.zip"))
    if not zipped_session:
        zipped_session = glob.glob(str(case_dir / "Session*.zip"))

    if not zipped_session:
        print("      ...Could not find zipped session for this patient.")
        return None

    import zipfile

    zip_path = Path(zipped_session[0])
    print(f"      Searching {zip_path} for localdb...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        zipped_db_names = [
            name for name in names
            if name.lower().endswith("local.db")
        ]

        # If first zip didn’t contain local.db and more zips exist, try the next
        if not zipped_db_names and len(zipped_session) > 1:
            zip_path = Path(zipped_session[1])
            print(f"      Searching {zip_path} for localdb...")
            with zipfile.ZipFile(zip_path, "r") as zf2:
                names = zf2.namelist()
                zipped_db_names = [
                    name for name in names
                    if name.lower().endswith("local.db")
                ]
                if not zipped_db_names:
                    print("      ...Could not find localdb in zipped session for this patient.")
                    return None
                member_name = zipped_db_names[0]
                dst = tempfolder / "local.db"
                zf2.extract(member_name, tempfolder)
                # Move/rename extracted file to local.db if it has a path
                extracted = tempfolder / member_name
                if extracted != dst:
                    dst.write_bytes(extracted.read_bytes())
                    extracted.unlink()
                return dst

        if not zipped_db_names:
            print("      ...Could not find localdb in zipped session for this patient.")
            return None

        # Extract first matched local.db into tempfolder/local.db
        member_name = zipped_db_names[0]
        dst = tempfolder / "local.db"
        zf.extract(member_name, tempfolder)
        extracted = tempfolder / member_name
        if extracted != dst:
            dst.write_bytes(extracted.read_bytes())
            extracted.unlink()
        return dst


# ---------------------------- PER-CASE PROCESSING --------------------------- #

def process_case(ii: int, total: int, case_dir: Path, yearlist: list[int], tempfolder: Path):
    """
    Minimal but real processing for one case:

    - Find local.db (unzipped or from zipped session).
    - Merge local2.db if present.
    - Read AuditLogRecords.
    - Determine treatment year from first TimeStamp.
    - Print whether the case is included or excluded by year.
    """
    print(f"#---  Case {ii} of {total}  ---#")
    print(f"    Case directory: {case_dir}")

    dbfile = find_or_extract_db(case_dir, tempfolder)
    if dbfile is None:
        print("    [skip] No local.db found for this case.")
        return

    print(f"    Using DB: {dbfile}")
    auditlog = read_auditlog_from_db(dbfile)

    if auditlog.empty:
        print("    [skip] AuditLogRecords table is empty.")
        return

    # Merge local2.db if present
    auditlog = merge_local2_if_present(case_dir, tempfolder, auditlog)

    # Determine treatment year from first TimeStamp
    if "TimeStamp" not in auditlog.columns:
        print("    [skip] No TimeStamp column in AuditLogRecords.")
        return

    ts0 = str(auditlog.iloc[0]["TimeStamp"])
    if len(ts0) < 4 or not ts0[:4].isdigit():
        print(f"    [skip] Cannot parse year from first TimeStamp: {ts0}")
        return

    treatment_year = int(ts0[:4])

    if treatment_year in yearlist:
        print(f"    [include] Treatment year {treatment_year} is in {yearlist}")
        # This is where we will eventually run the full workflow reconstruction.
        # For now we stop here to validate discovery & year filtering.
    else:
        print(f"    [exclude] Treatment year {treatment_year} not in {yearlist}")


# ----------------------------------- MAIN ----------------------------------- #

def main():
    args = parse_args()

    root_dir = resolve_root(args.root)
    yearlist = build_year_list(args.years)

    print(f"Root dir:  {root_dir}")
    print(f"Site:      {args.site}")
    print(f"Years:     {yearlist}")

    site_root = find_site_root(root_dir, args.timing_subdir, args.site)
    print(f"Site root: {site_root}")

    # temp folder under Timing Data/temp
    timing_root = root_dir / args.timing_subdir
    tempfolder = timing_root / "temp"
    tempfolder.mkdir(parents=True, exist_ok=True)

    case_folders = list_case_folders(site_root)
    if not case_folders:
        print("No case folders found under site root.")
        return

    print(f"Found {len(case_folders)} case folders.\n")

    for ii, case_dir in enumerate(case_folders, start=1):
        process_case(ii, len(case_folders), case_dir, yearlist, tempfolder)


if __name__ == "__main__":
    main()
