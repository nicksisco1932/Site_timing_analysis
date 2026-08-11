# Project: Site Timing Analysis
# File: src/site_timing_analysis/errors.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Defines typed exceptions for timing pipeline configuration, discovery, ingestion, and export failures.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from pathlib import Path


class SiteTimingError(Exception):
    """Base exception for first-slice pipeline failures."""


class ConfigValidationError(SiteTimingError):
    """Raised when run configuration values are invalid."""


class DiscoveryError(SiteTimingError):
    """Raised when case discovery cannot proceed."""


class DatabaseSourceNotFoundError(SiteTimingError):
    """Raised when no usable local.db source can be resolved for a case."""

    def __init__(self, case_id: str, message: str) -> None:
        super().__init__(f"[{case_id}] {message}")
        self.case_id = case_id


class AmbiguousDatabaseSourceError(SiteTimingError):
    """Raised when multiple database candidates exist without explicit override."""

    def __init__(self, case_id: str, candidates: list[str], context: str) -> None:
        super().__init__(
            f"[{case_id}] Ambiguous database source in {context}. "
            f"Candidates: {', '.join(candidates)}"
        )
        self.case_id = case_id
        self.candidates = candidates
        self.context = context


class DatabaseReadError(SiteTimingError):
    """Raised when SQLite or ZIP reads fail."""

    def __init__(self, source_path: Path, message: str) -> None:
        super().__init__(f"[{source_path}] {message}")
        self.source_path = source_path


class MissingTableError(SiteTimingError):
    """Raised when a required SQLite table is missing."""

    def __init__(self, source_path: Path, table_name: str) -> None:
        super().__init__(f"[{source_path}] Missing required table: {table_name}")
        self.source_path = source_path
        self.table_name = table_name


class NormalizationError(SiteTimingError):
    """Raised when raw audit rows cannot be normalized to required fields."""

    def __init__(self, case_id: str, row_number: int, message: str) -> None:
        super().__init__(f"[{case_id}] row {row_number}: {message}")
        self.case_id = case_id
        self.row_number = row_number


class ManifestWriteError(SiteTimingError):
    """Raised when manifest or export artifacts cannot be written."""


class TimingLogParseError(SiteTimingError):
    """Raised when a present timing-log file cannot be parsed or validated."""

    def __init__(self, case_id: str, source_path: Path, message: str) -> None:
        super().__init__(f"[{case_id}] [{source_path}] {message}")
        self.case_id = case_id
        self.source_path = source_path


class EnrichmentError(SiteTimingError):
    """Raised when enrichment cannot be completed safely for a case."""


class HardwareLookupError(SiteTimingError):
    """Raised when hardware lookup ingestion or query operations fail."""
