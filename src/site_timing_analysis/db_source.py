from __future__ import annotations

import zipfile
from pathlib import Path

from .errors import (
    AmbiguousDatabaseSourceError,
    DatabaseReadError,
    DatabaseSourceNotFoundError,
)
from .models import CaseDiscoveryRecord, DatabaseSourceRecord


def _resolve_candidate_index(
    *,
    case_id: str,
    candidates: list[str],
    context: str,
    allow_ambiguous: bool,
    selected_index: int | None,
) -> tuple[int, list[str]]:
    if len(candidates) == 1:
        return 0, []

    if not allow_ambiguous:
        raise AmbiguousDatabaseSourceError(case_id=case_id, candidates=candidates, context=context)

    if selected_index is None:
        raise AmbiguousDatabaseSourceError(case_id=case_id, candidates=candidates, context=context)

    if selected_index < 0 or selected_index >= len(candidates):
        raise AmbiguousDatabaseSourceError(
            case_id=case_id,
            candidates=candidates,
            context=f"{context} (invalid selected_index={selected_index})",
        )

    extras = [candidate for idx, candidate in enumerate(candidates) if idx != selected_index]
    return selected_index, extras


def _find_localdb_members(zip_path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            return [name for name in zip_file.namelist() if name.lower().endswith("local.db")]
    except (zipfile.BadZipFile, OSError) as exc:
        raise DatabaseReadError(zip_path, f"Failed to inspect zip archive: {exc}") from exc


def resolve_database_source(
    case_record: CaseDiscoveryRecord,
    *,
    allow_ambiguous: bool = False,
    db_candidate_index: int | None = None,
    zip_member_index: int | None = None,
) -> DatabaseSourceRecord:
    unzipped = [str(path) for path in case_record.candidate_unzipped_db_paths]
    zip_candidates = [str(path) for path in case_record.candidate_zip_paths]
    warnings = list(case_record.warnings)

    if unzipped:
        selected_idx, ambiguous = _resolve_candidate_index(
            case_id=case_record.case_id,
            candidates=unzipped,
            context="unzipped local.db candidates",
            allow_ambiguous=allow_ambiguous,
            selected_index=db_candidate_index,
        )
        selected_path = Path(unzipped[selected_idx])
        return DatabaseSourceRecord(
            case_id=case_record.case_id,
            case_path=case_record.case_path,
            source_type="unzipped",
            source_path=selected_path,
            selected_zip_member=None,
            resolution_rule="unzipped_precedence",
            candidate_unzipped_db_paths=list(case_record.candidate_unzipped_db_paths),
            candidate_zip_paths=list(case_record.candidate_zip_paths),
            ambiguous_candidates=ambiguous,
            warnings=warnings,
        )

    zip_with_localdb: list[tuple[Path, list[str]]] = []
    for zip_path in case_record.candidate_zip_paths:
        members = _find_localdb_members(zip_path)
        if not members:
            warnings.append(f"zip_without_localdb:{zip_path}")
            continue
        zip_with_localdb.append((zip_path, members))

    if not zip_with_localdb:
        raise DatabaseSourceNotFoundError(
            case_id=case_record.case_id,
            message="No unzipped local.db and no zip containing local.db found.",
        )

    zip_candidates_with_members = [str(item[0]) for item in zip_with_localdb]
    zip_idx, zip_ambiguous = _resolve_candidate_index(
        case_id=case_record.case_id,
        candidates=zip_candidates_with_members,
        context="zip candidates containing local.db",
        allow_ambiguous=allow_ambiguous,
        selected_index=db_candidate_index,
    )
    selected_zip, members = zip_with_localdb[zip_idx]

    member_idx, member_ambiguous = _resolve_candidate_index(
        case_id=case_record.case_id,
        candidates=members,
        context=f"local.db members in zip {selected_zip}",
        allow_ambiguous=allow_ambiguous,
        selected_index=zip_member_index,
    )

    selected_member = members[member_idx]
    return DatabaseSourceRecord(
        case_id=case_record.case_id,
        case_path=case_record.case_path,
        source_type="zip_extracted",
        source_path=selected_zip,
        selected_zip_member=selected_member,
        resolution_rule="zip_precedence",
        candidate_unzipped_db_paths=list(case_record.candidate_unzipped_db_paths),
        candidate_zip_paths=list(case_record.candidate_zip_paths),
        ambiguous_candidates=[*zip_ambiguous, *member_ambiguous],
        warnings=warnings,
    )
