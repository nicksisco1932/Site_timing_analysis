# Project: Site Timing Analysis
# File: _run_src_module.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-03
# Purpose: Provides the compatibility dispatcher used by root-level wrapper scripts.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def run_entry(script_path: str) -> None:
    repo_root = Path(script_path).resolve().parent
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    module_name = f"site_timing_analysis.{Path(script_path).stem}"
    runpy.run_module(module_name, run_name="__main__")
