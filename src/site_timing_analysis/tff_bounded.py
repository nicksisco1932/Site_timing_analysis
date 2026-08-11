# Project: Site Timing Analysis
# File: src/site_timing_analysis/tff_bounded.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-13
# Purpose: Builds bounded TFF join windows for case-level timing metadata validation.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import ParserError


SHEET1_NAME = "Sheet1"
SHEET1_USECOLS = "A:BK"
SHEET2_NAME = "Sheet2"
PRIMARY_CASE_ID_COLUMN = "Generated Treatment ID"
SECONDARY_CASE_ID_COLUMN = "PatientID"

_CANONICAL_CASE_PATTERN = re.compile(r"^([A-Z]{0,3}\d{3})_(\d{2})-(\d{3})$")
_CASE_VARIANT_PATTERNS = (
    re.compile(r"^([A-Z]{0,3}\d{3})-(\d{2})-(\d{3})$"),
    re.compile(r"^([A-Z]{0,3}\d{3})_(\d{2})_(\d{3})$"),
    re.compile(r"^([A-Z]{0,3}\d{3})-(\d{2})_(\d{3})$"),
)

_CLOCK_PATTERN = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?\s*(?P<ampm>[AaPp][Mm])?$"
)

_SEQUENCE_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("patient_enters_mri", "Patient enters MRI room", ("patient enters mri",)),
    (
        "anesthesia_start_prepare",
        "Anesthesia starts to prepare patient",
        ("anesthesia starts to prepare", "anaesthesia starts to prepare"),
    ),
    ("patient_sedated", "Patient is sedated", ("patient is sedated",)),
    ("device_insertion_begins", "Device insertion begins", ("device insertion begins",)),
    ("device_insertion_complete", "Device insertion complete", ("device insertion complete",)),
    ("patient_leaves_mri", "Patient leaves MRI room", ("patient leaves mri room", "patient leaves mri")),
    (
        "patient_transfer_recovery",
        "Patient transfer to recovery",
        ("patient transfer to recovery", "transfer to recovery"),
    ),
]


@dataclass(slots=True)
class ParsedTime:
    raw_text: str
    minute_of_day: int | None
    parse_kind: str


@dataclass(slots=True)
class SequencePoint:
    event_key: str
    event_label: str
    column_name: str
    raw_value: str
    parsed_minute: int | None
    parse_kind: str
    corrected_minute: int | None
    correction_applied: str
    correction_reason: str


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _header_key(value: str) -> str:
    return _normalize_text(value).lower()


def _is_blank(value: Any) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def canonicalize_case_id(raw_value: Any) -> tuple[str | None, str]:
    """Canonicalize case IDs to AAA999_99-999 style with deterministic soft-fail statuses."""
    if _is_blank(raw_value):
        return None, "missing_case_id"

    cleaned = _normalize_text(str(raw_value)).upper()
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"[^A-Z0-9_-]", "", cleaned)
    cleaned = cleaned.strip("_-")

    match = _CANONICAL_CASE_PATTERN.fullmatch(cleaned)
    if match:
        return cleaned, "ok_canonical"

    for pattern in _CASE_VARIANT_PATTERNS:
        variant_match = pattern.fullmatch(cleaned)
        if not variant_match:
            continue
        canonical = f"{variant_match.group(1)}_{variant_match.group(2)}-{variant_match.group(3)}"
        return canonical, "ok_normalized_variant"

    return None, "unresolved_case_id_format"


def _guess_site_code(normalized_label: str) -> str:
    match = re.search(r"\b(\d{3})\b", normalized_label)
    return match.group(1) if match else ""


def _normalize_site_label(raw_value: Any) -> tuple[str, str]:
    if _is_blank(raw_value):
        return "", ""
    normalized = _normalize_text(str(raw_value))
    key = re.sub(r"[^A-Za-z0-9]+", " ", normalized).strip().upper()
    return normalized, key


def _extract_site_code_from_case_id(case_id: str) -> str:
    case_text = str(case_id).strip().upper()
    match = _CANONICAL_CASE_PATTERN.fullmatch(case_text)
    if not match:
        return ""
    prefix = match.group(1)
    suffix_match = re.search(r"(\d{3})$", prefix)
    return suffix_match.group(1) if suffix_match else ""


def _build_site_normalization_table(case_table_df: pd.DataFrame) -> pd.DataFrame:
    required_cols = ["site_label_raw", "site_label_normalized", "site_key", "case_id"]
    site_work = case_table_df[required_cols].copy()
    site_work["case_site_code"] = site_work["case_id"].map(_extract_site_code_from_case_id)
    site_work["case_id_non_blank"] = site_work["case_id"].fillna("").astype(str).str.strip().ne("")
    site_work["case_site_code_non_blank"] = site_work["case_site_code"].fillna("").astype(str).str.strip().ne("")

    table_rows: list[dict[str, Any]] = []
    grouped = site_work.groupby(["site_label_raw", "site_label_normalized", "site_key"], dropna=False)
    for (raw_label, normalized_label, site_key), group in grouped:
        row_count = int(len(group))
        unique_case_ids = int(group.loc[group["case_id_non_blank"], "case_id"].nunique())
        evidence_series = group.loc[group["case_site_code_non_blank"], "case_site_code"].astype(str)
        rows_with_site_code = int(len(evidence_series))
        value_counts = evidence_series.value_counts()
        candidate_codes = sorted(value_counts.index.tolist())
        candidate_counts_text = "|".join(f"{code}:{int(value_counts[code])}" for code in candidate_codes)

        if str(normalized_label).strip() == "":
            mapping_status = "unmapped"
            mapping_reason = "blank_site_label"
            normalized_site_code = ""
        elif rows_with_site_code == 0:
            mapping_status = "unmapped"
            mapping_reason = "no_caseid_site_code_evidence"
            normalized_site_code = ""
        elif len(candidate_codes) == 1:
            mapping_status = "mapped"
            mapping_reason = "single_caseid_site_code_consensus"
            normalized_site_code = candidate_codes[0]
        else:
            mapping_status = "ambiguous"
            mapping_reason = "multiple_caseid_site_codes_detected"
            normalized_site_code = ""

        table_rows.append(
            {
                "site_label_raw": raw_label,
                "site_label_normalized": normalized_label,
                "site_key": site_key,
                "row_count": row_count,
                "unique_case_ids": unique_case_ids,
                "rows_with_case_site_code": rows_with_site_code,
                "mapping_status": mapping_status,
                "normalized_site_code": normalized_site_code,
                "mapping_reason": mapping_reason,
                "candidate_site_codes": "|".join(candidate_codes),
                "candidate_site_code_counts": candidate_counts_text,
            }
        )
    return pd.DataFrame(table_rows).sort_values(["row_count", "site_label_raw"], ascending=[False, True])


def parse_time_value(raw_value: Any) -> ParsedTime:
    if _is_blank(raw_value):
        return ParsedTime(raw_text="", minute_of_day=None, parse_kind="blank")

    if isinstance(raw_value, pd.Timestamp):
        return ParsedTime(
            raw_text=raw_value.isoformat(),
            minute_of_day=int(raw_value.hour) * 60 + int(raw_value.minute),
            parse_kind="datetime",
        )
    if isinstance(raw_value, datetime):
        return ParsedTime(
            raw_text=raw_value.isoformat(),
            minute_of_day=int(raw_value.hour) * 60 + int(raw_value.minute),
            parse_kind="datetime",
        )
    if isinstance(raw_value, time):
        return ParsedTime(
            raw_text=raw_value.isoformat(),
            minute_of_day=int(raw_value.hour) * 60 + int(raw_value.minute),
            parse_kind="datetime",
        )

    raw_text = _normalize_text(str(raw_value))
    clock_match = _CLOCK_PATTERN.fullmatch(raw_text)
    if clock_match:
        hour = int(clock_match.group("hour"))
        minute = int(clock_match.group("minute"))
        if minute > 59 or hour > 24:
            return ParsedTime(raw_text=raw_text, minute_of_day=None, parse_kind="unparseable")
        ampm = clock_match.group("ampm")
        if ampm:
            normalized_hour = hour % 12
            if ampm.lower() == "pm":
                normalized_hour += 12
            return ParsedTime(
                raw_text=raw_text,
                minute_of_day=normalized_hour * 60 + minute,
                parse_kind="clock_ampm",
            )
        if 13 <= hour <= 23:
            return ParsedTime(raw_text=raw_text, minute_of_day=hour * 60 + minute, parse_kind="clock_24h")
        if 0 <= hour <= 12:
            return ParsedTime(raw_text=raw_text, minute_of_day=hour * 60 + minute, parse_kind="clock_ambiguous")
        return ParsedTime(raw_text=raw_text, minute_of_day=None, parse_kind="unparseable")

    parsed_datetime = pd.to_datetime(raw_text, errors="coerce")
    if pd.notna(parsed_datetime):
        return ParsedTime(
            raw_text=raw_text,
            minute_of_day=int(parsed_datetime.hour) * 60 + int(parsed_datetime.minute),
            parse_kind="datetime",
        )
    return ParsedTime(raw_text=raw_text, minute_of_day=None, parse_kind="unparseable")


def _to_excel_row_number(index_zero_based: int) -> int:
    return index_zero_based + 2


def _select_site_column(columns: list[str]) -> str | None:
    keys = {_header_key(col): col for col in columns}
    if "site name" in keys:
        return keys["site name"]

    candidates = [col for col in columns if "site" in _header_key(col)]
    if not candidates:
        return None
    return sorted(candidates)[0]


def _timing_parse_stats(series: pd.Series) -> dict[str, int]:
    stats = {
        "blank": 0,
        "clock_ambiguous": 0,
        "clock_ampm": 0,
        "clock_24h": 0,
        "datetime": 0,
        "unparseable": 0,
        "parseable": 0,
    }
    for value in series:
        parsed = parse_time_value(value)
        stats[parsed.parse_kind] = stats.get(parsed.parse_kind, 0) + 1
        if parsed.minute_of_day is not None:
            stats["parseable"] += 1
    return stats


def _identify_timing_columns(sheet1: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for col in sheet1.columns:
        column_key = _header_key(col)
        stats = _timing_parse_stats(sheet1[col])
        non_blank = int((~sheet1[col].map(_is_blank)).sum())
        parseable_ratio = (stats["parseable"] / non_blank) if non_blank else 0.0
        header_time_signal = "timing" in column_key or " time" in column_key or column_key.startswith("time ")
        timing_candidate = header_time_signal and (parseable_ratio >= 0.35 or non_blank <= 20)

        rows.append(
            {
                "column": str(col),
                "column_key": column_key,
                "non_blank_rows": non_blank,
                "parseable_rows": stats["parseable"],
                "parseable_ratio": round(parseable_ratio, 4),
                "clock_ambiguous_count": stats["clock_ambiguous"],
                "clock_ampm_count": stats["clock_ampm"],
                "clock_24h_count": stats["clock_24h"],
                "datetime_count": stats["datetime"],
                "unparseable_count": stats["unparseable"],
                "timing_candidate": timing_candidate,
            }
        )
    return pd.DataFrame(rows)


def _select_sequence_columns(sheet1: pd.DataFrame) -> dict[str, tuple[str, str]]:
    selected: dict[str, tuple[str, str]] = {}
    ordered_columns = list(sheet1.columns)
    ordered_keys = [_header_key(col) for col in ordered_columns]

    for event_key, event_label, phrases in _SEQUENCE_RULES:
        match_index: int | None = None
        for idx, key in enumerate(ordered_keys):
            if any(phrase in key for phrase in phrases):
                match_index = idx
                break
        if match_index is not None:
            selected[event_key] = (event_label, str(ordered_columns[match_index]))
    return selected


def _repair_sequence(points: list[SequencePoint]) -> list[SequencePoint]:
    repaired: list[SequencePoint] = []
    previous_corrected: int | None = None
    previous_event: str | None = None

    for point in points:
        corrected = point.parsed_minute
        applied = "none"
        reason = "parse_ok"

        if point.parsed_minute is None:
            if point.parse_kind == "blank":
                reason = "missing_time_value"
            else:
                reason = "unparseable_time_value"
        elif previous_corrected is not None and point.parsed_minute < previous_corrected:
            plus12 = point.parsed_minute + 720
            plus24 = point.parsed_minute + 1440
            if plus12 >= previous_corrected:
                corrected = plus12
                applied = "+12h"
                reason = f"non_monotonic_after_{previous_event};prefer_smallest_forward"
            elif plus24 >= previous_corrected:
                corrected = plus24
                applied = "+24h"
                reason = f"non_monotonic_after_{previous_event};+12h_insufficient"
            else:
                corrected = point.parsed_minute
                applied = "unresolved"
                reason = f"non_monotonic_after_{previous_event};no_forward_fix_found"

        repaired_point = SequencePoint(
            event_key=point.event_key,
            event_label=point.event_label,
            column_name=point.column_name,
            raw_value=point.raw_value,
            parsed_minute=point.parsed_minute,
            parse_kind=point.parse_kind,
            corrected_minute=corrected,
            correction_applied=applied,
            correction_reason=reason,
        )
        repaired.append(repaired_point)

        if corrected is not None:
            previous_corrected = corrected
            previous_event = point.event_key
    return repaired


def _build_sequence_points(
    row: pd.Series,
    sequence_columns: dict[str, tuple[str, str]],
) -> list[SequencePoint]:
    points: list[SequencePoint] = []
    for event_key, (event_label, column_name) in sequence_columns.items():
        parsed = parse_time_value(row[column_name])
        points.append(
            SequencePoint(
                event_key=event_key,
                event_label=event_label,
                column_name=column_name,
                raw_value=parsed.raw_text,
                parsed_minute=parsed.minute_of_day,
                parse_kind=parsed.parse_kind,
                corrected_minute=parsed.minute_of_day,
                correction_applied="none",
                correction_reason="parse_ok",
            )
        )
    return points


def run_tff_bounded_normalization(*, workbook_path: Path, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        sheet1 = pd.read_excel(
            workbook_path,
            sheet_name=SHEET1_NAME,
            usecols=SHEET1_USECOLS,
            dtype=object,
            engine="openpyxl",
        )
    except (ParserError, ValueError):
        # Some workbooks have fewer than BK materialized columns in tests/smaller exports.
        sheet1_full = pd.read_excel(
            workbook_path,
            sheet_name=SHEET1_NAME,
            dtype=object,
            engine="openpyxl",
        )
        sheet1 = sheet1_full.iloc[:, :63].copy()
    sheet2_ids = pd.read_excel(
        workbook_path,
        sheet_name=SHEET2_NAME,
        usecols=[SECONDARY_CASE_ID_COLUMN],
        dtype=object,
        engine="openpyxl",
    )

    if PRIMARY_CASE_ID_COLUMN not in sheet1.columns:
        raise ValueError(f"Missing required primary case ID column: {PRIMARY_CASE_ID_COLUMN}")

    site_column = _select_site_column([str(col) for col in sheet1.columns])
    timing_column_report = _identify_timing_columns(sheet1)
    sequence_columns = _select_sequence_columns(sheet1)

    secondary_case_ids: set[str] = set()
    for raw_id in sheet2_ids[SECONDARY_CASE_ID_COLUMN]:
        canonical, status = canonicalize_case_id(raw_id)
        if canonical and status.startswith("ok_"):
            secondary_case_ids.add(canonical)

    case_rows: list[dict[str, Any]] = []
    case_alignment_rows: list[dict[str, Any]] = []
    correction_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []

    canonical_counter: dict[str, int] = {}

    for row_index, row in sheet1.iterrows():
        excel_row = _to_excel_row_number(row_index)
        raw_case_id = row[PRIMARY_CASE_ID_COLUMN]
        canonical_case_id, case_status = canonicalize_case_id(raw_case_id)
        case_soft_fail = not case_status.startswith("ok_")

        if canonical_case_id:
            canonical_counter[canonical_case_id] = canonical_counter.get(canonical_case_id, 0) + 1

        raw_site = row[site_column] if site_column is not None else ""
        site_label_normalized, site_key = _normalize_site_label(raw_site)
        guessed_site_code = _guess_site_code(site_label_normalized)

        sequence_points = _build_sequence_points(row, sequence_columns)
        repaired_points = _repair_sequence(sequence_points)

        normalized_case_row: dict[str, Any] = {
            "sheet1_row_number": excel_row,
            "generated_treatment_id_raw": "" if _is_blank(raw_case_id) else _normalize_text(str(raw_case_id)),
            "case_id": canonical_case_id or "",
            "case_id_status": case_status,
            "case_id_soft_fail": case_soft_fail,
            "site_label_raw": "" if _is_blank(raw_site) else _normalize_text(str(raw_site)),
            "site_label_normalized": site_label_normalized,
            "site_key": site_key,
            "guessed_site_code": guessed_site_code,
        }

        row_has_unresolved_timing = False
        row_has_plus24 = False
        for point in repaired_points:
            normalized_case_row[f"{point.event_key}_raw"] = point.raw_value
            normalized_case_row[f"{point.event_key}_parse_kind"] = point.parse_kind
            normalized_case_row[f"{point.event_key}_minute"] = (
                point.parsed_minute if point.parsed_minute is not None else ""
            )
            normalized_case_row[f"{point.event_key}_minute_corrected"] = (
                point.corrected_minute if point.corrected_minute is not None else ""
            )
            normalized_case_row[f"{point.event_key}_correction"] = point.correction_applied

            correction_rows.append(
                {
                    "sheet1_row_number": excel_row,
                    "case_id": canonical_case_id or "",
                    "generated_treatment_id_raw": normalized_case_row["generated_treatment_id_raw"],
                    "event_key": point.event_key,
                    "event_label": point.event_label,
                    "source_column": point.column_name,
                    "raw_value": point.raw_value,
                    "parse_kind": point.parse_kind,
                    "parsed_minute": point.parsed_minute if point.parsed_minute is not None else "",
                    "corrected_minute": point.corrected_minute if point.corrected_minute is not None else "",
                    "correction_applied": point.correction_applied,
                    "correction_reason": point.correction_reason,
                }
            )

            if point.correction_applied == "unresolved":
                row_has_unresolved_timing = True
            if point.correction_applied == "+24h":
                row_has_plus24 = True

        case_rows.append(normalized_case_row)

        in_secondary = bool(canonical_case_id and canonical_case_id in secondary_case_ids)
        case_alignment_rows.append(
            {
                "sheet1_row_number": excel_row,
                "generated_treatment_id_raw": normalized_case_row["generated_treatment_id_raw"],
                "case_id": canonical_case_id or "",
                "case_id_status": case_status,
                "case_id_soft_fail": case_soft_fail,
                "appears_in_sheet2_patientid": in_secondary,
            }
        )

        if case_soft_fail:
            unresolved_rows.append(
                {
                    "sheet1_row_number": excel_row,
                    "issue_type": "case_id_soft_fail",
                    "case_id_raw": normalized_case_row["generated_treatment_id_raw"],
                    "case_id": canonical_case_id or "",
                    "detail": case_status,
                }
            )
        if row_has_plus24:
            unresolved_rows.append(
                {
                    "sheet1_row_number": excel_row,
                    "issue_type": "timing_plus24_used",
                    "case_id_raw": normalized_case_row["generated_treatment_id_raw"],
                    "case_id": canonical_case_id or "",
                    "detail": "one_or_more_events_required_plus24h_forward_adjustment",
                }
            )
        if row_has_unresolved_timing:
            unresolved_rows.append(
                {
                    "sheet1_row_number": excel_row,
                    "issue_type": "timing_unresolved_non_monotonic",
                    "case_id_raw": normalized_case_row["generated_treatment_id_raw"],
                    "case_id": canonical_case_id or "",
                    "detail": "non_monotonic_sequence_not_repairable_with_plus12_or_plus24",
                }
            )

    case_table_df = pd.DataFrame(case_rows)
    alignment_df = pd.DataFrame(case_alignment_rows)
    correction_df = pd.DataFrame(correction_rows)
    unresolved_df = pd.DataFrame(unresolved_rows)

    if not alignment_df.empty:
        alignment_df["duplicate_case_id_in_sheet1"] = alignment_df["case_id"].map(
            lambda value: bool(value) and canonical_counter.get(value, 0) > 1
        )

    if site_column is not None:
        site_mapping_df = _build_site_normalization_table(case_table_df)
        case_table_df = case_table_df.merge(
            site_mapping_df[
                [
                    "site_label_raw",
                    "site_label_normalized",
                    "site_key",
                    "mapping_status",
                    "normalized_site_code",
                    "mapping_reason",
                    "candidate_site_codes",
                ]
            ],
            on=["site_label_raw", "site_label_normalized", "site_key"],
            how="left",
        )
    else:
        site_mapping_df = pd.DataFrame(
            columns=[
                "site_label_raw",
                "site_label_normalized",
                "site_key",
                "row_count",
                "unique_case_ids",
                "rows_with_case_site_code",
                "mapping_status",
                "normalized_site_code",
                "mapping_reason",
                "candidate_site_codes",
                "candidate_site_code_counts",
            ]
        )
        case_table_df["mapping_status"] = "unmapped"
        case_table_df["normalized_site_code"] = ""
        case_table_df["mapping_reason"] = "no_site_column_detected"
        case_table_df["candidate_site_codes"] = ""

    case_table_df["mapping_status"] = (
        case_table_df["mapping_status"].fillna("unmapped").astype(str)
    )
    case_table_df["normalized_site_code"] = (
        case_table_df["normalized_site_code"].fillna("").astype(str)
    )
    case_table_df["mapping_reason"] = (
        case_table_df["mapping_reason"].fillna("unmapped_no_rule").astype(str)
    )
    case_table_df["candidate_site_codes"] = (
        case_table_df["candidate_site_codes"].fillna("").astype(str)
    )

    if not case_table_df.empty:
        site_unresolved = case_table_df[case_table_df["mapping_status"] != "mapped"]
        if not site_unresolved.empty:
            site_issue_rows = site_unresolved[
                [
                    "sheet1_row_number",
                    "generated_treatment_id_raw",
                    "case_id",
                    "mapping_status",
                    "mapping_reason",
                ]
            ].copy()
            site_issue_rows = site_issue_rows.rename(
                columns={
                    "generated_treatment_id_raw": "case_id_raw",
                    "mapping_reason": "detail",
                }
            )
            site_issue_rows["issue_type"] = site_issue_rows["mapping_status"].map(
                lambda status: "site_ambiguous" if status == "ambiguous" else "site_unmapped"
            )
            site_issue_rows = site_issue_rows[
                ["sheet1_row_number", "issue_type", "case_id_raw", "case_id", "detail"]
            ]
            unresolved_df = pd.concat([unresolved_df, site_issue_rows], ignore_index=True)

    site_mapped_rows = int((case_table_df["mapping_status"] == "mapped").sum()) if not case_table_df.empty else 0
    site_unmapped_rows = int((case_table_df["mapping_status"] == "unmapped").sum()) if not case_table_df.empty else 0
    site_ambiguous_rows = int((case_table_df["mapping_status"] == "ambiguous").sum()) if not case_table_df.empty else 0

    label_mapped = int((site_mapping_df["mapping_status"] == "mapped").sum()) if not site_mapping_df.empty else 0
    label_unmapped = int((site_mapping_df["mapping_status"] == "unmapped").sum()) if not site_mapping_df.empty else 0
    label_ambiguous = int((site_mapping_df["mapping_status"] == "ambiguous").sum()) if not site_mapping_df.empty else 0

    summary_path = output_dir / "tff_bounded_normalization_summary.md"
    summary_lines = [
        "# TFF Bounded Normalization Summary",
        "",
        f"- workbook: `{workbook_path}`",
        f"- source scope: `{SHEET1_NAME}!{SHEET1_USECOLS}`",
        f"- primary case ID: `{PRIMARY_CASE_ID_COLUMN}`",
        f"- secondary fallback/reference: `{SHEET2_NAME}::{SECONDARY_CASE_ID_COLUMN}`",
        "",
        "## Row Counts",
        f"- normalized case rows: {len(case_table_df)}",
        f"- case-id alignment rows: {len(alignment_df)}",
        f"- timing correction audit rows: {len(correction_df)}",
        f"- unresolved/soft-fail rows: {len(unresolved_df)}",
        "",
        "## Case ID Soft-Fail",
        f"- soft-fail rows: {int(alignment_df['case_id_soft_fail'].sum()) if not alignment_df.empty else 0}",
        "",
        "## Site Normalization Status",
        f"- mapped rows: {site_mapped_rows}",
        f"- unmapped rows: {site_unmapped_rows}",
        f"- ambiguous rows: {site_ambiguous_rows}",
        f"- mapped labels: {label_mapped}",
        f"- unmapped labels: {label_unmapped}",
        f"- ambiguous labels: {label_ambiguous}",
        "",
        "## Timing Correction Signals",
        f"- +12h corrections: {int((correction_df['correction_applied'] == '+12h').sum()) if not correction_df.empty else 0}",
        f"- +24h corrections: {int((correction_df['correction_applied'] == '+24h').sum()) if not correction_df.empty else 0}",
        f"- unresolved timing corrections: {int((correction_df['correction_applied'] == 'unresolved').sum()) if not correction_df.empty else 0}",
    ]
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    site_summary_path = output_dir / "tff_site_normalization_summary.md"
    site_summary_lines = [
        "# TFF Site Normalization Summary",
        "",
        f"- workbook: `{workbook_path}`",
        f"- source scope: `{SHEET1_NAME}!{SHEET1_USECOLS}`",
        "",
        "## Label-Level Classification",
        f"- mapped labels: {label_mapped}",
        f"- unmapped labels: {label_unmapped}",
        f"- ambiguous labels: {label_ambiguous}",
        "",
        "## Row-Level Coverage",
        f"- mapped rows: {site_mapped_rows}",
        f"- unmapped rows: {site_unmapped_rows}",
        f"- ambiguous rows: {site_ambiguous_rows}",
    ]
    site_summary_path.write_text("\n".join(site_summary_lines) + "\n", encoding="utf-8")

    paths = {
        "normalized_case_table": output_dir / "tff_normalized_case_table.csv",
        "case_id_alignment_report": output_dir / "tff_case_id_alignment_report.csv",
        "site_mapping_report": output_dir / "tff_site_mapping_report.csv",
        "site_normalization_table": output_dir / "tff_site_normalization_table.csv",
        "site_normalization_summary": site_summary_path,
        "time_correction_audit_report": output_dir / "tff_time_correction_audit_report.csv",
        "unresolved_soft_fail_report": output_dir / "tff_unresolved_soft_fail_report.csv",
        "timing_column_report": output_dir / "tff_timing_column_report.csv",
        "summary": summary_path,
    }

    case_table_df.to_csv(paths["normalized_case_table"], index=False)
    alignment_df.to_csv(paths["case_id_alignment_report"], index=False)
    site_mapping_df.to_csv(paths["site_mapping_report"], index=False)
    site_mapping_df.to_csv(paths["site_normalization_table"], index=False)
    correction_df.to_csv(paths["time_correction_audit_report"], index=False)
    unresolved_df.to_csv(paths["unresolved_soft_fail_report"], index=False)
    timing_column_report.to_csv(paths["timing_column_report"], index=False)
    return paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded TFF normalization/export slice. "
            "Reads Sheet1!A:BK, normalizes case IDs, site labels, and timing corrections."
        )
    )
    parser.add_argument("--workbook", required=True, help="Path to Treatment Feedback Forms Output.xlsx")
    parser.add_argument(
        "--output",
        required=True,
        help="Output directory for normalized table and audit artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    paths = run_tff_bounded_normalization(
        workbook_path=Path(args.workbook),
        output_dir=Path(args.output),
    )
    for key, path in paths.items():
        print(f"{key}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
