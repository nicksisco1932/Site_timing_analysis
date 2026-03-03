#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_site_pipeline.py  (v0.1)

Unified, robust TULSA timing pipeline for a single site.

Steps
-----
1. Collect raw AuditLogRecords:
       tulsa_collect_auditlogs.py

2. Map to workflow states + per-row durations:
       tulsa_state_machine.py

3. Build per-patient timing summary:
       tulsa_build_timing_summary.py

4. Generate figures and stats:
   - tulsa_plot_timing.py      (stacked per-patient, boxplots, histograms, Gantt)
   - tulsa_box_jitter.py       (box + jitter per phase)
   - tulsa_trend_analysis.py   (trends, CVs, outlier tables, JSON summary)

Outputs
-------
Analysis root:
    <analysis_root>/<DATE>_<SITE_LABEL>/

Key files:
    auditlogs_<site>.csv
    auditlogs_<site>_states.csv
    timing_summary_<site>.csv
    plots/
    stats/    (from tulsa_trend_analysis.py)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def default_analysis_root() -> Path:
    """
    Default analysis root:
        C:/Users/<USERNAME>/OneDrive - Profound Medical/Documents/Analysis
    """
    username = os.environ.get("USERNAME", "NicholasSisco")
    return Path(
        f"C:/Users/{username}/OneDrive - Profound Medical/Documents/Analysis"
    )


def run_step(name: str, cmd: list[str]) -> None:
    """
    Run a subprocess step with logging and error handling.
    """
    print("\n" + "=" * 70)
    print(f"[STEP] {name}")
    print("-" * 70)
    print("Command:")
    print("  " + " ".join(cmd))
    print("-" * 70)

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[ERROR] {name} failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    print(f"[OK] {name} completed successfully.")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified site-level TULSA timing pipeline."
    )

    parser.add_argument(
        "--site",
        required=True,
        help="Site folder name under Timing Data, e.g. 'Stanford_064', 'MayoRoch_075'.",
    )

    parser.add_argument(
        "--years",
        default="All",
        help="Year selection for case inclusion: "
             "All, CurrentYear, PastYears, or explicit year (e.g., 2023).",
    )

    parser.add_argument(
        "--site-label",
        default=None,
        help="Short label for the site in output folder names/titles. "
             "Default: same as --site.",
    )

    parser.add_argument(
        "--date",
        default=None,
        help="Date tag YYYYMMDD for the analysis folder. "
             "Default: today's date.",
    )

    parser.add_argument(
        "--analysis-root",
        default=None,
        help="Root for analysis outputs. "
             "Default: C:/Users/<USERNAME>/OneDrive - Profound Medical/Documents/Analysis",
    )

    parser.add_argument(
        "--root",
        default=None,
        help="Root directory where 'Profound Medical' lives for auditlogs collection. "
             "If omitted, tulsa_collect_auditlogs.py uses its own default.",
    )

    parser.add_argument(
        "--timing-subdir",
        default="Clinical Science Team - Genius Services/Timing Data",
        help="Subdirectory under root containing timing folders. "
             "Only used if forwarding --root to tulsa_collect_auditlogs.py.",
    )

    # Skips for debugging
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="Skip Step 1 (collect auditlogs).",
    )
    parser.add_argument(
        "--skip-states",
        action="store_true",
        help="Skip Step 2 (state machine).",
    )
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Skip Step 3 (timing summary).",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Skip Step 4 (plots + trends).",
    )

    parser.add_argument(
        "--no-filter-outliers",
        action="store_true",
        help="Disable duration_sec > 6h filter in tulsa_build_timing_summary.py.",
    )

    parser.add_argument(
        "--trend-with-gantt",
        action="store_true",
        help="If set, tulsa_trend_analysis.py will generate per-case Gantts "
             "for longest MRITotal cases.",
    )

    return parser.parse_args()


# ----------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    site = args.site
    site_label = args.site_label or site

    # Determine date tag
    if args.date is not None:
        date_tag = args.date
    else:
        date_tag = datetime.today().strftime("%Y%m%d")

    # Analysis root and output folder
    if args.analysis_root is not None:
        analysis_root = Path(args.analysis_root)
    else:
        analysis_root = default_analysis_root()

    outdir = analysis_root / f"{date_tag}_{site_label}"
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  TULSA SITE TIMING PIPELINE")
    print("=" * 70)
    print(f"  Site:          {site}")
    print(f"  Site label:    {site_label}")
    print(f"  Years:         {args.years}")
    print(f"  Date tag:      {date_tag}")
    print(f"  Analysis root: {analysis_root}")
    print(f"  Output dir:    {outdir}")
    print("=" * 70)

    # The package lives under src/site_timing_analysis; subprocess entrypoints stay at repo root.
    repo_root = Path(__file__).resolve().parents[2]
    python_exe = sys.executable

    # ------------------------------------------------------------------
    # STEP 1: Collect auditlogs
    # ------------------------------------------------------------------
    infile = outdir / f"auditlogs_{site}.csv"

    if not args.skip_collect:
        collect_script = repo_root / "tulsa_collect_auditlogs.py"
        cmd = [
            python_exe,
            str(collect_script),
            "--site",
            site,
            "--years",
            args.years,
            "--outdir",
            str(outdir),
        ]
        if args.root is not None:
            cmd.extend(["--root", args.root])
            cmd.extend(["--timing-subdir", args.timing_subdir])

        run_step("STEP 1: Collect AuditLogRecords", cmd)

        if not infile.exists():
            print(f"[ERROR] Expected auditlog file not found:\n  {infile}")
            sys.exit(1)
    else:
        print("\n[INFO] Skipping STEP 1 (collect auditlogs) per --skip-collect.")
        if not infile.exists():
            print(f"[ERROR] --skip-collect set but auditlog file missing:\n  {infile}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # STEP 2: State machine
    # ------------------------------------------------------------------
    states_csv = outdir / f"auditlogs_{site}_states.csv"

    if not args.skip_states:
        state_script = repo_root / "tulsa_state_machine.py"
        cmd = [
            python_exe,
            str(state_script),
            "--infile",
            str(infile),
            "--outdir",
            str(outdir),
        ]
        run_step("STEP 2: Map workflow states + durations", cmd)

        if not states_csv.exists():
            print(f"[ERROR] Expected state-enriched file not found:\n  {states_csv}")
            sys.exit(1)
    else:
        print("\n[INFO] Skipping STEP 2 (state machine) per --skip-states.")
        if not states_csv.exists():
            print(f"[ERROR] --skip-states set but states file missing:\n  {states_csv}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # STEP 3: Timing summary
    # ------------------------------------------------------------------
    summary_csv = outdir / f"timing_summary_{site}.csv"

    if not args.skip_summary:
        build_script = repo_root / "tulsa_build_timing_summary.py"
        cmd = [
            python_exe,
            str(build_script),
            "--states-csv",
            str(states_csv),
            "--outdir",
            str(outdir),
        ]
        if not args.no_filter_outliers:
            cmd.append("--filter-outliers")

        run_step("STEP 3: Build per-patient timing summary", cmd)

        if not summary_csv.exists():
            print(f"[ERROR] Expected timing summary not found:\n  {summary_csv}")
            sys.exit(1)
    else:
        print("\n[INFO] Skipping STEP 3 (timing summary) per --skip-summary.")
        if not summary_csv.exists():
            print(f"[ERROR] --skip-summary set but summary file missing:\n  {summary_csv}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # STEP 4: Plots & trends
    # ------------------------------------------------------------------
    if args.skip_plots:
        print("\n[INFO] Skipping STEP 4 (plots + trends) per --skip-plots.")
        print("\nPipeline complete (collection + states + summary only).")
        return

    plots_dir = outdir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    # 4a. Summary plots + Gantt from states
    plot_script = repo_root / "tulsa_plot_timing.py"
    cmd_plot = [
        python_exe,
        str(plot_script),
        "--summary-csv",
        str(summary_csv),
        "--states-csv",
        str(states_csv),
        "--outdir",
        str(plots_dir),
        "--site",
        site,
    ]
    run_step("STEP 4a: Summary plots (stacked, box, hist, Gantt)", cmd_plot)

    # 4b. Box + jitter per phase
    box_script = repo_root / "tulsa_box_jitter.py"
    cmd_box = [
        python_exe,
        str(box_script),
        "--summary-csv",
        str(summary_csv),
        "--outdir",
        str(plots_dir),
        "--basename",
        "timing_boxjitter",
        "--title",
        f"{site} – per-phase timing distribution (box + jitter)",
    ]
    run_step("STEP 4b: Box + jitter plot", cmd_box)

    # 4c. Trend / variability / stats
    trend_script = repo_root / "tulsa_trend_analysis.py"
    cmd_trend = [
        python_exe,
        str(trend_script),
        "--site",
        site,
        "--analysis-root",
        str(outdir),
    ]
    if args.trend_with_gantt:
        cmd_trend.append("--with-gantt")

    run_step("STEP 4c: Trend + variability analysis", cmd_trend)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print(f"  Summary CSV: {summary_csv}")
    print(f"  Plots:       {plots_dir}")
    print(f"  Stats:       {outdir / 'stats'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
