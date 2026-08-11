# Project: Site Timing Analysis
# File: src/site_timing_analysis/config.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Builds and validates run configuration for the staged timing pipeline.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Mapping, Any

from .errors import ConfigValidationError
from .models import RunConfig


_SPECIAL_YEAR_SELECTIONS = {"All", "CurrentYear", "PastYears"}


def validate_year_selection(year_selection: str) -> str:
    value = str(year_selection).strip()
    if value in _SPECIAL_YEAR_SELECTIONS:
        return value

    try:
        year = int(value)
    except ValueError as exc:
        raise ConfigValidationError(
            f"Invalid year selection '{year_selection}'. "
            "Use All, CurrentYear, PastYears, or a 4-digit year."
        ) from exc

    if year < 1900 or year > 3000:
        raise ConfigValidationError(
            f"Invalid year selection '{year_selection}'. Expected range 1900-3000."
        )
    return str(year)


def resolve_year_list(year_selection: str, *, current_year: int | None = None) -> list[int]:
    year = current_year if current_year is not None else date.today().year
    normalized = validate_year_selection(year_selection)
    if normalized == "All":
        return list(range(2016, year + 1))
    if normalized == "CurrentYear":
        return [year]
    if normalized == "PastYears":
        return list(range(2016, year))
    return [int(normalized)]


def build_run_config(
    *,
    site_code: str,
    year_selection: str,
    root_dir: str | Path,
    output_dir: str | Path,
    site_path: str | Path | None = None,
    case_id_file: str | Path | None = None,
    allow_ambiguous_db: bool = False,
    db_candidate_index: int | None = None,
    zip_member_index: int | None = None,
    timing_log_dir: str | Path | None = None,
    diagnostics: bool = False,
    diagnostics_file: str | Path | None = None,
    tff_adapter_enabled: bool = False,
    tff_normalized_case_table: str | Path | None = None,
    tff_filter_known_exclusions: bool = False,
) -> RunConfig:
    normalized_site = site_code.strip()
    if not normalized_site:
        raise ConfigValidationError("site_code is required.")

    normalized_year = validate_year_selection(year_selection)

    resolved_root = Path(root_dir).expanduser().resolve()
    if not resolved_root.exists():
        raise ConfigValidationError(f"root_dir does not exist: {resolved_root}")

    resolved_output = Path(output_dir).expanduser().resolve()
    resolved_site_path = (
        Path(site_path).expanduser().resolve()
        if site_path is not None
        else resolved_root / normalized_site
    )
    resolved_case_id_file = (
        Path(case_id_file).expanduser().resolve() if case_id_file is not None else None
    )
    resolved_timing_log_dir = (
        Path(timing_log_dir).expanduser().resolve() if timing_log_dir is not None else None
    )
    resolved_diagnostics_file = (
        Path(diagnostics_file).expanduser().resolve() if diagnostics_file is not None else None
    )
    resolved_tff_normalized_case_table = (
        Path(tff_normalized_case_table).expanduser().resolve()
        if tff_normalized_case_table is not None
        else None
    )

    if db_candidate_index is not None and db_candidate_index < 0:
        raise ConfigValidationError("db_candidate_index must be >= 0 when provided.")
    if zip_member_index is not None and zip_member_index < 0:
        raise ConfigValidationError("zip_member_index must be >= 0 when provided.")

    return RunConfig(
        site_code=normalized_site,
        year_selection=normalized_year,
        root_dir=resolved_root,
        output_dir=resolved_output,
        site_path=resolved_site_path,
        case_id_file=resolved_case_id_file,
        allow_ambiguous_db=allow_ambiguous_db,
        db_candidate_index=db_candidate_index,
        zip_member_index=zip_member_index,
        timing_log_dir=resolved_timing_log_dir,
        diagnostics=diagnostics,
        diagnostics_file=resolved_diagnostics_file,
        tff_adapter_enabled=tff_adapter_enabled,
        tff_normalized_case_table=resolved_tff_normalized_case_table,
        tff_filter_known_exclusions=tff_filter_known_exclusions,
    )


def build_run_config_from_mapping(config_data: Mapping[str, Any]) -> RunConfig:
    return build_run_config(
        site_code=str(config_data["site_code"]),
        year_selection=str(config_data.get("year_selection", "All")),
        root_dir=config_data["root_dir"],
        output_dir=config_data["output_dir"],
        site_path=config_data.get("site_path"),
        case_id_file=config_data.get("case_id_file"),
        allow_ambiguous_db=bool(config_data.get("allow_ambiguous_db", False)),
        db_candidate_index=config_data.get("db_candidate_index"),
        zip_member_index=config_data.get("zip_member_index"),
        timing_log_dir=config_data.get("timing_log_dir"),
        diagnostics=bool(config_data.get("diagnostics", False)),
        diagnostics_file=config_data.get("diagnostics_file"),
        tff_adapter_enabled=bool(config_data.get("tff_adapter_enabled", False)),
        tff_normalized_case_table=config_data.get("tff_normalized_case_table"),
        tff_filter_known_exclusions=bool(config_data.get("tff_filter_known_exclusions", False)),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="First-slice timing migration: discovery, ingestion, normalization exports."
    )
    parser.add_argument("--site", required=True, help="Site code (e.g. Stanford_064).")
    parser.add_argument(
        "--years",
        default="All",
        help="All, CurrentYear, PastYears, or specific year.",
    )
    parser.add_argument("--root", required=True, help="Root directory containing site folders.")
    parser.add_argument("--output", required=True, help="Output directory for manifests/exports.")
    parser.add_argument(
        "--site-path",
        default=None,
        help="Optional explicit site folder path. Overrides <root>/<site>.",
    )
    parser.add_argument(
        "--case-id-file",
        default=None,
        help="Optional newline-delimited case IDs. Discovery still runs first, then only these IDs are ingested.",
    )
    parser.add_argument(
        "--allow-ambiguous-db",
        action="store_true",
        help="Allow ambiguous DB candidate selection when explicit indexes are provided.",
    )
    parser.add_argument(
        "--db-candidate-index",
        type=int,
        default=None,
        help="Candidate index to select when DB candidates are ambiguous.",
    )
    parser.add_argument(
        "--zip-member-index",
        type=int,
        default=None,
        help="Zip member index to select when multiple local.db entries exist in one zip.",
    )
    parser.add_argument(
        "--timing-log-dir",
        default=None,
        help="Optional directory containing <case_id>.csv timing logs. "
        "Default: <resolved_site_root>/TimingLogs",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Write operator-facing diagnostics summary after run completion.",
    )
    parser.add_argument(
        "--diagnostics-file",
        default=None,
        help="Optional diagnostics output file path. Default: <output>/reports/diagnostics_summary.md",
    )
    parser.add_argument(
        "--enable-tff-adapter",
        action="store_true",
        help="Enable read-only TFF case-level metadata adapter (default: disabled).",
    )
    parser.add_argument(
        "--tff-normalized-case-table",
        default=None,
        help="Path to tff_normalized_case_table.csv. "
        "Default when adapter enabled: <output>/reports/tff_audit/tff_normalized_case_table.csv",
    )
    parser.add_argument(
        "--tff-filter-known-exclusions",
        action="store_true",
        help="Optionally filter known exclusion-case classes (e.g. known Stanford RCT IDs) "
        "from TFF join quality metrics.",
    )
    return parser


def build_run_config_from_args(argv: list[str] | None = None) -> RunConfig:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return build_run_config(
        site_code=args.site,
        year_selection=args.years,
        root_dir=args.root,
        output_dir=args.output,
        site_path=args.site_path,
        case_id_file=args.case_id_file,
        allow_ambiguous_db=args.allow_ambiguous_db,
        db_candidate_index=args.db_candidate_index,
        zip_member_index=args.zip_member_index,
        timing_log_dir=args.timing_log_dir,
        diagnostics=args.diagnostics,
        diagnostics_file=args.diagnostics_file,
        tff_adapter_enabled=args.enable_tff_adapter,
        tff_normalized_case_table=args.tff_normalized_case_table,
        tff_filter_known_exclusions=args.tff_filter_known_exclusions,
    )
