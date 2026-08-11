# Project: Site Timing Analysis
# File: scripts/acquire_localdb_bulk.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Provides the repository-local CLI for explicit resumable bulk local.db acquisition.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from site_timing_analysis.bulk_acquisition import main


if __name__ == "__main__":
    raise SystemExit(main())
