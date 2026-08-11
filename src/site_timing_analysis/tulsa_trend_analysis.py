#!/usr/bin/env python
"""
tulsa_trend_analysis.py

Trend and variability analysis for TULSA timing data.

Inputs (per site):
  - timing_summary_<site>.csv

Outputs:
  - plots/
      site_<site>_MRITotal_trend.png
      site_<site>_Treating_trend.png
      site_<site>_phase_trends.png
      site_<site>_phase_CV_bar.png
      site_<site>_gantt_<PtId>.png
  - stats/
      phase_variability_<site>.csv
      outliers_<site>.csv
      site_stats_<site>.json
"""

# Project: Site Timing Analysis
# File: src/site_timing_analysis/tulsa_trend_analysis.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Implements the legacy-compatible TULSA trend analysis workflow script.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from .tulsa_workflow import PLOTTED_STATES


# ------------------------ Helpers ------------------------ #

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def infer_id_column(df: pd.DataFrame) -> str:
    """
    Prefer PtId, then Pt. If neither exists, create CaseIndex.
    """
    if "PtId" in df.columns:
        return "PtId"
    if "Pt" in df.columns:
        return "Pt"
    # Fallback: create a synthetic ID
    df["CaseIndex"] = np.arange(1, len(df) + 1)
    return "CaseIndex"


def get_phase_columns(df: pd.DataFrame):
    """
    Infer phase columns from known names.
    Adjust here if you add/remove columns in timing_summary.
    """
    candidate_cols = [
        *PLOTTED_STATES,
        "MRITotal",
        "ProcedureTotal",
    ]
    phases = [c for c in candidate_cols if c in df.columns]
    return phases


def coerce_numeric_with_cap(df: pd.DataFrame,
                            cols,
                            max_minutes: float | None = None) -> pd.DataFrame:
    """
    Convert columns to numeric, and optionally treat any values > max_minutes
    as NaN (database garbage like 30000 minutes).
    """
    for col in cols:
        if col not in df.columns:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if max_minutes is not None:
            mask_bad = df[col] > max_minutes
            n_bad = int(mask_bad.sum())
            if n_bad > 0:
                print(f"  [INFO] {col}: {n_bad} values > {max_minutes} min "
                      f"set to NaN (likely DB artifacts).")
                df.loc[mask_bad, col] = np.nan
    return df


# ------------------------ Plotting ------------------------ #

def line_plot_by_id(df: pd.DataFrame,
                    idcol: str,
                    ycol: str,
                    outpath: Path,
                    title: str,
                    ylabel: str):
    """
    Plot y versus patient ID. X axis is positional index; tick labels are IDs.
    """
    if ycol not in df.columns:
        print(f"  [WARN] {ycol} not in dataframe, skipping {title}")
        return

    tmp = df[[idcol, ycol]].copy()
    tmp = tmp.dropna(subset=[ycol])
    if tmp.empty:
        print(f"  [WARN] No valid data to plot for {ycol}")
        return

    ii_vals = np.arange(len(tmp))
    plt.figure(figsize=(12, 5))
    plt.plot(ii_vals, tmp[ycol].values, marker="o", linestyle="-")
    plt.title(title)
    plt.xlabel(idcol)
    plt.ylabel(ylabel)
    plt.xticks(ii_vals, tmp[idcol].astype(str).values,
               rotation=90, ha="center", fontsize=7)
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()
    print(f"  Saved plot: {outpath}")


def multi_phase_trend_plot_by_id(df: pd.DataFrame,
                                 idcol: str,
                                 phase_cols,
                                 outpath: Path,
                                 title: str):
    """
    Multiple phase curves versus patient ID.
    """
    plt.figure(figsize=(14, 7))
    ii_vals = np.arange(len(df))

    for col in phase_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        mask = series.notna()
        if not mask.any():
            continue
        plt.plot(
            ii_vals[mask],
            series[mask].values,
            marker="o",
            linestyle="-",
            label=col,
        )

    plt.title(title)
    plt.xlabel(idcol)
    plt.ylabel("Duration (min)")
    plt.xticks(ii_vals, df[idcol].astype(str).values,
               rotation=90, ha="center", fontsize=6)
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()
    print(f"  Saved plot: {outpath}")


def cv_bar_plot(cv_df: pd.DataFrame, outpath: Path, title: str):
    plt.figure(figsize=(10, 5))
    plot_df = cv_df.sort_values("CV", ascending=False)
    plt.bar(plot_df["Phase"], plot_df["CV"])
    plt.title(title)
    plt.ylabel("Coefficient of variation (CV)")
    plt.xticks(rotation=45, ha="right")
    plt.grid(True, axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()
    print(f"  Saved CV bar plot: {outpath}")


def gantt_for_cases(df: pd.DataFrame,
                    phase_order,
                    outdir: Path,
                    site: str,
                    idcol: str,
                    max_cases: int = 5):
    """
    Build Gantt-style plots for a subset of cases.
    We choose the top N MRITotal cases after cleaning.
    """
    if "MRITotal" not in df.columns:
        print("No MRITotal column, skipping Gantt plots.")
        return

    tmp = df.copy()
    tmp["MRITotal_num"] = pd.to_numeric(tmp["MRITotal"], errors="coerce")
    tmp = tmp.dropna(subset=["MRITotal_num"])
    if tmp.empty:
        print("No numeric MRITotal data, skipping Gantt plots.")
        return

    tmp = tmp.sort_values("MRITotal_num", ascending=False).head(max_cases)

    print(f"Generating Gantt plots for {len(tmp)} cases "
          f"(longest MRITotal).")

    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
        "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
        "#bcbd22", "#17becf", "#aec7e8", "#ffbb78"
    ]

    for ii, (_, row) in enumerate(tmp.iterrows(), start=1):
        ptid = row.get(idcol, f"case_{ii}")
        fig, ax = plt.subplots(figsize=(10, 4))

        start = 0.0
        y = 10
        height = 9

        for kk, phase in enumerate(phase_order):
            if phase not in row.index:
                continue
            dur = row[phase]
            try:
                dur = float(dur)
            except Exception:
                continue
            if np.isnan(dur) or dur <= 0:
                continue
            ax.broken_barh(
                [(start, dur)],
                (y, height),
                facecolors=colors[kk % len(colors)],
                edgecolors="black",
                linewidth=0.5,
                alpha=0.8,
            )
            ax.text(
                start + dur / 2.0,
                y + height / 2.0,
                phase,
                ha="center",
                va="center",
                fontsize=7,
                color="white",
            )
            start += dur

        ax.set_xlabel("Minutes")
        ax.set_yticks([])
        ax.set_title(f"Workflow Gantt – {site} – {ptid}")
        ax.grid(True, axis="x", linestyle="--", alpha=0.4)
        plt.tight_layout()

        outpath = outdir / f"site_{site}_gantt_{ptid}.png"
        plt.savefig(outpath, dpi=200)
        plt.close()
        print(f"  Saved Gantt plot: {outpath}")


# ------------------------ Analysis ------------------------ #

def compute_phase_stats(df: pd.DataFrame, phases, site: str):
    rows = []
    for col in phases:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        mean = float(series.mean())
        median = float(series.median())
        sd = float(series.std(ddof=1)) if len(series) > 1 else np.nan
        cv = float(sd / mean) if mean > 0 and not np.isnan(sd) else np.nan
        minv = float(series.min())
        maxv = float(series.max())
        rows.append(
            dict(
                Site=site,
                Phase=col,
                N=int(len(series)),
                Mean=mean,
                Median=median,
                SD=sd,
                CV=cv,
                Min=minv,
                Max=maxv,
            )
        )

    stats_df = pd.DataFrame(rows)
    return stats_df


def detect_outliers(df: pd.DataFrame, phases, site: str, z_thresh=3.0):
    records = []
    for col in phases:
        series = pd.to_numeric(df[col], errors="coerce")
        mask_valid = series.notna()
        if not mask_valid.any():
            continue
        x = series[mask_valid]
        mean = x.mean()
        sd = x.std(ddof=1)
        if sd == 0 or np.isnan(sd):
            continue
        z = (x - mean) / sd
        out_mask = z.abs() >= z_thresh
        if not out_mask.any():
            continue
        for idx in x.index[out_mask]:
            rec = dict(
                Site=site,
                Pt=df.at[idx, "Pt"] if "Pt" in df.columns else None,
                PtId=df.at[idx, "PtId"] if "PtId" in df.columns else None,
                Phase=col,
                Value=float(series.at[idx]),
                Z=float(z.at[idx]),
            )
            records.append(rec)

    out_df = pd.DataFrame(records)
    return out_df


def build_site_stats_json(stats_df: pd.DataFrame,
                          site: str,
                          outliers_df: pd.DataFrame,
                          n_cases: int):
    site_stats = {
        "site": site,
        "n_cases": int(n_cases),
        "phases": {},
        "outliers": {
            "n_outliers": int(len(outliers_df)),
            "z_threshold": 3.0,
        },
    }
    for _, row in stats_df.iterrows():
        phase = row["Phase"]
        site_stats["phases"][phase] = {
            "N": int(row["N"]),
            "Mean": row["Mean"],
            "Median": row["Median"],
            "SD": row["SD"],
            "CV": row["CV"],
            "Min": row["Min"],
            "Max": row["Max"],
        }
    return site_stats


# ------------------------ Main ------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description="Trend and variability analysis for TULSA timing data."
    )
    parser.add_argument("--site", required=True,
                        help="Site name, e.g., Stanford_064")
    parser.add_argument("--analysis-root", required=True,
                        help="Folder containing timing_summary CSV")
    parser.add_argument("--summary-file", default=None,
                        help="Override timing_summary filename if needed")
    parser.add_argument("--with-gantt", action="store_true",
                        help="Generate Gantt plots for longest MRITotal cases")
    parser.add_argument("--max-minutes", type=float, default=1000.0,
                        help="Values above this (per phase) are treated as "
                             "NaN (to drop DB artifacts like 30000 min).")
    parser.add_argument("--gantt-cases", type=int, default=5,
                    help="Number of longest MRITotal cases to plot as Gantts")

    args = parser.parse_args()

    site = args.site
    analysis_root = Path(args.analysis_root)

    if args.summary_file is not None:
        summary_path = analysis_root / args.summary_file
    else:
        summary_path = analysis_root / f"timing_summary_{site}.csv"

    if not summary_path.exists():
        raise FileNotFoundError(f"Timing summary file not found: {summary_path}")

    plots_dir = analysis_root / "plots"
    stats_dir = analysis_root / "stats"
    ensure_dir(plots_dir)
    ensure_dir(stats_dir)

    # ---- Load summary ----
    print(f"Reading timing summary: {summary_path}")
    df = pd.read_csv(summary_path)

    idcol = infer_id_column(df)
    print(f"Using ID column for x-axis: {idcol}")

    phases = get_phase_columns(df)
    if not phases:
        raise RuntimeError("No recognizable phase columns found in summary.")

    # Ensure numeric + cap outliers
    df = coerce_numeric_with_cap(df, phases, max_minutes=args.max_minutes)
    # After: df = coerce_numeric_with_cap(df, phases, max_minutes=args.max_minutes)

    weird = df[
        (df["Treating"].notna()) &
        (
            (df["Treating"] < 1.0) |   # less than 1 min
            (df["Treating"] > 240.0)   # more than 4 hours
        )
    ]

    if not weird.empty:
        weird_csv = stats_dir / f"treating_weird_{site}.csv"
        weird.to_csv(weird_csv, index=False)
        print(f"  [INFO] Wrote treating weirdness table: {weird_csv}")


    # ---- STEP 1: MRITotal trend ----
    print("STEP 1: MRITotal trend vs ID...")
    if "MRITotal" in df.columns:
        line_plot_by_id(
            df,
            idcol,
            "MRITotal",
            plots_dir / f"site_{site}_MRITotal_trend.png",
            title=f"{site}: MRITotal trend by case",
            ylabel="MRITotal (min)",
        )
    else:
        print("  [WARN] MRITotal column not found, skipping MRITotal trend.")

    # ---- STEP 2: Treating time trend ----
    print("STEP 2: Treating time trend vs ID...")
    if "Treating" in df.columns:
        line_plot_by_id(
            df,
            idcol,
            "Treating",
            plots_dir / f"site_{site}_Treating_trend.png",
            title=f"{site}: Treating time trend by case",
            ylabel="Treating (min)",
        )
    else:
        print("  [WARN] Treating column not found, skipping Treating trend.")

    # ---- STEP 3: Multi-phase trends ----
    print("STEP 3: Phase trend curves vs ID...")
    phase_trend_cols = [c for c in phases if c not in ("MRITotal", "ProcedureTotal")]
    multi_phase_trend_plot_by_id(
        df,
        idcol,
        phase_trend_cols,
        plots_dir / f"site_{site}_phase_trends.png",
        title=f"{site}: Phase duration trends by case",
    )

    # ---- STEP 4: Variability & CV ----
    print("STEP 4: Variability and CV...")
    stats_df = compute_phase_stats(df, phases, site)
    stats_csv = stats_dir / f"phase_variability_{site}.csv"
    stats_df.to_csv(stats_csv, index=False)
    print(f"  Saved phase variability table: {stats_csv}")

    cv_plot_path = plots_dir / f"site_{site}_phase_CV_bar.png"
    if not stats_df.empty:
        cv_bar_plot(stats_df[["Phase", "CV"]], cv_plot_path,
                    title=f"{site}: Phase CV")

    # ---- STEP 5: Outlier detection ----
    print("STEP 5: Outlier detection (z >= 3.0)...")
    outliers_df = detect_outliers(df, phases, site, z_thresh=3.0)
    outliers_csv = stats_dir / f"outliers_{site}.csv"
    if not outliers_df.empty:
        outliers_df.to_csv(outliers_csv, index=False)
        print(f"  Saved outlier table: {outliers_csv}")
    else:
        print("  No outliers detected at z >= 3.0.")

    # ---- STEP 6: Gantt plots ----
    if args.with_gantt:
        print("STEP 6: Gantt plots for longest MRITotal cases...")
        gantt_phase_order = [
            c for c in [
                "Room ready",
                "Alignment",
                "Coarse",
                "Detailed",
                "Planning start angle",
                "Initialization",
                "TULSA QA",
                "Treating",
                "Post-treatment scans & Device removal",
                "Review",
                "Paused",
            ] if c in df.columns
        ]
        gantt_for_cases(df, gantt_phase_order, plots_dir, site, idcol,
                    max_cases=args.gantt_cases)

    # ---- STEP 7: Site stats JSON ----
    print("STEP 7: Site stats JSON...")
    site_stats = build_site_stats_json(stats_df, site, outliers_df,
                                       n_cases=len(df))
    json_path = stats_dir / f"site_stats_{site}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(site_stats, f, indent=2)
    print(f"  Saved site stats JSON: {json_path}")

    print("Done.")


if __name__ == "__main__":
    main()
