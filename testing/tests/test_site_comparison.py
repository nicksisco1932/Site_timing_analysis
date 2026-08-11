# Project: Site Timing Analysis
# File: testing/tests/test_site_comparison.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-19
# Purpose: Tests site comparison behavior for the Site Timing Analysis workflow.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from site_timing_analysis.site_comparison import (
    PLOT_SUBTITLE,
    PLOT_TITLE,
    SITE_A_LABEL,
    SITE_B_LABEL,
    create_comparison_figure,
    prepare_comparison_data,
)


def _write_state_intervals(intervals_dir: Path, case_id: str, minutes_by_state: dict[str, float]) -> None:
    rows = []
    for state, minutes in minutes_by_state.items():
        rows.append({"state": state, "duration_sec": minutes * 60.0})
    pd.DataFrame(rows).to_csv(intervals_dir / f"{case_id}_state_intervals.csv", index=False)


def test_prepare_comparison_data_filters_states_and_preserves_neutral_labels(tmp_path: Path) -> None:
    site_a_dir = tmp_path / "Yale_065"
    site_b_dir = tmp_path / "Stanford_064"
    site_a_dir.mkdir()
    site_b_dir.mkdir()

    for index in range(10):
        _write_state_intervals(
            site_a_dir,
            f"A_{index:02d}",
            {
                "Treating": 50 + index,
                "Room ready": 10 + index,
                "": 99,
                "<NA>": 88,
            },
        )
        _write_state_intervals(
            site_b_dir,
            f"B_{index:02d}",
            {
                "Treating": 40 + index,
                "Room ready": 20 + index,
                "": 77,
                "<NA>": 66,
            },
        )

    for index in range(5):
        _write_state_intervals(site_a_dir, f"AR_{index:02d}", {"Review": 5 + index})
        _write_state_intervals(site_b_dir, f"BR_{index:02d}", {"Review": 6 + index})

    data = prepare_comparison_data(site_a_dir, site_b_dir, min_cases_per_site=10)

    assert data.site_order == [SITE_A_LABEL, SITE_B_LABEL]
    assert data.state_order == ["Treating", "Room ready"]
    assert set(data.summary_df["site"]) == {SITE_A_LABEL, SITE_B_LABEL}
    assert "Review" not in set(data.summary_df["state"])


def test_create_comparison_figure_uses_anonymized_title_and_legend(tmp_path: Path) -> None:
    site_a_dir = tmp_path / "Yale_065"
    site_b_dir = tmp_path / "Stanford_064"
    site_a_dir.mkdir()
    site_b_dir.mkdir()

    for index in range(10):
        _write_state_intervals(site_a_dir, f"A_{index:02d}", {"Treating": 50 + index})
        _write_state_intervals(site_b_dir, f"B_{index:02d}", {"Treating": 40 + index})

    data = prepare_comparison_data(site_a_dir, site_b_dir, min_cases_per_site=10)
    figure, axis = create_comparison_figure(data)

    title = axis.get_title()
    assert title == f"{PLOT_TITLE}\n{PLOT_SUBTITLE}"
    assert "Yale_065" not in title
    assert "Stanford_064" not in title

    legend_texts = [text.get_text() for text in figure.legends[0].get_texts()]
    assert legend_texts == [SITE_A_LABEL, SITE_B_LABEL]
    plt.close(figure)
