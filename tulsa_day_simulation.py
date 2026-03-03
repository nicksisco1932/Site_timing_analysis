#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tulsa_day_simulation.py  (v0.2)
-------------------------------
Monte Carlo simulation of full clinical days using observed state
durations from timing_summary_<site>.csv.

Workflow per simulated day:
    - Anesthesia induction
    - Pre-insertion buffer
    - Device insertion
    - Alignment
    - Coarse
    - Detailed
    - Planning start angle
    - Treating
    - Paused
    - (NEW) Second planning segment (fixed duration)
    - (NEW) Extra treatment segment (fixed duration)
    - Post-treatment scans & Device removal

Durations for TULSA states (Alignment, Coarse, Detailed, Planning,
Treating, Paused, Post-treatment) are sampled from real cases in
timing_summary_<site>.csv (bootstrap by rows).

Additional fixed segments:
    - extra-plan-minutes  (default 20)
    - extra-treat-minutes (default 60)

Outputs:
    - day_sim_<site>.csv          (per-simulation metrics)
    - day_sim_summary_<site>.csv  (aggregated metrics)
"""

import argparse
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd


# ----------------------- helpers ----------------------- #

STATE_COLS = [
    # "Room ready",  # removed from simulation
    "Alignment",
    "Coarse",
    "Detailed",
    "Planning start angle",
    "Treating",
    "Paused",
    "Post-treatment scans & Device removal",
]


def parse_time_hhmm(s: str) -> dtime:
    s = s.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Could not parse time '{s}'. Expected HH:MM or HH:MM:SS.")


def minutes_to_td(minutes: float) -> timedelta:
    return timedelta(minutes=float(minutes))


def load_timing_summary(summary_path: Path) -> pd.DataFrame:
    df = pd.read_csv(summary_path)
    # Ensure numeric + non-negative for state columns
    for col in STATE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].fillna(0.0).clip(lower=0.0)
    return df


def simulate_one_day(
    case_row: pd.Series,
    anest_start_t: dtime,
    anest_minutes: float,
    pre_insert_gap_minutes: float,
    insert_minutes: float,
    cutoff_t: dtime,
    extra_plan_minutes: float,
    extra_treat_minutes: float,
) -> dict:
    """
    Simulate a single day using durations from `case_row` and fixed
    anesthesia / insertion / extra-plan / extra-treat parameters.

    Returns a dict with key timestamps and flags.
    """
    # Use an arbitrary reference date; only time-of-day matters
    base_date = datetime(2025, 1, 1)

    # Anesthesia block
    anest_start = datetime.combine(base_date.date(), anest_start_t)
    anest_end = anest_start + minutes_to_td(anest_minutes)

    # Pre-insertion gap
    pre_insert_end = anest_end + minutes_to_td(pre_insert_gap_minutes)

    # Insertion block
    insert_start = pre_insert_end
    insert_end = insert_start + minutes_to_td(insert_minutes)

    # TULSA states start after insertion
    current = insert_end

    def get_dur(col: str) -> float:
        if col in case_row.index:
            return float(case_row[col])
        return 0.0

    # Durations (minutes) from sampled row
    align_dur = get_dur("Alignment")
    coarse_dur = get_dur("Coarse")
    detailed_dur = get_dur("Detailed")
    plan_dur = get_dur("Planning start angle")
    treat_dur = get_dur("Treating")
    paused_dur = get_dur("Paused")
    post_dur = get_dur("Post-treatment scans & Device removal")

    # --- First imaging + planning + treating block ---

    align_start = current
    align_end = align_start + minutes_to_td(align_dur)

    coarse_start = align_end
    coarse_end = coarse_start + minutes_to_td(coarse_dur)

    detailed_start = coarse_end
    detailed_end = detailed_start + minutes_to_td(detailed_dur)

    plan_start = detailed_end
    plan_end = plan_start + minutes_to_td(plan_dur)

    treat_start = plan_end
    treat_end = treat_start + minutes_to_td(treat_dur)

    paused_start = treat_end
    paused_end = paused_start + minutes_to_td(paused_dur)

    # --- Second planning + extra treatment block (fixed durations) ---

    plan2_start = paused_end
    plan2_end = plan2_start + minutes_to_td(extra_plan_minutes)

    treat2_start = plan2_end
    treat2_end = treat2_start + minutes_to_td(extra_treat_minutes)

    # --- Post-treatment MRI + removal ---

    post_start = treat2_end
    post_end = post_start + minutes_to_td(post_dur)

    # Cutoff logic
    cutoff_dt = datetime.combine(base_date.date(), cutoff_t)

    case_ends_after_cutoff = post_end >= cutoff_dt
    case_crosses_cutoff = (align_start < cutoff_dt) and (post_end >= cutoff_dt)

    # Convenience: minutes from midnight for main milestone
    def minutes_since_midnight(dt: datetime) -> float:
        return dt.hour * 60.0 + dt.minute + dt.second / 60.0

    return {
        "anest_start": anest_start,
        "anest_end": anest_end,
        "insert_start": insert_start,
        "insert_end": insert_end,
        "align_start": align_start,
        "align_end": align_end,
        "coarse_start": coarse_start,
        "coarse_end": coarse_end,
        "detailed_start": detailed_start,
        "detailed_end": detailed_end,
        "plan_start": plan_start,
        "plan_end": plan_end,
        "treat_start": treat_start,
        "treat_end": treat_end,
        "paused_start": paused_start,
        "paused_end": paused_end,
        "plan2_start": plan2_start,
        "plan2_end": plan2_end,
        "treat2_start": treat2_start,
        "treat2_end": treat2_end,
        "post_start": post_start,
        "post_end": post_end,
        "post_end_minutes": minutes_since_midnight(post_end),
        "case_ends_after_cutoff": bool(case_ends_after_cutoff),
        "case_crosses_cutoff": bool(case_crosses_cutoff),
    }


def run_simulation(
    df: pd.DataFrame,
    n_sim: int,
    anest_start_str: str,
    anest_minutes: float,
    pre_insert_gap_minutes: float,
    insert_minutes: float,
    cutoff_str: str,
    extra_plan_minutes: float,
    extra_treat_minutes: float,
    random_seed: int | None = None,
) -> pd.DataFrame:
    if random_seed is not None:
        np.random.seed(random_seed)

    anest_start_t = parse_time_hhmm(anest_start_str)
    cutoff_t = parse_time_hhmm(cutoff_str)

    results = []

    for sim_idx in range(n_sim):
        row = df.sample(n=1, replace=True).iloc[0]
        res = simulate_one_day(
            row,
            anest_start_t=anest_start_t,
            anest_minutes=anest_minutes,
            pre_insert_gap_minutes=pre_insert_gap_minutes,
            insert_minutes=insert_minutes,
            cutoff_t=cutoff_t,
            extra_plan_minutes=extra_plan_minutes,
            extra_treat_minutes=extra_treat_minutes,
        )
        res["sim"] = sim_idx + 1
        results.append(res)

    out_df = pd.DataFrame(results)

    # Sort by post_end time for readability
    out_df = out_df.sort_values("post_end").reset_index(drop=True)
    return out_df


def summarize_results(sim_df: pd.DataFrame, cutoff_str: str) -> pd.DataFrame:
    """
    Compute high-level summary metrics from simulation results.
    """
    n = len(sim_df)
    if n == 0:
        raise ValueError("No simulations to summarize.")

    prob_end_after = sim_df["case_ends_after_cutoff"].mean()
    prob_cross = sim_df["case_crosses_cutoff"].mean()

    end_min = sim_df["post_end_minutes"]
    q = end_min.quantile([0.05, 0.25, 0.5, 0.75, 0.95])

    summary = pd.DataFrame(
        [
            {
                "N_sim": n,
                "Cutoff": cutoff_str,
                "Prob_case_ends_after_cutoff": float(prob_end_after),
                "Prob_case_crosses_cutoff": float(prob_cross),
                "EndTimeMin_mean": float(end_min.mean()),
                "EndTimeMin_std": float(end_min.std(ddof=1)),
                "EndTimeMin_p05": float(q.loc[0.05]),
                "EndTimeMin_p25": float(q.loc[0.25]),
                "EndTimeMin_p50": float(q.loc[0.5]),
                "EndTimeMin_p75": float(q.loc[0.75]),
                "EndTimeMin_p95": float(q.loc[0.95]),
            }
        ]
    )
    return summary


# ----------------------- CLI ----------------------- #

def parse_args():
    p = argparse.ArgumentParser(
        description="Simulate full clinical days using state duration distributions."
    )
    p.add_argument(
        "--site",
        required=True,
        help="Site name, e.g. Stanford_064",
    )
    p.add_argument(
        "--analysis-root",
        required=True,
        help="Directory containing timing_summary_<site>.csv",
    )
    p.add_argument(
        "--summary-file",
        default=None,
        help="Optional override for timing summary filename.",
    )
    p.add_argument(
        "--n-sim",
        type=int,
        default=10000,
        help="Number of simulated days.",
    )
    p.add_argument(
        "--cutoff",
        default="12:00",
        help="Cutoff time-of-day as HH:MM or HH:MM:SS (default 12:00).",
    )
    p.add_argument(
        "--anest-start",
        default="07:30",
        help="Anesthesia start time (HH:MM), default 07:30.",
    )
    p.add_argument(
        "--anest-minutes",
        type=float,
        default=15.0,
        help="Anesthesia duration in minutes (default 15).",
    )
    p.add_argument(
        "--pre-insert-gap-minutes",
        type=float,
        default=15.0,
        help="Gap between anesthesia end and insertion start (default 15).",
    )
    p.add_argument(
        "--insert-minutes",
        type=float,
        default=45.0,
        help="Device insertion duration in minutes (default 45).",
    )
    p.add_argument(
        "--extra-plan-minutes",
        type=float,
        default=20.0,
        help="Extra planning duration after Pause (minutes, default 20).",
    )
    p.add_argument(
        "--extra-treat-minutes",
        type=float,
        default=60.0,
        help="Extra treatment duration after the second planning (minutes, default 60).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional).",
    )
    return p.parse_args()


def main():
    args = parse_args()

    site = args.site
    analysis_root = Path(args.analysis_root)

    if args.summary_file is not None:
        summary_path = analysis_root / args.summary_file
    else:
        summary_path = analysis_root / f"timing_summary_{site}.csv"

    if not summary_path.exists():
        raise FileNotFoundError(f"Timing summary file not found: {summary_path}")

    print(f"Loading timing summary from:\n  {summary_path}")
    df = load_timing_summary(summary_path)

    print(
        f"Running {args.n_sim} simulations with:\n"
        f"  Anesthesia start:          {args.anest_start}\n"
        f"  Anesthesia duration:       {args.anest_minutes} min\n"
        f"  Pre-insert gap:            {args.pre_insert_gap_minutes} min\n"
        f"  Insertion duration:        {args.insert_minutes} min\n"
        f"  Extra planning after Pause:{args.extra_plan_minutes} min\n"
        f"  Extra treatment duration:  {args.extra_treat_minutes} min\n"
        f"  Cutoff time:               {args.cutoff}"
    )

    sim_df = run_simulation(
        df=df,
        n_sim=args.n_sim,
        anest_start_str=args.anest_start,
        anest_minutes=args.anest_minutes,
        pre_insert_gap_minutes=args.pre_insert_gap_minutes,
        insert_minutes=args.insert_minutes,
        cutoff_str=args.cutoff,
        extra_plan_minutes=args.extra_plan_minutes,
        extra_treat_minutes=args.extra_treat_minutes,
        random_seed=args.seed,
    )

    summary_df = summarize_results(sim_df, cutoff_str=args.cutoff)

    # Save outputs
    out_sim = analysis_root / f"day_sim_{site}.csv"
    out_summary = analysis_root / f"day_sim_summary_{site}.csv"

    # For CSV, convert datetimes to ISO strings (HH:MM:SS)
    sim_df_out = sim_df.copy()
    time_cols = [
        "anest_start",
        "anest_end",
        "insert_start",
        "insert_end",
        "align_start",
        "align_end",
        "coarse_start",
        "coarse_end",
        "detailed_start",
        "detailed_end",
        "plan_start",
        "plan_end",
        "treat_start",
        "treat_end",
        "paused_start",
        "paused_end",
        "plan2_start",
        "plan2_end",
        "treat2_start",
        "treat2_end",
        "post_start",
        "post_end",
    ]
    for col in time_cols:
        sim_df_out[col] = sim_df_out[col].dt.strftime("%H:%M:%S")

    sim_df_out.to_csv(out_sim, index=False)
    summary_df.to_csv(out_summary, index=False)

    print(f"\nSaved per-simulation results to:\n  {out_sim}")
    print(f"Saved summary metrics to:\n  {out_summary}")

    # Echo the main probabilities
    row = summary_df.iloc[0]
    print("\nSummary:")
    print(f"  N_sim:                            {int(row['N_sim'])}")
    print(f"  Cutoff:                           {row['Cutoff']}")
    print(
        f"  Prob case ends after cutoff:      {row['Prob_case_ends_after_cutoff']:.3f}"
    )
    print(
        f"  Prob case crosses cutoff:         {row['Prob_case_crosses_cutoff']:.3f}"
    )
    print(
        f"  Median end time (minutes):        {row['EndTimeMin_p50']:.1f} "
        f"(~{row['EndTimeMin_p50']/60:.2f} h)"
    )
    print(
        f"  95th percentile end time (min):   {row['EndTimeMin_p95']:.1f} "
        f"(~{row['EndTimeMin_p95']/60:.2f} h)"
    )


if __name__ == "__main__":
    main()
