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
    analysis_configuration,
    compare_runs,
    export_long,
    export_wide,
    import_prepared_run,
    import_run,
    initialize_database,
    list_runs,
    prepare_run_import,
    summarize_runs,
    validate_database_path,
)
from site_timing_analysis.models import DatabaseSourceRecord
from site_timing_analysis.first_slice_cli import run_first_slice
from site_timing_analysis.timeline_cache import TimelineCacheReader
from site_timing_analysis import store_relocation
from site_timing_analysis import store_upgrade
from site_timing_analysis.store_relocation import (
    capture_database_snapshot,
    logical_database_hash,
    relocate_store,
    verify_relocated_store,
)
from testing.synthetic_test_db import create_synthetic_test_db


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


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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
        "case_analysis_cache_entries",
        "case_analysis_inputs",
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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        migrations = connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [tuple(row[:2]) for row in migrations] == [
            (1, "initial_timeline_store"),
            (2, "exact_case_cache_inputs"),
        ]
        assert [row["checksum_sha256"] for row in migrations] == [
            analytical_store._migration_checksum(1),
            analytical_store._migration_checksum(2),
        ]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        connection.execute(
            "UPDATE schema_migrations SET checksum_sha256 = 'INVALID' WHERE version = 2"
        )
    with pytest.raises(AnalyticalStoreError, match="checksum"):
        initialize_database(database)
    assert not Path(str(database) + "-wal").exists()
    assert not Path(str(database) + "-shm").exists()


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
        reconciliation_details = connection.execute(
            "SELECT details_json FROM reconciliation_results LIMIT 1"
        ).fetchone()[0]
        assert json.loads(reconciliation_details)["detailed_intervals_are_authoritative"] is True

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


def test_import_accepts_empty_reconciliation_without_comparator(tmp_path: Path) -> None:
    run_dir = _build_run(tmp_path, run_id="no-comparator-run")
    _write_csv(
        run_dir / "Backend" / "reports" / "phase_reconciliation.csv",
        (
            "case_id",
            "phase",
            "detailed_minutes_unrounded",
            "rollup_minutes",
            "difference_minutes",
            "status",
            "failure_type",
        ),
        [],
    )
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)

    result = import_run(database, run_dir, parser_version=_parser())

    assert result.status == "IMPORTED"
    assert result.reconciliation_rows == 0
    with _connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_results"
        ).fetchone()[0] == 0


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
                run / "Backend" / "events" / "state_labeled" / "001_01-001_state_labeled_events.csv",
                EVENT_FIELDS,
                "timestamp",
                "2025-12-31T23:59:59",
            ),
            "Canonical event outside valid event window",
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
        (
            lambda run: _replace_csv_value(
                run / "Backend" / "reports" / "phase_reconciliation.csv",
                (
                    "case_id",
                    "phase",
                    "detailed_minutes_unrounded",
                    "rollup_minutes",
                    "difference_minutes",
                    "status",
                    "failure_type",
                ),
                "detailed_minutes_unrounded",
                "999.0",
            ),
            "Detailed reconciliation total differs from intervals",
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


def _prepare_source_store(tmp_path: Path) -> tuple[Path, Path, str]:
    run_id = "run-001"
    run_dir = _build_run(tmp_path / "runs", run_id=run_id)
    source_database = tmp_path / "old_store" / "timeline_analysis.sqlite"
    source_export = tmp_path / "old_store" / "exports" / "test_001_timeline_analysis.csv"
    initialize_database(source_database)
    import_run(source_database, run_dir, parser_version=_parser())
    export_wide(source_database, run_id, source_export)
    return source_database, source_export, run_id


def test_logical_hash_is_order_independent_and_type_complete(tmp_path: Path) -> None:
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    for path, rows in (
        (first, [(2, None, b"\x00\xff", 1.25), (1, "text", b"abc", -0.0)]),
        (second, [(1, "text", b"abc", -0.0), (2, None, b"\x00\xff", 1.25)]),
    ):
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE typed_values (id INTEGER PRIMARY KEY, text_value TEXT, "
            "blob_value BLOB, real_value REAL)"
        )
        connection.executemany("INSERT INTO typed_values VALUES (?, ?, ?, ?)", rows)
        connection.commit()
        connection.close()
    with sqlite3.connect(first) as first_connection, sqlite3.connect(second) as second_connection:
        assert logical_database_hash(first_connection) == logical_database_hash(second_connection)
        second_connection.execute(
            "UPDATE typed_values SET blob_value = ? WHERE id = 2", (b"changed",)
        )
        second_connection.commit()
        assert logical_database_hash(first_connection) != logical_database_hash(second_connection)


def test_relocation_is_non_overwriting_idempotent_and_cleanup_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_database, source_export, run_id = _prepare_source_store(tmp_path)
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination_database = destination_root / "timeline_analysis.sqlite"
    destination_export = destination_root / "exports" / "test_001_timeline_analysis.csv"
    monkeypatch.setattr(store_relocation, "onedrive_process_running", lambda: False)

    first = relocate_store(
        source_database=source_database,
        destination_database=destination_database,
        source_export=source_export,
        destination_export=destination_export,
        run_id=run_id,
        confirm_onedrive_stopped=True,
        cleanup_source=False,
        pin_destination=False,
    )
    assert first.status == "RELOCATED"
    assert source_database.is_file()
    assert destination_database.is_file()
    assert destination_export.read_bytes() == source_export.read_bytes()
    assert capture_database_snapshot(destination_database).journal_mode == "delete"
    assert not Path(str(destination_database) + "-wal").exists()
    assert not Path(str(destination_database) + "-shm").exists()

    second = relocate_store(
        source_database=source_database,
        destination_database=destination_database,
        source_export=source_export,
        destination_export=destination_export,
        run_id=run_id,
        confirm_onedrive_stopped=True,
        cleanup_source=True,
        pin_destination=False,
    )
    assert second.status == "VERIFIED_EXISTING_DESTINATION"
    assert not source_database.exists()
    assert not source_export.exists()
    assert destination_database.is_file()
    assert destination_export.is_file()
    verified = verify_relocated_store(
        database=destination_database,
        output=destination_export,
        run_id=run_id,
        require_pinned=False,
    )
    assert verified["status"] == "VERIFIED"
    assert set(verified["local_states"]) == {
        "database_directory",
        "database",
        "export_directory",
        "export",
    }
    assert all(
        state["fully_local"] for state in verified["local_states"].values()
    )


def test_relocation_rejects_unexpected_destination_without_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_database, source_export, run_id = _prepare_source_store(tmp_path)
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination_database = destination_root / "timeline_analysis.sqlite"
    initialize_database(destination_database)
    monkeypatch.setattr(store_relocation, "onedrive_process_running", lambda: False)

    with pytest.raises(AnalyticalStoreError, match="not the intended migration output"):
        relocate_store(
            source_database=source_database,
            destination_database=destination_database,
            source_export=source_export,
            destination_export=destination_root / "exports" / "result.csv",
            run_id=run_id,
            confirm_onedrive_stopped=True,
            cleanup_source=True,
            pin_destination=False,
        )
    assert source_database.is_file()
    assert source_export.is_file()


def test_export_conflict_does_not_publish_database_or_clean_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_database, source_export, run_id = _prepare_source_store(tmp_path)
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination_database = destination_root / "timeline_analysis.sqlite"
    destination_export = destination_root / "exports" / "result.csv"
    destination_export.parent.mkdir()
    destination_export.write_text("unrelated", encoding="utf-8")
    monkeypatch.setattr(store_relocation, "onedrive_process_running", lambda: False)

    with pytest.raises(AnalyticalStoreError, match="Wide export schema mismatch"):
        relocate_store(
            source_database=source_database,
            destination_database=destination_database,
            source_export=source_export,
            destination_export=destination_export,
            run_id=run_id,
            confirm_onedrive_stopped=True,
            cleanup_source=True,
            pin_destination=False,
        )
    assert not destination_database.exists()
    assert source_database.is_file()
    assert source_export.is_file()
    assert destination_export.read_text(encoding="utf-8") == "unrelated"


def test_relocation_requires_stopped_onedrive_and_rejects_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_database, source_export, run_id = _prepare_source_store(tmp_path)
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination_database = destination_root / "timeline_analysis.sqlite"
    destination_sidecar = Path(str(destination_database) + "-wal")
    destination_sidecar.write_bytes(b"unexpected")
    monkeypatch.setattr(store_relocation, "onedrive_process_running", lambda: True)

    with pytest.raises(AnalyticalStoreError, match="OneDrive.exe is still running"):
        relocate_store(
            source_database=source_database,
            destination_database=destination_database,
            source_export=source_export,
            destination_export=destination_root / "exports" / "result.csv",
            run_id=run_id,
            confirm_onedrive_stopped=True,
            cleanup_source=False,
            pin_destination=False,
        )
    monkeypatch.setattr(store_relocation, "onedrive_process_running", lambda: False)
    with pytest.raises(AnalyticalStoreError, match="destination sidecar"):
        relocate_store(
            source_database=source_database,
            destination_database=destination_database,
            source_export=source_export,
            destination_export=destination_root / "exports" / "result.csv",
            run_id=run_id,
            confirm_onedrive_stopped=True,
            cleanup_source=False,
            pin_destination=False,
        )
    assert source_database.is_file()


def _cache_source(run_dir: Path, case_id: str = "001_01-001") -> DatabaseSourceRecord:
    source_path = run_dir.parent / "sources" / case_id / "local.db"
    return DatabaseSourceRecord(
        case_id=case_id,
        case_path=source_path.parent,
        source_type="unzipped",
        source_path=source_path,
        selected_zip_member=None,
        resolution_rule="synthetic_test",
    )


def test_schema_v2_copy_up_preserves_v1_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "store" / "timeline.sqlite"
    database.parent.mkdir()
    connection = analytical_store._open_database(database)
    try:
        analytical_store._apply_schema_migration(connection, 1)
        connection.execute(
            "INSERT INTO sites (site_code, first_seen_at_utc) VALUES (?, ?)",
            ("TEST_001", "2026-08-11T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(store_upgrade, "onedrive_process_running", lambda: False)

    result = store_upgrade.upgrade_database_copy(
        database,
        confirm_onedrive_stopped=True,
        cleanup_backup=True,
        require_pinned=False,
    )

    assert result["status"] == "UPGRADED"
    assert result["before"]["legacy_content_sha256"] == result["after"][
        "legacy_content_sha256"
    ]
    assert result["backup_removed"] is True
    with _connect(database) as upgraded:
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 2
        assert upgraded.execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 1
        assert upgraded.execute(
            "SELECT COUNT(*) FROM case_analysis_cache_entries"
        ).fetchone()[0] == 0
    assert not Path(str(database) + "-wal").exists()
    assert not Path(str(database) + "-shm").exists()


def test_exact_cache_hit_and_all_invalidation_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _build_run(tmp_path / "runs", run_id="cache-run")
    database = tmp_path / "store" / "timeline.sqlite"
    parser = _parser("cache-parser")
    initialize_database(database)
    prepared = prepare_run_import(run_dir, parser_version=parser)
    import_prepared_run(database, prepared)
    source = _cache_source(run_dir)

    reader = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256=prepared.configuration_fingerprint_sha256,
        parser_version=parser,
    )
    hit = reader.lookup(case_id=source.case_id, source=source, timing_log_path=None)
    assert hit.status == "HIT", hit.reason
    assert hit.artifacts is not None
    assert len(hit.artifacts.state_labeled_events) == 1
    assert len(hit.artifacts.state_intervals) == 1
    assert len(hit.artifacts.normalized_events) == 1

    timing_log = tmp_path / "timing.csv"
    timing_log.write_text("label,time\nQA,10:00\n", encoding="utf-8")
    assert reader.lookup(
        case_id=source.case_id, source=source, timing_log_path=timing_log
    ).status == "MISS"

    parser_miss = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256=prepared.configuration_fingerprint_sha256,
        parser_version=_parser("changed-parser"),
    )
    assert parser_miss.lookup(
        case_id=source.case_id, source=source, timing_log_path=None
    ).status == "MISS"

    configuration_miss = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256="F" * 64,
        parser_version=parser,
    )
    assert configuration_miss.lookup(
        case_id=source.case_id, source=source, timing_log_path=None
    ).status == "MISS"

    import site_timing_analysis.timeline_cache as timeline_cache

    monkeypatch.setattr(timeline_cache, "CACHE_CONTRACT_VERSION", 2)
    contract_miss = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256=prepared.configuration_fingerprint_sha256,
        parser_version=parser,
    )
    assert contract_miss.lookup(
        case_id=source.case_id, source=source, timing_log_path=None
    ).status == "MISS"

    source.source_path.write_bytes(source.source_path.read_bytes() + b"changed")
    monkeypatch.setattr(timeline_cache, "CACHE_CONTRACT_VERSION", 1)
    assert reader.lookup(
        case_id=source.case_id, source=source, timing_log_path=None
    ).status == "MISS"


def test_invalid_cache_entry_falls_back_as_typed_invalid(tmp_path: Path) -> None:
    run_dir = _build_run(tmp_path / "runs", run_id="invalid-cache-run")
    database = tmp_path / "store" / "timeline.sqlite"
    parser = _parser("cache-parser")
    initialize_database(database)
    prepared = prepare_run_import(run_dir, parser_version=parser)
    import_prepared_run(database, prepared)
    reader = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256=prepared.configuration_fingerprint_sha256,
        parser_version=parser,
    )
    with _connect(database) as connection:
        connection.execute(
            "UPDATE canonical_events SET raw_payload_json = 'not-json' WHERE event_ordinal = 1"
        )
    result = reader.lookup(
        case_id="001_01-001", source=_cache_source(run_dir), timing_log_path=None
    )
    assert result.status == "INVALID"
    assert result.reason.startswith("cache_entry_invalid:")


def test_cache_materialization_restores_normalized_source_order() -> None:
    import site_timing_analysis.timeline_cache as timeline_cache

    rows = []
    for row_number, timestamp in ((8, "2026-01-01T08:00:00"), (2, "2026-01-01T08:01:00")):
        row = dict.fromkeys(EVENT_FIELDS, "")
        row.update(
            {
                "case_id": "001_01-001",
                "timestamp": timestamp,
                "event_type": "SyntheticEvent",
                "source": "auditlog",
                "is_synthetic": "False",
                "row_number": str(row_number),
                "raw_payload_json": "{}",
            }
        )
        rows.append(row)

    normalized, enriched, labeled = timeline_cache._materialize_event_models(rows)

    assert [event.row_number for event in normalized] == [2, 8]
    assert [event.row_number for event in enriched] == [8, 2]
    assert [event.row_number for event in labeled] == [8, 2]


def test_first_slice_materializes_exact_cache_hit_without_opening_source_database(
    tmp_path: Path,
) -> None:
    case_id = "001_01-001"
    site_root = tmp_path / "site"
    source_path = site_root / case_id / "local.db"
    run_dir = _build_run(
        tmp_path / "seed_runs",
        run_id="seed-run",
        source_paths={case_id: source_path},
    )
    database = tmp_path / "store" / "timeline.sqlite"
    parser = _parser("cache-parser")
    initialize_database(database)
    prepared = prepare_run_import(run_dir, parser_version=parser)
    import_prepared_run(database, prepared)
    _, configuration_fingerprint = analysis_configuration(
        year_selection="All", canonical_prefix="001_"
    )
    reader = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256=configuration_fingerprint,
        parser_version=parser,
    )
    selection = tmp_path / "selected.txt"
    selection.write_text(case_id + "\n", encoding="utf-8")
    output = tmp_path / "cached_run"

    manifest = run_first_slice(
        [
            "--site",
            "TEST_001",
            "--years",
            "All",
            "--root",
            str(tmp_path),
            "--site-path",
            str(site_root),
            "--output",
            str(output),
            "--case-id-file",
            str(selection),
        ],
        cache_reader=reader,
    )

    assert manifest.cases_processed == 1
    assert manifest.cases_failed == 0
    assert manifest.case_results[0]["cache_status"] == "HIT"
    assert reader.summary()["counts"] == {"HIT": 1, "MISS": 0, "INVALID": 0}
    assert (output / "events" / "state_labeled" / f"{case_id}_state_labeled_events.csv").is_file()
    assert (output / "intervals" / "state" / f"{case_id}_state_intervals.csv").is_file()


def test_first_slice_parses_source_after_invalid_cache_entry(tmp_path: Path) -> None:
    case_id = "001_01-001"
    site_root = tmp_path / "site"
    source_path = create_synthetic_test_db(site_root / case_id / "local.db")
    run_dir = _build_run(
        tmp_path / "seed_runs",
        run_id="invalid-fallback-seed",
        source_paths={case_id: source_path},
    )
    database = tmp_path / "store" / "timeline.sqlite"
    parser = _parser("cache-parser")
    initialize_database(database)
    prepared = prepare_run_import(run_dir, parser_version=parser)
    import_prepared_run(database, prepared)
    with _connect(database) as connection:
        connection.execute(
            "UPDATE canonical_events SET raw_payload_json = 'not-json' WHERE event_ordinal = 1"
        )

    _, configuration_fingerprint = analysis_configuration(
        year_selection="All", canonical_prefix="001_"
    )
    reader = TimelineCacheReader(
        database=database,
        site_code="TEST_001",
        configuration_fingerprint_sha256=configuration_fingerprint,
        parser_version=parser,
    )
    selection = tmp_path / "selected.txt"
    selection.write_text(case_id + "\n", encoding="utf-8")

    manifest = run_first_slice(
        [
            "--site",
            "TEST_001",
            "--years",
            "All",
            "--root",
            str(tmp_path),
            "--site-path",
            str(site_root),
            "--output",
            str(tmp_path / "fallback_run"),
            "--case-id-file",
            str(selection),
        ],
        cache_reader=reader,
    )

    assert manifest.cases_processed == 1
    assert manifest.cases_failed == 0
    assert manifest.case_results[0]["cache_status"] == "INVALID"
    assert manifest.case_results[0]["raw_event_count"] > 0
    assert reader.summary()["counts"] == {"HIT": 0, "MISS": 0, "INVALID": 1}


def test_sql_native_long_compare_and_summary_exports(tmp_path: Path) -> None:
    run_dir = _build_run(tmp_path / "runs", run_id="report-run")
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    import_run(database, run_dir, parser_version=_parser())
    output_root = tmp_path / "external_reports"

    long_result = export_long(database, "report-run", output_root / "long.csv")
    compare_result = compare_runs(
        database,
        "report-run",
        "report-run",
        output_root / "compare.csv",
    )
    summary_result = summarize_runs(
        database,
        ["report-run"],
        output_root / "summary.csv",
    )

    assert long_result["row_count"] == len(REQUESTED_STATES)
    assert compare_result["row_count"] == len(REQUESTED_STATES)
    assert summary_result["row_count"] == len(REQUESTED_STATES)
    long_rows = _read_csv_rows(output_root / "long.csv")
    assert [row["state"] for row in long_rows] == list(REQUESTED_STATES)
    assert all("T" in row["start_timestamp_iso"] for row in long_rows)
    compare_rows = _read_csv_rows(output_root / "compare.csv")
    assert {row["status"] for row in compare_rows} == {"MATCHED"}
    assert {float(row["difference_minutes_unrounded"]) for row in compare_rows} == {0.0}
    summary_rows = _read_csv_rows(output_root / "summary.csv")
    assert {int(row["case_count"]) for row in summary_rows} == {1}


def test_compare_runs_reports_cases_missing_from_each_side(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    baseline = _build_run(
        runs_root,
        run_id="baseline",
        successful_ids=("001_01-001",),
    )
    comparison = _build_run(
        runs_root,
        run_id="comparison",
        successful_ids=("001_01-002",),
    )
    database = tmp_path / "store" / "timeline.sqlite"
    initialize_database(database)
    import_run(database, baseline, parser_version=_parser())
    import_run(database, comparison, parser_version=_parser())
    output = tmp_path / "reports" / "missing.csv"

    result = compare_runs(database, "baseline", "comparison", output)
    rows = _read_csv_rows(output)

    assert result["row_count"] == len(REQUESTED_STATES) * 2
    assert {row["status"] for row in rows} == {
        "MISSING_BASELINE",
        "MISSING_COMPARISON",
    }
