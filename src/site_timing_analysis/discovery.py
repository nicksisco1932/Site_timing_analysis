from __future__ import annotations

import glob
from pathlib import Path
import re

from .errors import DiscoveryError
from .models import RunConfig, CaseDiscoveryRecord


_UNZIPPED_PATTERNS = [
    ("*", "_*", "local.db"),
    ("_*", "local.db"),
    ("local.db",),
]

_ZIP_PATTERNS = [
    ("TDC Sessions", "_*.zip"),
    ("_201*.zip",),
    ("*", "_201*.zip"),
    ("Session*.zip",),
]


def _glob_sorted(case_path: Path, pattern_parts: tuple[str, ...]) -> list[Path]:
    pattern = str(case_path.joinpath(*pattern_parts))
    matches = sorted(glob.glob(pattern), key=lambda s: s.lower())
    return [Path(m).resolve() for m in matches]


def _dedupe_preserve_order(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        deduped.append(path)
        seen.add(path)
    return deduped


def _expected_case_prefix(site_code: str) -> str | None:
    match = re.search(r"_(\d{3})$", str(site_code).strip())
    if match is None:
        return None
    return f"{match.group(1)}_"


def discover_cases(config: RunConfig) -> list[CaseDiscoveryRecord]:
    site_root = config.site_path if config.site_path is not None else config.root_dir / config.site_code
    if not site_root.exists() or not site_root.is_dir():
        raise DiscoveryError(f"Site path not found or not a directory: {site_root}")

    case_dirs = [path for path in site_root.iterdir() if path.is_dir()]
    expected_prefix = _expected_case_prefix(config.site_code)
    if expected_prefix is not None:
        case_dirs = [path for path in case_dirs if path.name.startswith(expected_prefix)]
    case_dirs = sorted(case_dirs, key=lambda p: p.name.lower())

    records: list[CaseDiscoveryRecord] = []
    for index, case_path in enumerate(case_dirs, start=1):
        case_warnings: list[str] = []

        unzipped_candidates: list[Path] = []
        for pattern in _UNZIPPED_PATTERNS:
            unzipped_candidates.extend(_glob_sorted(case_path, pattern))
        ordered_unzipped = _dedupe_preserve_order(unzipped_candidates)

        zip_candidates: list[Path] = []
        for pattern in _ZIP_PATTERNS:
            zip_candidates.extend(_glob_sorted(case_path, pattern))
        ordered_zip = _dedupe_preserve_order(zip_candidates)

        if not ordered_unzipped and not ordered_zip:
            case_warnings.append("no_database_candidates_found")
        if len(ordered_unzipped) > 1:
            case_warnings.append("multiple_unzipped_database_candidates")
        if len(ordered_zip) > 1:
            case_warnings.append("multiple_zip_candidates")

        records.append(
            CaseDiscoveryRecord(
                site_code=config.site_code,
                case_id=case_path.name,
                case_path=case_path.resolve(),
                discovery_order=index,
                candidate_unzipped_db_paths=ordered_unzipped,
                candidate_zip_paths=ordered_zip,
                warnings=case_warnings,
            )
        )

    return records
