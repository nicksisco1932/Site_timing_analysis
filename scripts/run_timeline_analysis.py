# Project: Site Timing Analysis
# File: scripts/run_timeline_analysis.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-10
# Purpose: Provides the site-agnostic CLI entry point for validated timeline exports.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import time

_PROCESS_WALL_STARTED = time.perf_counter()
_PROCESS_CPU_STARTED = time.process_time()

from run_asui_122_timeline_analysis import main


if __name__ == "__main__":
    raise SystemExit(
        main(
            process_wall_started=_PROCESS_WALL_STARTED,
            process_cpu_started=_PROCESS_CPU_STARTED,
        )
    )
