from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd


def run_step(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(args)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    return result


def run_testdata_pipeline(repo_root: Path, outdir: Path) -> dict[str, Path]:
    site = "TESTDATA"
    db_path = repo_root / "test_data" / "local.db"
    outdir.mkdir(parents=True, exist_ok=True)

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

    return {
        "auditlogs": outdir / f"auditlogs_{site}.csv",
        "states": outdir / f"auditlogs_{site}_states.csv",
        "summary": outdir / f"timing_summary_{site}.csv",
        "sanity": outdir / f"time_sanity_{site}.csv",
        "plots_dir": outdir / "plots",
        "plots_summary_dir": outdir / "plots_summary",
    }


def test_test_data_pipeline_outputs_expected_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outputs = run_testdata_pipeline(repo_root, tmp_path / "pipeline")

    for path in [outputs["auditlogs"], outputs["states"], outputs["summary"], outputs["sanity"]]:
        assert path.exists(), f"Expected output missing: {path}"

    plot_names = sorted(p.name for p in outputs["plots_dir"].glob("*.png"))
    summary_plot_names = sorted(p.name for p in outputs["plots_summary_dir"].glob("*.png"))

    assert "gantt_all_patients.png" in plot_names
    assert "per_patient_stacked_phases.png" in plot_names
    assert "gantt_all_cases.png" in summary_plot_names


def test_test_data_pipeline_has_no_unmapped_state_rows(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outputs = run_testdata_pipeline(repo_root, tmp_path / "pipeline")

    states_df = pd.read_csv(outputs["states"])
    unmapped = states_df["CurrentState"].fillna("").eq("").sum()

    assert unmapped == 0
    assert states_df["PtId"].nunique() == 1

    expected_states = {
        "TULSA QA",
        "Room ready",
        "Patient positioning & induction",
        "Device insertion",
        "Device repositioning",
        "Alignment",
        "Coarse",
        "Detailed",
        "Planning start angle",
        "Initialization",
        "Treating",
        "Paused",
        "Post-treatment scans & Device removal",
        "Patient recovery & transfer",
    }
    assert expected_states.issubset(set(states_df["CurrentState"].astype(str)))


def test_test_data_summary_matches_expected_shape(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outputs = run_testdata_pipeline(repo_root, tmp_path / "pipeline")

    summary_df = pd.read_csv(outputs["summary"])
    sanity_df = pd.read_csv(outputs["sanity"])

    assert len(summary_df) == 1
    assert summary_df.at[0, "PtId"] == "064_01-137"
    assert summary_df.at[0, "MRITotal"] > 0
    assert summary_df.at[0, "ProcedureTotal"] >= summary_df.at[0, "MRITotal"]
    assert summary_df.at[0, "Treating"] > 0
    assert summary_df.at[0, "Device insertion"] > 0
    assert summary_df.at[0, "Device repositioning"] > 0
    assert summary_df.at[0, "Initialization"] > 0

    assert len(sanity_df) == 1
    assert bool(sanity_df.at[0, "crossed_noon"]) is True
