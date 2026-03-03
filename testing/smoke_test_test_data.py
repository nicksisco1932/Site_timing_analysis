#!/usr/bin/env python
"""
Run a repeatable smoke test against test_data/local.db.

This is intentionally narrow:
- collect raw AuditLogRecords from a direct local.db path
- run state mapping
- build timing summary
- run time sanity
- build Gantt-ready plots
- print unmapped event types so parity work has a concrete target
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd


def run_step(repo_root: Path, *args: str) -> None:
    cmd = [sys.executable, *args]
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    print(f"CMD: {' '.join(args)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:")
        print(result.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = repo_root / "test_data" / "local.db"
    outdir = repo_root / "test_output" / "test_data_smoke"
    outdir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise FileNotFoundError(f"Expected test DB not found: {db_path}")

    site = "TESTDATA"

    run_step(
        repo_root,
        "tulsa_collect_auditlogs.py",
        "--db-path",
        str(db_path),
        "--site",
        site,
        "--outdir",
        str(outdir),
    )
    run_step(
        repo_root,
        "tulsa_state_machine.py",
        "--infile",
        str(outdir / f"auditlogs_{site}.csv"),
        "--outdir",
        str(outdir),
    )
    run_step(
        repo_root,
        "tulsa_build_timing_summary.py",
        "--states-csv",
        str(outdir / f"auditlogs_{site}_states.csv"),
        "--outdir",
        str(outdir),
    )
    run_step(
        repo_root,
        "tulsa_time_sanity.py",
        "--states-csv",
        str(outdir / f"auditlogs_{site}_states.csv"),
        "--outdir",
        str(outdir),
    )
    run_step(
        repo_root,
        "tulsa_plot_timing.py",
        "--summary-csv",
        str(outdir / f"timing_summary_{site}.csv"),
        "--states-csv",
        str(outdir / f"auditlogs_{site}_states.csv"),
        "--outdir",
        str(outdir / "plots"),
        "--site",
        site,
    )
    run_step(
        repo_root,
        "tulsa_gantt_plots.py",
        "--summary-csv",
        str(outdir / f"timing_summary_{site}.csv"),
        "--outdir",
        str(outdir / "plots_summary"),
    )

    states_df = pd.read_csv(outdir / f"auditlogs_{site}_states.csv")
    unmapped = (
        states_df.loc[states_df["CurrentState"].fillna("") == "", "AuditRecordBase_Type"]
        .value_counts()
        .rename_axis("AuditRecordBase_Type")
        .reset_index(name="Count")
    )
    summary_df = pd.read_csv(outdir / f"timing_summary_{site}.csv")

    print("Summary:")
    print(summary_df.to_string(index=False))

    print("\nTop unmapped event types:")
    if unmapped.empty:
        print("None")
    else:
        print(unmapped.to_string(index=False))

    plot_files = sorted(p.name for p in (outdir / "plots").glob("*.png"))
    summary_plot_files = sorted(p.name for p in (outdir / "plots_summary").glob("*.png"))

    print("\nGenerated plots:")
    for name in plot_files + summary_plot_files:
        print(name)

    print(f"\nOutput directory: {outdir}")


if __name__ == "__main__":
    main()
