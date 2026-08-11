# Project: Site Timing Analysis
# File: testing/tests/test_profiling.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-10
# Purpose: Verifies nested profiler reconciliation and unique artifact accounting.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import json
from pathlib import Path

from site_timing_analysis.profiling import PerformanceProfiler


def test_nested_stage_timings_reconcile_without_double_counting(tmp_path: Path) -> None:
    profiler = PerformanceProfiler(site_code="TEST_001", output_dir=tmp_path)

    with profiler.stage("run orchestration outside named stages"):
        with profiler.stage("event normalization", case_id="001_01-001"):
            sum(index * index for index in range(10_000))
        with profiler.stage("validation and reconciliation", case_id="001_01-001"):
            sum(range(10_000))
    profiler.finalize()

    payload = profiler.build_payload()
    assert payload["timing_model"] == "nested_exclusive"
    assert payload["timing_reconciliation_status"] == "PASS"
    assert abs(payload["unaccounted_runtime_seconds"]) <= payload["reconciliation_tolerance_seconds"]
    orchestration = next(
        row
        for row in payload["stage_totals_ranked"]
        if row["stage"] == "run orchestration outside named stages"
    )
    assert abs(
        payload["instrumented_stage_total_seconds"] - orchestration["inclusive_wall_seconds"]
    ) < 1e-6


def test_artifact_metrics_assign_each_file_to_one_scope(tmp_path: Path) -> None:
    case_path = tmp_path / "case.csv"
    shared_path = tmp_path / "shared.json"
    case_path.write_bytes(b"case")
    shared_path.write_bytes(b"shared")
    profiler = PerformanceProfiler(site_code="TEST_001", output_dir=tmp_path)

    profiler.record_output_paths("001_01-001", [case_path, case_path])
    profiler.record_global_output_paths([shared_path, shared_path, case_path])
    profiler.finalize()

    payload = profiler.build_payload()
    case = payload["case_totals_ranked"][0]
    metrics = payload["artifact_metrics"]
    assert case["output_file_count"] == 1
    assert case["output_bytes_written"] == 4
    assert metrics["global_output_file_count"] == 1
    assert metrics["global_output_bytes_written"] == 6
    assert metrics["total_unique_output_file_count"] == 2
    assert metrics["total_unique_output_bytes_written"] == 10


def test_written_report_artifact_bytes_reconcile_after_self_serialization(tmp_path: Path) -> None:
    profiler = PerformanceProfiler(site_code="TEST_001", output_dir=tmp_path)
    with profiler.stage("run orchestration outside named stages"):
        pass

    summary_path, _ = profiler.write_reports(tmp_path / "reports")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    case_paths = [
        path
        for case in payload["case_totals_ranked"]
        for path in case["output_paths"]
    ]
    global_paths = payload["artifact_metrics"]["global_output_paths"]
    unique_paths = sorted(set(case_paths + global_paths))
    actual_bytes = sum(Path(path).stat().st_size for path in unique_paths)

    assert actual_bytes == payload["artifact_metrics"]["total_unique_output_bytes_written"]
