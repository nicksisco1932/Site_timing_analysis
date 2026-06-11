from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OutputLayout:
    """
    Canonical folder map for one pipeline run.

    Input:
        A completed or target run directory.
    Output:
        Stable artifact directories grouped by purpose.
    Assumptions:
        ``run_dir`` is the run boundary supplied by ``--output``; callers should
        create dated/site-specific run directories before invoking the pipeline.
    """

    run_dir: Path

    @property
    def manifests_dir(self) -> Path:
        return self.run_dir / "manifests"

    @property
    def normalized_events_dir(self) -> Path:
        return self.run_dir / "events" / "normalized"

    @property
    def enriched_events_dir(self) -> Path:
        return self.run_dir / "events" / "enriched"

    @property
    def state_labeled_events_dir(self) -> Path:
        return self.run_dir / "events" / "state_labeled"

    @property
    def state_intervals_dir(self) -> Path:
        return self.run_dir / "intervals" / "state"

    @property
    def timeline_plots_dir(self) -> Path:
        return self.run_dir / "plots" / "timelines"

    @property
    def tables_dir(self) -> Path:
        return self.run_dir / "tables"

    @property
    def reports_dir(self) -> Path:
        return self.run_dir / "reports"

    @property
    def scratch_dir(self) -> Path:
        return self.run_dir / "scratch"

    @property
    def db_extract_dir(self) -> Path:
        return self.scratch_dir / "db_extract"

    @property
    def run_manifest_path(self) -> Path:
        return self.manifests_dir / "run_manifest.json"

    @property
    def case_manifest_path(self) -> Path:
        return self.manifests_dir / "case_manifest.csv"

    @property
    def diagnostics_summary_path(self) -> Path:
        return self.reports_dir / "diagnostics_summary.md"

    @property
    def interval_outlier_diagnostics_path(self) -> Path:
        return self.reports_dir / "interval_outlier_diagnostics.md"


def output_layout(run_dir: Path) -> OutputLayout:
    return OutputLayout(run_dir=run_dir.resolve())


def first_existing_path(*paths: Path) -> Path:
    """
    Return the first existing path, falling back to the first candidate.

    This supports historical run directories while new runs use the canonical
    ``OutputLayout`` paths.
    """
    if not paths:
        raise ValueError("At least one candidate path is required")
    for path in paths:
        if path.exists():
            return path
    return paths[0]
