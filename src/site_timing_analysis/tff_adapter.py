from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_WORKFLOW_TIMING_FIELDS: tuple[str, ...] = (
    "patient_enters_mri",
    "anesthesia_start_prepare",
    "patient_sedated",
    "device_insertion_begins",
    "device_insertion_complete",
    "patient_leaves_mri",
    "patient_transfer_recovery",
)

_WORKFLOW_TIMING_LABELS: dict[str, str] = {
    "patient_enters_mri": "Patient enters MRI room",
    "anesthesia_start_prepare": "Anesthesia starts to prepare the patient",
    "patient_sedated": "Patient is sedated",
    "device_insertion_begins": "Device Insertion Begins",
    "device_insertion_complete": "Device Insertion Complete",
    "patient_leaves_mri": "Patient leaves MRI room",
    "patient_transfer_recovery": "Patient Transfer to Recovery room",
}

_KNOWN_EXCLUSION_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "rct_stanford_sta",
        "known_stanford_rct_case_pattern:^STA_01-00[3-8]$",
        re.compile(r"^STA_01-00[3-8]$"),
    ),
)


@dataclass(slots=True)
class _TFFJoinedCase:
    case_id: str
    source_row: int | None
    time_corrected: bool
    correction_type: str
    parse_status: str
    timing_payload: dict[str, str]


@dataclass(slots=True)
class _KnownExclusionMatch:
    exclusion_class: str
    exclusion_rule: str


def default_tff_case_table_path(output_dir: Path) -> Path:
    return output_dir / "tff_audit" / "tff_normalized_case_table.csv"


def _is_truthy(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y"}


def _parse_optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _select_parse_status(parse_kinds: list[str], correction_types: list[str]) -> str:
    if any(correction == "unresolved" for correction in correction_types):
        return "unresolved"
    if any(kind == "unparseable" for kind in parse_kinds):
        return "unresolved"
    if all(kind in {"", "blank"} for kind in parse_kinds):
        return "blank"
    if any(kind in {"", "blank"} for kind in parse_kinds):
        return "partial"
    return "ok"


def _required_columns() -> list[str]:
    columns = ["case_id", "case_id_soft_fail", "sheet1_row_number"]
    for field in _WORKFLOW_TIMING_FIELDS:
        columns.extend(
            [
                f"{field}_minute_corrected",
                f"{field}_parse_kind",
                f"{field}_correction",
            ]
        )
    return columns


def _choose_preferred_row(current: _TFFJoinedCase, candidate: _TFFJoinedCase) -> _TFFJoinedCase:
    # Deterministic duplicate handling: prefer the earliest source row.
    if current.source_row is None and candidate.source_row is None:
        return current
    if current.source_row is None:
        return candidate
    if candidate.source_row is None:
        return current
    return candidate if candidate.source_row < current.source_row else current


def _build_joined_tff_case(row: dict[str, str]) -> _TFFJoinedCase:
    parse_kinds: list[str] = []
    correction_types: list[str] = []
    timing_payload: dict[str, str] = {}

    for field in _WORKFLOW_TIMING_FIELDS:
        timing_payload[f"tff_{field}_label"] = _WORKFLOW_TIMING_LABELS[field]
        timing_payload[f"tff_{field}_minute"] = str(row.get(f"{field}_minute_corrected", "")).strip()
        timing_payload[f"tff_{field}_parse_kind"] = str(row.get(f"{field}_parse_kind", "")).strip()
        timing_payload[f"tff_{field}_correction"] = str(row.get(f"{field}_correction", "")).strip()
        parse_kinds.append(timing_payload[f"tff_{field}_parse_kind"])
        correction_types.append(timing_payload[f"tff_{field}_correction"])

    correction_set = sorted(
        {
            correction
            for correction in correction_types
            if correction not in {"", "none"}
        }
    )
    return _TFFJoinedCase(
        case_id=str(row.get("case_id", "")).strip(),
        source_row=_parse_optional_int(row.get("sheet1_row_number")),
        time_corrected=any(correction not in {"", "none"} for correction in correction_types),
        correction_type="|".join(correction_set) if correction_set else "none",
        parse_status=_select_parse_status(parse_kinds, correction_types),
        timing_payload=timing_payload,
    )


def _match_known_exclusion(case_id: str) -> _KnownExclusionMatch | None:
    normalized = str(case_id or "").strip().upper()
    if not normalized:
        return None
    for exclusion_class, exclusion_rule, pattern in _KNOWN_EXCLUSION_RULES:
        if pattern.fullmatch(normalized):
            return _KnownExclusionMatch(
                exclusion_class=exclusion_class,
                exclusion_rule=exclusion_rule,
            )
    return None


def _load_tff_cases(tff_case_table: Path) -> tuple[dict[str, _TFFJoinedCase], dict[str, int], list[str]]:
    stats = {
        "rows_total": 0,
        "rows_case_id_soft_fail": 0,
        "rows_missing_case_id": 0,
        "rows_usable": 0,
        "duplicate_case_ids": 0,
    }
    warnings: list[str] = []
    cases_by_id: dict[str, _TFFJoinedCase] = {}

    if not tff_case_table.exists():
        warnings.append(f"tff_adapter:tff_case_table_missing:{tff_case_table}")
        return cases_by_id, stats, warnings

    with tff_case_table.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing_columns = [column for column in _required_columns() if column not in fieldnames]
        if missing_columns:
            warnings.append(
                "tff_adapter:tff_case_table_missing_columns:"
                + "|".join(sorted(missing_columns))
            )
            return cases_by_id, stats, warnings

        for row in reader:
            stats["rows_total"] += 1
            case_id = str(row.get("case_id", "")).strip()
            if not case_id:
                stats["rows_missing_case_id"] += 1
                continue
            if _is_truthy(row.get("case_id_soft_fail")):
                stats["rows_case_id_soft_fail"] += 1
                continue

            candidate = _build_joined_tff_case(row)
            current = cases_by_id.get(case_id)
            if current is None:
                cases_by_id[case_id] = candidate
                stats["rows_usable"] += 1
                continue

            stats["duplicate_case_ids"] += 1
            preferred = _choose_preferred_row(current, candidate)
            cases_by_id[case_id] = preferred
            kept_row = preferred.source_row if preferred.source_row is not None else "unknown"
            warnings.append(f"tff_adapter:duplicate_case_id:{case_id}:kept_source_row={kept_row}")

    return cases_by_id, stats, warnings


def _write_filtered_known_exclusions_csv(
    *,
    filtered_rows: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    out_dir = output_dir / "tff_adapter"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tff_filtered_known_exclusions.csv"
    fieldnames = [
        "case_id",
        "status",
        "tff_join_status",
        "tff_exclusion_class",
        "tff_exclusion_rule",
        "tff_exclusion_reason",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in filtered_rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return out_path


def _write_joined_case_dataset(
    *,
    joined_rows: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    out_dir = output_dir / "tff_adapter"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tff_case_join.csv"

    fieldnames = [
        "case_id",
        "status",
        "tff_join_status",
        "tff_source_row",
        "tff_time_corrected",
        "tff_correction_type",
        "tff_parse_status",
    ]
    for field in _WORKFLOW_TIMING_FIELDS:
        fieldnames.extend(
            [
                f"tff_{field}_label",
                f"tff_{field}_minute",
                f"tff_{field}_parse_kind",
                f"tff_{field}_correction",
            ]
        )

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in joined_rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return out_path


def _write_integration_summary(
    *,
    output_dir: Path,
    tff_case_table: Path,
    stats: dict[str, int],
    pipeline_case_rows_total: int,
    pipeline_case_rows_considered: int,
    matched_count: int,
    filtered_known_exclusions_count: int,
    true_unmatched_pipeline_count: int,
    unmatched_tff_count: int,
    known_exclusion_filter_enabled: bool,
) -> Path:
    out_dir = output_dir / "tff_adapter"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tff_integration_summary.md"

    lines = [
        "# TFF Read-Only Adapter Summary",
        "",
        f"- tff_normalized_case_table: `{tff_case_table}`",
        f"- known exclusion filter enabled: `{known_exclusion_filter_enabled}`",
        f"- pipeline case rows total: `{pipeline_case_rows_total}`",
        f"- pipeline case rows considered for join-quality metrics: `{pipeline_case_rows_considered}`",
        f"- matched by canonical case_id: `{matched_count}`",
        f"- filtered known exclusions: `{filtered_known_exclusions_count}`",
        f"- true unmatched pipeline cases: `{true_unmatched_pipeline_count}`",
        f"- TFF cases without pipeline match: `{unmatched_tff_count}`",
        "",
        "## TFF Table Intake",
        f"- rows_total: `{stats['rows_total']}`",
        f"- rows_usable: `{stats['rows_usable']}`",
        f"- rows_case_id_soft_fail: `{stats['rows_case_id_soft_fail']}`",
        f"- rows_missing_case_id: `{stats['rows_missing_case_id']}`",
        f"- duplicate_case_ids: `{stats['duplicate_case_ids']}`",
        "",
        "## Integrated Timing Fields",
    ]
    for field in _WORKFLOW_TIMING_FIELDS:
        lines.append(f"- {_WORKFLOW_TIMING_LABELS[field]}")
    lines.extend(
        [
            "",
            "## Provenance Fields Preserved",
            "- `tff_source_row`",
            "- `tff_time_corrected`",
            "- `tff_correction_type`",
            "- `tff_parse_status`",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def apply_read_only_tff_adapter(
    *,
    case_results: list[dict[str, Any]],
    output_dir: Path,
    tff_case_table: Path | None,
    filter_known_exclusions: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """
    Join bounded TFF normalized metadata onto case-level results by canonical case_id.

    This adapter is read-only:
    - it does not replace existing timing/state values
    - it only appends optional TFF fields and writes adapter artifacts
    """

    resolved_tff_table = (
        tff_case_table.expanduser().resolve()
        if tff_case_table is not None
        else default_tff_case_table_path(output_dir).resolve()
    )

    tff_cases, tff_stats, warnings = _load_tff_cases(resolved_tff_table)
    updated_results: list[dict[str, Any]] = []
    matched_case_ids: set[str] = set()
    filtered_known_exclusion_rows: list[dict[str, Any]] = []

    for case_result in case_results:
        row = dict(case_result)
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            row["tff_join_status"] = "no_case_id"
            updated_results.append(row)
            continue

        if filter_known_exclusions:
            known_exclusion = _match_known_exclusion(case_id)
            if known_exclusion is not None:
                row["tff_join_status"] = "filtered_known_exclusion"
                row["tff_exclusion_class"] = known_exclusion.exclusion_class
                row["tff_exclusion_rule"] = known_exclusion.exclusion_rule
                row["tff_exclusion_reason"] = "known_exclusion_case_class"
                filtered_known_exclusion_rows.append(
                    {
                        "case_id": case_id,
                        "status": str(row.get("status", "")),
                        "tff_join_status": row["tff_join_status"],
                        "tff_exclusion_class": row["tff_exclusion_class"],
                        "tff_exclusion_rule": row["tff_exclusion_rule"],
                        "tff_exclusion_reason": row["tff_exclusion_reason"],
                    }
                )
                updated_results.append(row)
                continue

        joined = tff_cases.get(case_id)
        if joined is None:
            row["tff_join_status"] = "no_tff_match"
            updated_results.append(row)
            continue

        matched_case_ids.add(case_id)
        row["tff_join_status"] = "matched"
        row["tff_source_row"] = joined.source_row
        row["tff_time_corrected"] = joined.time_corrected
        row["tff_correction_type"] = joined.correction_type
        row["tff_parse_status"] = joined.parse_status
        row.update(joined.timing_payload)
        updated_results.append(row)

    pipeline_case_rows_total = sum(
        1 for row in updated_results if str(row.get("case_id", "")).strip()
    )
    filtered_known_exclusions_count = len(filtered_known_exclusion_rows)
    pipeline_case_rows_considered = pipeline_case_rows_total - filtered_known_exclusions_count

    true_unmatched_pipeline_count = sum(
        1 for row in updated_results if str(row.get("tff_join_status", "")) == "no_tff_match"
    )
    eligible_pipeline_case_ids = {
        str(row.get("case_id", "")).strip()
        for row in updated_results
        if str(row.get("case_id", "")).strip()
        and str(row.get("tff_join_status", "")) != "filtered_known_exclusion"
    }
    unmatched_tff_count = len(set(tff_cases.keys()) - eligible_pipeline_case_ids)
    matched_count = len(matched_case_ids)

    if filtered_known_exclusions_count > 0:
        warnings.append(f"tff_adapter:known_exclusions_filtered:{filtered_known_exclusions_count}")
    if true_unmatched_pipeline_count > 0:
        warnings.append(f"tff_adapter:pipeline_cases_without_tff:{true_unmatched_pipeline_count}")
    if unmatched_tff_count > 0:
        warnings.append(f"tff_adapter:tff_cases_without_pipeline_match:{unmatched_tff_count}")

    joined_rows = [
        {
            "case_id": str(row.get("case_id", "")),
            "status": str(row.get("status", "")),
            "tff_join_status": str(row.get("tff_join_status", "")),
            "tff_source_row": row.get("tff_source_row", ""),
            "tff_time_corrected": row.get("tff_time_corrected", ""),
            "tff_correction_type": row.get("tff_correction_type", ""),
            "tff_parse_status": row.get("tff_parse_status", ""),
            **{
                f"tff_{field}_{suffix}": row.get(f"tff_{field}_{suffix}", "")
                for field in _WORKFLOW_TIMING_FIELDS
                for suffix in ("label", "minute", "parse_kind", "correction")
            },
        }
        for row in updated_results
    ]

    joined_path = _write_joined_case_dataset(joined_rows=joined_rows, output_dir=output_dir)
    filtered_path: Path | None = None
    if filter_known_exclusions:
        filtered_path = _write_filtered_known_exclusions_csv(
            filtered_rows=filtered_known_exclusion_rows,
            output_dir=output_dir,
        )
    summary_path = _write_integration_summary(
        output_dir=output_dir,
        tff_case_table=resolved_tff_table,
        stats=tff_stats,
        pipeline_case_rows_total=pipeline_case_rows_total,
        pipeline_case_rows_considered=pipeline_case_rows_considered,
        matched_count=matched_count,
        filtered_known_exclusions_count=filtered_known_exclusions_count,
        true_unmatched_pipeline_count=true_unmatched_pipeline_count,
        unmatched_tff_count=unmatched_tff_count,
        known_exclusion_filter_enabled=filter_known_exclusions,
    )

    artifacts = {
        "tff_case_join": str(joined_path),
        "tff_integration_summary": str(summary_path),
    }
    if filtered_path is not None:
        artifacts["tff_filtered_known_exclusions"] = str(filtered_path)
    return updated_results, artifacts, warnings
