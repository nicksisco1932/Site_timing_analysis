# Project: Site Timing Analysis
# File: scripts/build_timing_gantt_deliverables.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: Unknown
# Purpose: Provides a repository-local wrapper for building timing Gantt final deliverables.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def main() -> None:
    _ensure_src_on_path()
    from site_timing_analysis.timing_gantt_deliverables import main as deliverables_main

    deliverables_main()


if __name__ == "__main__":
    main()
