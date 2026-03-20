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

Also supports a direct single-DB mode for local smoke testing:
    python tulsa_collect_auditlogs.py --db-path test_data/local.db --outdir out

Usage examples:
    python tulsa_collect_auditlogs.py --site Stanford_064
    python tulsa_collect_auditlogs.py --site Stanford_064 --years 2021
"""

import argparse
import re
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
        default=None,
        help="Site ID used in output naming, e.g., 'Stanford_064', 'MayoRoch_075'.",
    )

    parser.add_argument(
        "--site-path",
        default=None,
        help="Optional direct filesystem path to the site folder. "
             "If set, bypass --root/--timing-subdir resolution.",
    )

    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional direct path to a single local.db file. If set, bypass site-folder discovery.",
    )

    parser.add_argument(
        "--pt-id",
        default=None,
        help="Optional PtId override when using --db-path.",
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

    args = parser.parse_args()

    if args.site is None and args.db_path is None:
        parser.error("Provide either --site for site-folder collection or --db-path for a single local.db file.")

    return args



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


def resolve_site_root(
    site: str,
    site_path_arg: str | None,
    root_dir: Path,
    timing_subdir: str,
) -> Path:
    """
    Resolve the source site folder for collection.

    Input:
        Site ID plus either an explicit site path or root/timing-subdir pair.
    Output:
        Existing site folder path used for case discovery.
    Assumptions:
        Explicit ``--site-path`` takes precedence so output naming can stay tied
        to the site ID while the source folder keeps its original on-disk label.
    """
    if site_path_arg is not None:
        site_root = Path(site_path_arg)
        if not site_root.exists():
            raise FileNotFoundError(f"Explicit --site-path not found: {site_root}")
        return site_root

    return find_site_root(root_dir, timing_subdir, site)


def expected_case_prefix(site: str) -> str | None:
    """
    Infer the canonical case-folder prefix from a site ID.

    Input:
        Site ID such as ``Stanford_064``.
    Output:
        Expected case-folder prefix like ``064_`` when the site ID ends in a
        three-digit code, otherwise ``None``.
    Assumptions:
        Legacy site folders may contain auxiliary/non-canonical case folders
        whose prefixes do not match the site's numeric code.
    """
    match = re.search(r"_(\d{3})$", str(site).strip())
    if match is None:
        return None
    return f"{match.group(1)}_"


def list_case_folders(site_root: Path, site: str) -> tuple[list[Path], list[str]]:
    case_dirs = [p for p in site_root.iterdir() if p.is_dir()]
    skipped_names: list[str] = []
    prefix = expected_case_prefix(site)
    if prefix is not None:
        skipped_names = [p.name for p in case_dirs if not p.name.startswith(prefix)]
        case_dirs = [p for p in case_dirs if p.name.startswith(prefix)]
    case_dirs.sort()
    skipped_names.sort()
    return case_dirs, skipped_names


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


def read_sessions_from_db(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query("SELECT * FROM Sessions", conn)
    finally:
        conn.close()


def infer_pt_id_from_db(db_path: Path, auditlog: pd.DataFrame, sessions: pd.DataFrame) -> str:
    candidates: list[str] = []

    if "PatientId" in auditlog.columns:
        candidates.extend(
            str(v).strip()
            for v in auditlog["PatientId"].dropna().unique().tolist()
            if str(v).strip()
        )

    if not sessions.empty:
        for col in ["PatientId", "DisplayName", "FirstName", "LastName"]:
            if col in sessions.columns:
                candidates.extend(
                    str(v).strip()
                    for v in sessions[col].dropna().tolist()
                    if str(v).strip()
                )

    if candidates:
        return candidates[0]

    return db_path.parent.name or db_path.stem


def _valid_session_timestamp(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text in {"0001-01-01 00:00:00", "00010101"}:
        return None

    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts) or ts.year < 2000:
        return None

    return text


def inject_session_events(auditlog: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """
    Add synthetic audit rows from session-level timestamps when available.
    """
    if auditlog.empty or sessions.empty:
        return auditlog

    out = auditlog.copy()
    template = out.iloc[[0]].copy()

    event_fields = {
        "TimePatientSedatedAt": "Ready4Urology",
        "TimeUaInsertedAt": "DeviceInsertionEnds",
        "TimePatientTransferredAt": "PatientTransferEnds",
    }

    next_id = None
    if "Id" in out.columns:
        next_id = pd.to_numeric(out["Id"], errors="coerce").max()
        next_id = int(next_id) + 1 if pd.notna(next_id) else 1

    extra_rows: list[pd.DataFrame] = []
    for _, session_row in sessions.iterrows():
        for field_name, event_name in event_fields.items():
            if field_name not in session_row.index:
                continue

            ts_text = _valid_session_timestamp(session_row[field_name])
            if ts_text is None:
                continue

            is_duplicate = (
                (out.get("AuditRecordBase_Type") == event_name)
                & (out.get("TimeStamp") == ts_text)
            ).any()
            if is_duplicate:
                continue

            row = template.copy()
            row["AuditRecordBase_Type"] = event_name
            row["TimeStamp"] = ts_text
            if next_id is not None:
                row["Id"] = next_id
                next_id += 1
            extra_rows.append(row)

    if not extra_rows:
        return out

    out = pd.concat([out, *extra_rows], ignore_index=True)
    out = out.sort_values("TimeStamp").reset_index(drop=True)
    return out


# ------------------------------ MAIN LOGIC --------------------------------- #

def main():
    args = parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.db_path is not None:
        db_path = Path(args.db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"DB file not found: {db_path}")

        print(f"Direct DB mode: {db_path}")
        auditlog = read_auditlog_from_db(db_path)
        if auditlog.empty:
            print("AuditLogRecords table is empty. Nothing to write.")
            return

        sessions = read_sessions_from_db(db_path)
        auditlog = inject_session_events(auditlog, sessions)
        pt_id = args.pt_id or infer_pt_id_from_db(db_path, auditlog, sessions)
        site_name = args.site or db_path.stem

        auditlog["Site"] = site_name
        auditlog["PtId"] = pt_id
        auditlog["Pt"] = 1
        auditlog["CaseFolder"] = str(db_path.parent)

        out_path = outdir / f"auditlogs_{site_name}.csv"
        auditlog.to_csv(out_path, index=False)

        print(f"Rows in AuditLogRecords: {len(auditlog)}")
        print(f"PtId used: {pt_id}")
        print(f"Saved to: {out_path}")
        return

    root_dir = resolve_root(args.root)
    yearlist = build_year_list(args.years)
    site_root = resolve_site_root(args.site, args.site_path, root_dir, args.timing_subdir)

    tempfolder = outdir / "_temp_collect"
    tempfolder.mkdir(parents=True, exist_ok=True)

    print(f"Root dir:   {root_dir}")
    print(f"Site:       {args.site}")
    print(f"Years:      {yearlist}")
    print(f"Site root:  {site_root}")
    print(f"Temp root:  {tempfolder}")

    case_folders, skipped_case_dirs = list_case_folders(site_root, args.site)
    if args.limit_cases is not None:
        case_folders = case_folders[:args.limit_cases]

    print(f"Found {len(case_folders)} case folders to process.\n")
    if skipped_case_dirs:
        print(
            "[INFO] Skipping non-canonical case folders for site "
            f"{args.site}: {', '.join(skipped_case_dirs)}\n"
        )

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

        try:
            sessions = read_sessions_from_db(db_path)
        except Exception:
            sessions = pd.DataFrame()
        auditlog = inject_session_events(auditlog, sessions)

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
