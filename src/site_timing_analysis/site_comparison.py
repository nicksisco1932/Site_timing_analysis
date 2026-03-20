from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


LOGGER = logging.getLogger(__name__)

SITE_A_LABEL = "Site A"
SITE_B_LABEL = "Site B"
SUMMARY_FILENAME = "state_duration_comparison_summary.csv"
PLOT_BASENAME = "state_duration_boxplot_by_site"
PLOT_TITLE = "Per-State Duration Comparison: Site A vs Site B"
PLOT_SUBTITLE = "(case-level totals; side-by-side boxplots)"
INVALID_STATE_VALUES = {"", "<NA>", "nan"}
SITE_COLORS = {
    SITE_A_LABEL: "#6BAED6",
    SITE_B_LABEL: "#F28E8B",
}


@dataclass(frozen=True)
class ComparisonSite:
    """Configuration for one comparison-site input."""

    site_key: str
    display_label: str
    intervals_dir: Path


@dataclass(frozen=True)
class ComparisonData:
    """Prepared data tables and ordering for the site-comparison figure."""

    plot_df: pd.DataFrame
    summary_df: pd.DataFrame
    state_order: list[str]
    site_order: list[str]


def load_case_state_totals(site: ComparisonSite) -> pd.DataFrame:
    """
    Load one site's per-case state totals from exported ``state_intervals`` CSVs.

    Input:
        Directory of ``*_state_intervals.csv`` files with at least ``state`` and
        ``duration_sec`` columns.
    Output:
        DataFrame with one row per case/state total and neutral display labels.
    Assumptions:
        Blank and ``<NA>`` states are excluded from comparison metrics.
    """

    if not site.intervals_dir.exists():
        raise ValueError(f"State-interval directory does not exist: {site.intervals_dir}")

    interval_paths = sorted(site.intervals_dir.glob("*_state_intervals.csv"))
    if not interval_paths:
        raise ValueError(f"No state-interval CSV files found in: {site.intervals_dir}")

    rows: list[pd.DataFrame] = []
    for interval_path in interval_paths:
        case_df = pd.read_csv(interval_path)
        required_columns = {"state", "duration_sec"}
        missing_columns = required_columns.difference(case_df.columns)
        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise ValueError(f"{interval_path} is missing required columns: {missing_text}")

        filtered = case_df.loc[case_df["state"].notna(), ["state", "duration_sec"]].copy()
        filtered["state"] = filtered["state"].astype(str).str.strip()
        filtered = filtered.loc[~filtered["state"].isin(INVALID_STATE_VALUES)].copy()
        if filtered.empty:
            continue

        aggregated = (
            filtered.groupby("state", dropna=False, as_index=False)["duration_sec"]
            .sum()
            .rename(columns={"duration_sec": "duration_sec_total"})
        )
        aggregated["case_id"] = interval_path.name.removesuffix("_state_intervals.csv")
        aggregated["site_key"] = site.site_key
        aggregated["site"] = site.display_label
        aggregated["minutes"] = aggregated["duration_sec_total"] / 60.0
        rows.append(aggregated)

    if not rows:
        raise ValueError(
            f"State-interval files were found but no usable state rows remained in: {site.intervals_dir}"
        )

    combined = pd.concat(rows, ignore_index=True)
    LOGGER.info("Loaded %s case/state totals for %s.", len(combined), site.display_label)
    return combined


def prepare_comparison_data(
    site_a_intervals: Path,
    site_b_intervals: Path,
    *,
    min_cases_per_site: int = 10,
) -> ComparisonData:
    """
    Build the anonymized comparison tables used for plotting and CSV export.

    Input:
        Two state-interval directories. The first directory is mapped to
        ``Site A`` and the second to ``Site B``.
    Output:
        Prepared plot rows, summary table, and deterministic state/site order.
    Assumptions:
        Per-state totals are derived by summing ``duration_sec`` within each
        case/state pair before cross-case comparison.
    """

    sites = [
        ComparisonSite(site_key="site_a", display_label=SITE_A_LABEL, intervals_dir=site_a_intervals),
        ComparisonSite(site_key="site_b", display_label=SITE_B_LABEL, intervals_dir=site_b_intervals),
    ]
    site_order = [site.display_label for site in sites]

    all_totals = pd.concat([load_case_state_totals(site) for site in sites], ignore_index=True)
    counts = (
        all_totals.groupby(["site", "state"], as_index=False)["case_id"]
        .nunique()
        .rename(columns={"case_id": "n_cases"})
    )
    count_matrix = counts.pivot(index="state", columns="site", values="n_cases").fillna(0)
    eligible_states = [
        state
        for state in count_matrix.index.tolist()
        if all(int(count_matrix.at[state, site_label]) >= min_cases_per_site for site_label in site_order)
    ]
    if not eligible_states:
        raise ValueError(
            "No states met the minimum case threshold at both sites. "
            f"Minimum required: {min_cases_per_site}"
        )

    plot_df = all_totals.loc[all_totals["state"].isin(eligible_states)].copy()
    state_order = (
        plot_df.groupby("state", as_index=True)["minutes"]
        .median()
        .sort_values(ascending=False)
        .index.tolist()
    )
    plot_df["state"] = pd.Categorical(plot_df["state"], categories=state_order, ordered=True)
    plot_df["site"] = pd.Categorical(plot_df["site"], categories=site_order, ordered=True)

    summary_df = (
        plot_df.groupby(["site", "state"], observed=True)["minutes"]
        .agg(
            n_cases="count",
            median_min="median",
            mean_min="mean",
            p25_min=lambda values: values.quantile(0.25),
            p75_min=lambda values: values.quantile(0.75),
        )
        .reset_index()
    )

    LOGGER.info("Prepared %s eligible workflow states for comparison.", len(state_order))
    return ComparisonData(
        plot_df=plot_df,
        summary_df=summary_df,
        state_order=state_order,
        site_order=site_order,
    )


def create_comparison_figure(data: ComparisonData) -> tuple[plt.Figure, plt.Axes]:
    """Create the anonymized comparison figure without saving it."""

    fig, ax = plt.subplots(figsize=(12, 8))

    base_positions = np.arange(len(data.state_order), dtype=float)
    offsets = {
        SITE_A_LABEL: -0.18,
        SITE_B_LABEL: 0.18,
    }
    jitter_rng = np.random.default_rng(seed=42)

    for site_label in data.site_order:
        site_rows = data.plot_df.loc[data.plot_df["site"] == site_label]
        box_data = [
            site_rows.loc[site_rows["state"] == state_name, "minutes"].to_numpy()
            for state_name in data.state_order
        ]
        positions = base_positions + offsets[site_label]
        boxplot = ax.boxplot(
            box_data,
            vert=False,
            positions=positions,
            widths=0.3,
            patch_artist=True,
            showfliers=False,
            manage_ticks=False,
            medianprops={"linewidth": 1.2, "color": "black"},
            whiskerprops={"linewidth": 1.1, "color": SITE_COLORS[site_label]},
            capprops={"linewidth": 1.1, "color": SITE_COLORS[site_label]},
        )

        for patch in boxplot["boxes"]:
            patch.set_facecolor(SITE_COLORS[site_label])
            patch.set_alpha(0.8)
            patch.set_edgecolor(SITE_COLORS[site_label])
            patch.set_linewidth(1.2)

        for index, state_name in enumerate(data.state_order):
            values = box_data[index]
            if len(values) == 0:
                continue
            y_jitter = jitter_rng.normal(loc=positions[index], scale=0.035, size=len(values))
            ax.scatter(
                values,
                y_jitter,
                s=9,
                alpha=0.65,
                color=SITE_COLORS[site_label],
                edgecolors="none",
                zorder=3,
            )

    ax.set_yticks(base_positions)
    ax.set_yticklabels(data.state_order)
    ax.invert_yaxis()
    ax.set_xlabel("Duration (minutes)")
    ax.set_ylabel("Workflow State")
    ax.set_title(f"{PLOT_TITLE}\n{PLOT_SUBTITLE}")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=SITE_COLORS[site_label], edgecolor=SITE_COLORS[site_label], alpha=0.8)
        for site_label in data.site_order
    ]
    fig.legend(
        legend_handles,
        data.site_order,
        loc="lower center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 0.03),
        columnspacing=1.8,
        handlelength=1.6,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    return fig, ax


def write_outputs(data: ComparisonData, outdir: Path, *, dpi: int = 200) -> None:
    """Write the anonymized comparison artifacts to disk."""

    outdir.mkdir(parents=True, exist_ok=True)

    summary_path = outdir / SUMMARY_FILENAME
    data.summary_df.to_csv(summary_path, index=False)
    LOGGER.info("Wrote summary CSV: %s", summary_path)

    figure, _ = create_comparison_figure(data)
    png_path = outdir / f"{PLOT_BASENAME}.png"
    pdf_path = outdir / f"{PLOT_BASENAME}.pdf"
    figure.savefig(png_path, dpi=dpi)
    figure.savefig(pdf_path)
    plt.close(figure)
    LOGGER.info("Wrote comparison plots: %s and %s", png_path, pdf_path)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the anonymized comparison exporter."""

    parser = argparse.ArgumentParser(
        description="Create an anonymized two-site state-duration comparison from state_intervals exports."
    )
    parser.add_argument(
        "--site-a-intervals",
        required=True,
        help="Path to the reference site state_intervals directory. Rendered as Site A.",
    )
    parser.add_argument(
        "--site-b-intervals",
        required=True,
        help="Path to the comparison site state_intervals directory. Rendered as Site B.",
    )
    parser.add_argument(
        "--outdir",
        required=True,
        help="Directory where anonymized comparison artifacts will be written.",
    )
    parser.add_argument(
        "--min-cases-per-site",
        type=int,
        default=10,
        help="Minimum cases required at both sites for a state to be included. Default 10.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="PNG resolution in dots per inch. Default 200.",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint for anonymized site-comparison export."""

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    args = parse_args()

    comparison_data = prepare_comparison_data(
        Path(args.site_a_intervals),
        Path(args.site_b_intervals),
        min_cases_per_site=args.min_cases_per_site,
    )
    write_outputs(comparison_data, Path(args.outdir), dpi=args.dpi)


if __name__ == "__main__":
    main()
