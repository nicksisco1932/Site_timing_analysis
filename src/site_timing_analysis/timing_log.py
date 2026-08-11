# Project: Site Timing Analysis
# File: src/site_timing_analysis/timing_log.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-03-11
# Purpose: Finds and parses optional timing-log CSV files for timing enrichment.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .errors import TimingLogParseError
from .models import TimingLogEntry


_EXPLICIT_COLUMNS = ("Events", "TimeSTART", "TimeEND")
_POS_EVENT_IDX = 2
_POS_START_IDX = 3
_POS_END_IDX = 4


def find_timing_log(
    case_id: str,
    resolved_site_root: Path,
    timing_log_dir_override: Path | None = None,
) -> Path | None:
    base_dir = timing_log_dir_override if timing_log_dir_override is not None else resolved_site_root / "TimingLogs"
    path = base_dir / f"{case_id}.csv"
    if path.exists() and path.is_file():
        return path.resolve()
    return None


def _parse_optional_datetime(
    raw_value: str | None,
    *,
    case_id: str,
    source_path: Path,
    row_number: int,
    field_name: str,
) -> tuple[datetime | None, str | None]:
    if raw_value is None:
        return None, None

    text = raw_value.strip()
    if text == "":
        return None, None

    normalized = text.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    if "." in normalized:
        left, right = normalized.split(".", 1)
        frac = right
        tz_suffix = ""
        if "+" in right:
            frac, tz_suffix = right.split("+", 1)
            tz_suffix = "+" + tz_suffix
        elif "-" in right[1:]:
            split_at = right[1:].find("-") + 1
            frac, tz_suffix = right[:split_at], right[split_at:]
        frac = frac[:6].ljust(6, "0")
        normalized = f"{left}.{frac}{tz_suffix}"

    try:
        return datetime.fromisoformat(normalized), None
    except ValueError:
        warning = (
            f"{case_id}:timing_log_unparseable_datetime:"
            f"{source_path.name}:row={row_number}:field={field_name}:value={text}"
        )
        return None, warning


def parse_timing_log_csv(path: Path, case_id: str) -> tuple[list[TimingLogEntry], list[str]]:
    if not path.exists():
        return [], []

    warnings: list[str] = []

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    except OSError as exc:
        raise TimingLogParseError(case_id, path, f"Failed to read timing-log CSV: {exc}") from exc

    if not rows:
        raise TimingLogParseError(case_id, path, "Timing-log CSV is empty.")

    header = [col.strip() for col in rows[0]]
    has_explicit = all(name in header for name in _EXPLICIT_COLUMNS)
    has_positional = len(header) >= 5
    if not has_explicit and not has_positional:
        raise TimingLogParseError(
            case_id,
            path,
            "Timing-log CSV missing expected columns. "
            "Expected explicit headers (Events, TimeSTART, TimeEND) "
            "or at least 5 columns for positional fallback.",
        )

    if len(rows) == 1:
        raise TimingLogParseError(case_id, path, "Timing-log CSV has header only and no data rows.")

    entries: list[TimingLogEntry] = []
    if has_explicit:
        events_idx = header.index("Events")
        start_idx = header.index("TimeSTART")
        end_idx = header.index("TimeEND")
    else:
        events_idx = _POS_EVENT_IDX
        start_idx = _POS_START_IDX
        end_idx = _POS_END_IDX

    for line_idx, row in enumerate(rows[1:], start=2):
        if len(row) <= max(events_idx, start_idx, end_idx):
            raise TimingLogParseError(
                case_id,
                path,
                f"Row {line_idx} does not contain required timing-log columns.",
            )

        label_raw = row[events_idx]
        start_raw = row[start_idx]
        end_raw = row[end_idx]

        if label_raw.strip() == "" and start_raw.strip() == "" and end_raw.strip() == "":
            warnings.append(f"{case_id}:timing_log_blank_row:{path.name}:row={line_idx}")
            continue

        time_start, start_warning = _parse_optional_datetime(
            start_raw,
            case_id=case_id,
            source_path=path,
            row_number=line_idx,
            field_name="TimeSTART",
        )
        if start_warning:
            warnings.append(start_warning)

        time_end, end_warning = _parse_optional_datetime(
            end_raw,
            case_id=case_id,
            source_path=path,
            row_number=line_idx,
            field_name="TimeEND",
        )
        if end_warning:
            warnings.append(end_warning)

        entries.append(
            TimingLogEntry(
                case_id=case_id,
                source_file=path.resolve(),
                row_number=line_idx,
                label_text=label_raw,
                time_start_raw=start_raw if start_raw.strip() != "" else None,
                time_end_raw=end_raw if end_raw.strip() != "" else None,
                time_start=time_start,
                time_end=time_end,
            )
        )

    return entries, warnings
