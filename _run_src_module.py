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
