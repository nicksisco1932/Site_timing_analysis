# Project: Site Timing Analysis
# File: testing/tests/test_analytical_store.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Validates the versioned Timeline Analysis SQLite store and SQL-backed export contract.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

import pytest

from site_timing_analysis import analytical_store
from site_timing_analysis.analytical_store import (
    AnalyticalStoreError,
    EVENT_FIELDS,
    INTERVAL_FIELDS,
    PHASE_ORDER,
    REQUESTED_STATES,
    WIDE_HEADERS,
    ParserVersion,
    export_wide,
    import_prepared_run,
    import_run,
    initialize_database,
    list_runs,
    prepare_run_import,
    validate_database_path,
)


@pytest.fixture(autouse=True)
def isolated_repository_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(analytical_store, "REPO_ROOT", repository)


def _parser(tag: str = "parser-a") -> ParserVersion:
    fingerprint = hashlib.sha256(tag.encode("utf-8")).hexdigest().upper()
    return ParserVersion(
        package_version="test",
        git_commit=tag,
        git_dirty=False,
        dirty_fingerprint_sha256=hashlib.sha256(b"").hexdigest().upper(),
        source_fingerprint_sha256=fingerprint,
        provenance_basis="synthetic_test_fixture",
    )


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _build_run(
    root: Path,
    *,
    run_id: str = "run-001",
    site: str = "TEST_001",
    successful_ids: tuple[str, ...] = ("001_01-001",),
    failed_ids: tuple[str, ...] = (),
    source_paths: dict[str, Path] | None = None,
    source_payloads: dict[str, bytes] | None = None,
    year_selection: str = "All",
) -> Path:
    run_dir = root / run_id
    reports = run_dir / "Backend" / "reports"
    manifests = run_dir / "Backend" / "manifests"
    events_dir = run_dir / "Backend" / "events" / "state_labeled"
    intervals_dir = run_dir / "Backend" / "intervals" / "state"
    report_dir = run_dir / "Report"
    for directory in (reports, manifests, events_dir, intervals_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)

    selected = [*successful_ids, *failed_ids]
    source_paths = dict(source_paths or {})
    source_payloads = dict(source_payloads or {})
    manifest_cases: list[dict[str, Any]] = []
    audit_cases: list[dict[str, Any]] = []
    execution_cases: list[dict[str, Any]] = []
    wide_rows: list[dict[str, str]] = []
    reconciliation_rows: list[dict[str, str]] = []
    raw_payload = json.dumps(
        {"PatientId": "synthetic", "nested": {"value": 7}}, sort_keys=True
    )

    for order, case_id in enumerate(selected, start=1):
        if case_id in successful_ids:
            source = source_paths.get(case_id, root / "sources" / case_id / "local.db")
            source.parent.mkdir(parents=True, exist_ok=True)
            if case_id in source_payloads or not source.exists():
                source.write_bytes(source_payloads.get(case_id, b"SQLite format 3\0synthetic"))
            source_paths[case_id] = source
            stat = source.stat()
            event_path = events_dir / f"{case_id}_state_labeled_events.csv"
            interval_path = intervals_dir / f"{case_id}_state_intervals.csv"
            start = "2026-01-01T10:00:00"
            end = "2026-01-01T10:01:05.050000"
            event_row = dict.fromkeys(EVENT_FIELDS, "")
            event_row.update(
                {
                    "case_id": case_id,
                    "timestamp": start,
                    "event_type": "SyntheticEvent",
                    "source": "auditlog",
                    "is_synthetic": "False",
                    "segment_id": "1",
                    "event_kind": "0",
                    "state": "TULSA QA",
                    "state_assignment_rule": "synthetic_rule",
                    "row_number": "7",
                    "source_detail": "synthetic_fixture",
                    "raw_payload_json": raw_payload,
                }
            )
            interval_row = dict.fromkeys(INTERVAL_FIELDS, "")
            interval_row.update(
                {
                    "case_id": case_id,
                    "timestamp": start,
                    "state": "TULSA QA",
                    "start_sec": "-5.0",
                    "duration_sec": "65.05",
                    "rebase_anchor": "LastUAHoming",
                    "origin_event_type": "SyntheticEvent",
                    "source": "auditlog",
                    "is_synthetic": "False",
                    "source_detail": "synthetic_fixture",
                    "row_number": "7",
                    "state_assignment_rule": "synthetic_rule",
                    "quality_flags": (
                        "negative_rebased_start|negative_rebased_start_expected_pre_anchor"
                    ),
                    "segment_id": "1",
                    "event_kind": "0",
                    "raw_payload_json": raw_payload,
                }
            )
            _write_csv(event_path, EVENT_FIELDS, [event_row])
            _write_csv(interval_path, INTERVAL_FIELDS, [interval_row])
            manifest_cases.append(
                {
                    "case_id": case_id,
                    "status": "PASS",
                    "source_type": "unzipped",
                    "source_path": str(source.resolve()),
                    "state_labeled_event_count": 1,
                    "state_labeled_export": str(event_path.resolve()),
                    "state_interval_count": 1,
                    "state_interval_export": str(interval_path.resolve()),
                }
            )
            audit_cases.append(
                {
                    "case_id": case_id,
                    "status": "PASS",
                    "candidate_count": 1,
                    "usable_candidate_count": 1,
                    "candidates": [
                        {
                            "case_id": case_id,
                            "candidate_kind": "unzipped",
                            "candidate_path": str(source.resolve()),
                            "zip_member": "",
                            "source_size_bytes": stat.st_size,
                            "source_mtime_ns": stat.st_mtime_ns,
                            "usable": True,
                        }
                    ],
                }
            )
            execution_cases.append(
                {
                    "case_id": case_id,
                    "pipeline_status": "PASS",
                    "generated_case_id": case_id,
                    "event_status": "PASS",
                    "starttime": start,
                    "endtime": end,
                    "start_provenance": json.dumps(
                        {"source": "AuditLogRecords", "row_number": 7}
                    ),
                    "end_provenance": json.dumps(
                        {"source": "session_timing", "field": "TimePatientTransferredAt"}
                    ),
                    "interval_status": "PASS",
                    "assigned_database_status": "PASS",
                    "identity_status": "PASS",
                    "identity_reason": "synthetic_identity_match",
                    "failures": [],
                    "failure_reason": "",
                }
            )
            wide_row = {field: "0.0" for field in REQUESTED_STATES}
            wide_row.update(
                {
                    "Experience": str(order),
                    "Site": site,
                    "PtId": case_id,
                    "starttime": "10:00:00 AM",
                    "endtime": "10:01:05 AM",
                    "TULSA QA": "1.1",
                }
            )
            wide_rows.append(wide_row)
        else:
            manifest_cases.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "source_type": "",
                    "source_path": "",
                    "state_labeled_event_count": 0,
                    "state_labeled_export": "",
                    "state_interval_count": 0,
                    "state_interval_export": "",
                }
            )
            audit_cases.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "candidate_count": 0,
                    "usable_candidate_count": 0,
                    "candidates": [],
                }
            )
            execution_cases.append(
                {
                    "case_id": case_id,
                    "pipeline_status": "FAIL",
                    "generated_case_id": case_id,
                    "event_status": "FAIL",
                    "starttime": "",
                    "endtime": "",
                    "start_provenance": "{}",
                    "end_provenance": "{}",
                    "interval_status": "FAIL",
                    "assigned_database_status": "FAIL",
                    "identity_status": "PASS",
                    "failures": ["missing_database"],
                    "failure_reason": "missing_database",
                }
            )

        for phase in PHASE_ORDER:
            detailed = 65.05 / 60.0 if case_id in successful_ids and phase == "Pre-op" else 0.0
            reconciliation_rows.append(
                {
                    "case_id": case_id,
                    "phase": phase,
                    "detailed_minutes_unrounded": str(detailed),
                    "rollup_minutes": str(detailed),
                    "difference_minutes": "0.0",
                    "status": "PASS" if case_id in successful_ids else "FAIL",
                    "failure_type": "" if case_id in successful_ids else "missing_database",
                }
            )

    manifest = {
        "run_id": run_id,
        "started_at": "2026-01-02T00:00:00+00:00",
        "completed_at": "2026-01-02T00:01:00+00:00",
        "site_code": site,
        "year_selection": year_selection,
        "root_dir": str(root),
        "output_dir": str((run_dir / "Backend").resolve()),
        "cases_discovered": len(selected),
        "cases_processed": len(successful_ids),
        "cases_failed": len(failed_ids),
        "warnings": [],
        "case_results": manifest_cases,
    }
    execution = {
        "status": "PUBLISHED" if not failed_ids else "PARTIAL_PUBLISHED",
        "exported_row_count": len(successful_ids),
        "cases": execution_cases,
    }
    discovery = {
        "canonical_prefix": "001_",
        "selected_case_ids": selected,
    }
    manifests.joinpath("run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    reports.joinpath("execution_result.json").write_text(
        json.dumps(execution, indent=2), encoding="utf-8"
    )
    reports.joinpath("discovery_selection.json").write_text(
        json.dumps(discovery, indent=2), encoding="utf-8"
    )
    reports.joinpath("database_candidate_audit.json").write_text(
        json.dumps({"cases": audit_cases, "failures": []}, indent=2), encoding="utf-8"
    )
    _write_csv(
        reports / "phase_reconciliation.csv",
        (
            "case_id",
            "phase",
            "detailed_minutes_unrounded",
            "rollup_minutes",
            "difference_minutes",
            "status",
            "failure_type",
        ),
        reconciliation_rows,
    )
    slug = "".join(character.lower() if character.isalnum() else "_" for character in site)
    _write_csv(report_dir / f"{slug}_timeline_analysis.csv", WIDE_HEADERS, wide_rows)
    return run_dir


def _connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_counts(database: Path) -> dict[str, int]:
    names = (
        "parser_versions",
        "sites",
        "cases",
        "source_artifacts",
        "analysis_runs",
        "case_analyses",
        "run_cases",
        "source_observations",
        "canonical_events",
        "state_intervals",
        "wide_result_snapshots",
        "reconciliation_results",
        "validation_results",
    )
    with _connect(database) as connection:
        return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}


def test_initialization_is_versioned_transactional_and_reopenable(tmp_path: Path) -> None:
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    initialize_database(database)

    with _connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        migration = connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations"
        ).fetchone()
        assert tuple(migration[:2]) == (1, "initial_timeline_store")
        assert migration["checksum_sha256"] == analytical_store._migration_checksum()
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_complete_import_export_raw_payload_and_idempotency(tmp_path: Path) -> None:
    run_dir = _build_run(tmp_path)
    source = tmp_path / "sources" / "001_01-001" / "local.db"
    source_before = (source.stat().st_size, source.stat().st_mtime_ns)
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)

    first = import_run(database, run_dir, parser_version=_parser())
    counts = _table_counts(database)
    second = import_run(database, run_dir, parser_version=_parser())

    assert first.status == "IMPORTED"
    assert first.run_cases == first.successful_cases == 1
    assert first.events_inserted == first.intervals_inserted == 1
    assert first.reconciliation_rows == 5
    assert second.status == "NOOP_ALREADY_IMPORTED"
    assert _table_counts(database) == counts
    assert (source.stat().st_size, source.stat().st_mtime_ns) == source_before
    with _connect(database) as connection:
        raw = connection.execute("SELECT raw_payload_json FROM canonical_events").fetchone()[0]
        assert json.loads(raw) == {"PatientId": "synthetic", "nested": {"value": 7}}
        interval = connection.execute(
            "SELECT start_sec, duration_sec, quality_flags_json FROM state_intervals"
        ).fetchone()
        assert interval["start_sec"] == -5.0
        assert interval["duration_sec"] == 65.05
        assert json.loads(interval["quality_flags_json"]) == [
            "negative_rebased_start",
            "negative_rebased_start_expected_pre_anchor",
        ]

    output = tmp_path / "exports" / "wide.csv"
    result = export_wide(database, "run-001", output)
    with output.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == WIDE_HEADERS
    assert result["row_count"] == 1
    assert rows[0]["starttime"] == "10:00:00 AM"
    assert rows[0]["endtime"] == "10:01:05 AM"
    assert rows[0]["TULSA QA"] == "1.1"
    assert list_runs(database)[0]["published_case_count"] == 1


def test_partial_run_retains_failed_case_and_exports_only_successes(tmp_path: Path) -> None:
    run_dir = _build_run(
        tmp_path,
        successful_ids=("001_01-001",),
        failed_ids=("001_01-002",),
    )
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    summary = import_run(database, run_dir, parser_version=_parser())

    assert (summary.run_cases, summary.successful_cases, summary.failed_cases) == (2, 1, 1)
    with _connect(database) as connection:
        failed = connection.execute(
            "SELECT processing_status, final_row_included, failure_reason "
            "FROM run_cases WHERE final_row_included = 0"
        ).fetchone()
        assert tuple(failed) == ("FAIL", 0, "missing_database")
    output = tmp_path / "exports" / "partial.csv"
    assert export_wide(database, "run-001", output)["row_count"] == 1


def test_history_reuses_or_versions_by_source_parser_and_configuration(tmp_path: Path) -> None:
    source = tmp_path / "sources" / "shared" / "local.db"
    paths = {"001_01-001": source}
    run_one = _build_run(tmp_path, run_id="run-001", source_paths=paths)
    run_two = _build_run(tmp_path, run_id="run-002", source_paths=paths)
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    assert import_run(database, run_one, parser_version=_parser("a")).case_analyses_inserted == 1
    assert import_run(database, run_two, parser_version=_parser("a")).case_analyses_reused == 1

    source.write_bytes(b"SQLite format 3\0changed source")
    run_three = _build_run(tmp_path, run_id="run-003", source_paths=paths)
    assert import_run(database, run_three, parser_version=_parser("a")).case_analyses_inserted == 1

    run_four = _build_run(tmp_path, run_id="run-004", source_paths=paths)
    assert import_run(database, run_four, parser_version=_parser("b")).case_analyses_inserted == 1

    run_five = _build_run(
        tmp_path,
        run_id="run-005",
        source_paths=paths,
        year_selection="2026",
    )
    assert import_run(database, run_five, parser_version=_parser("b")).case_analyses_inserted == 1
    with _connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_artifacts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM parser_versions").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM case_analyses").fetchone()[0] == 4


def test_same_run_id_with_changed_content_is_a_hard_conflict(tmp_path: Path) -> None:
    run_dir = _build_run(tmp_path)
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    import_run(database, run_dir, parser_version=_parser())
    manifest_path = run_dir / "Backend" / "manifests" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["warnings"] = ["changed after import"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(AnalyticalStoreError, match="different content"):
        import_run(database, run_dir, parser_version=_parser())
    assert _table_counts(database)["analysis_runs"] == 1


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda run: (run / "Backend" / "events" / "state_labeled" / "001_01-001_state_labeled_events.csv").unlink(),
            "Missing 001_01-001 state-labeled event artifact",
        ),
        (
            lambda run: _replace_csv_value(
                run / "Backend" / "intervals" / "state" / "001_01-001_state_intervals.csv",
                INTERVAL_FIELDS,
                "duration_sec",
                "-1.0",
            ),
            "Negative duration",
        ),
        (
            lambda run: _replace_csv_value(
                run / "Backend" / "events" / "state_labeled" / "001_01-001_state_labeled_events.csv",
                EVENT_FIELDS,
                "case_id",
                "001_01-999",
            ),
            "Canonical event identity mismatch",
        ),
        (
            lambda run: _replace_csv_value(
                run / "Report" / "test_001_timeline_analysis.csv",
                WIDE_HEADERS,
                "TULSA QA",
                "9.9",
            ),
            "Wide interval-derived value mismatch",
        ),
    ],
)
def test_invalid_runs_fail_before_transaction(
    tmp_path: Path,
    mutate: Callable[[Path], None],
    match: str,
) -> None:
    run_dir = _build_run(tmp_path)
    mutate(run_dir)
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    before = _table_counts(database)
    with pytest.raises(AnalyticalStoreError, match=match):
        import_run(database, run_dir, parser_version=_parser())
    assert _table_counts(database) == before


def _replace_csv_value(path: Path, fields: tuple[str, ...], key: str, value: str) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0][key] = value
    _write_csv(path, fields, rows)


def test_transaction_rolls_back_after_mid_import_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _build_run(tmp_path)
    prepared = prepare_run_import(run_dir, parser_version=_parser())
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    before = _table_counts(database)

    def fail_intervals(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("injected interval failure")

    monkeypatch.setattr(analytical_store, "_insert_intervals", fail_intervals)
    with pytest.raises(RuntimeError, match="injected interval failure"):
        import_prepared_run(database, prepared)
    assert _table_counts(database) == before


def test_database_destination_rejects_repository_and_run_paths(tmp_path: Path) -> None:
    repository_database = analytical_store.REPO_ROOT / "timeline.sqlite"
    with pytest.raises(AnalyticalStoreError, match="outside the repository"):
        validate_database_path(repository_database)

    run_dir = _build_run(tmp_path)
    database = run_dir / "Backend" / "timeline.sqlite"
    with pytest.raises(AnalyticalStoreError, match="outside the imported run"):
        import_run(database, run_dir, parser_version=_parser())


def test_deterministic_reuse_rejects_conflicting_case_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "sources" / "shared" / "local.db"
    paths = {"001_01-001": source}
    run_one = _build_run(tmp_path, run_id="run-001", source_paths=paths)
    run_two = _build_run(tmp_path, run_id="run-002", source_paths=paths)
    _replace_csv_value(
        run_two / "Backend" / "events" / "state_labeled" / "001_01-001_state_labeled_events.csv",
        EVENT_FIELDS,
        "source_detail",
        "conflicting_artifact",
    )
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    import_run(database, run_one, parser_version=_parser())
    before = _table_counts(database)

    with pytest.raises(AnalyticalStoreError, match="Deterministic case-analysis conflict"):
        import_run(database, run_two, parser_version=_parser())
    assert _table_counts(database) == before


def test_parser_dataclass_can_express_a_historical_version() -> None:
    original = _parser("one")
    changed = replace(original, source_fingerprint_sha256=_parser("two").source_fingerprint_sha256)
    assert changed.source_fingerprint_sha256 != original.source_fingerprint_sha256
