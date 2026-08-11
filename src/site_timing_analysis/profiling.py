# Project: Site Timing Analysis
# File: src/site_timing_analysis/profiling.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-10
# Purpose: Provides opt-in wall-clock and CPU-time profiling for pipeline runs.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import csv
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
from typing import Any


PROFILE_STAGES = (
    "process startup and CLI parsing",
    "run orchestration outside named stages",
    "preflight and manifest construction",
    "global setup and teardown",
    "directory discovery",
    "case selection",
    "database candidate resolution",
    "staging or copying",
    "database connection and ingestion",
    "per-case orchestration outside named stages",
    "event normalization",
    "event enrichment",
    "state labeling",
    "interval construction",
    "detailed aggregation",
    "all artifact writes",
    "CSV export",
    "global plot orchestration",
    "plot generation",
    "final output discovery",
    "validation and reconciliation",
    "report assembly and serialization",
    "report generation",
    "shutdown",
)

STAGE_WORK_CLASS = {
    "process startup and CLI parsing": "CPU-bound import and argument parsing",
    "run orchestration outside named stages": "mixed orchestration overhead",
    "preflight and manifest construction": "mixed CPU + subprocess + filesystem I/O",
    "global setup and teardown": "mixed orchestration + filesystem I/O",
    "directory discovery": "filesystem I/O",
    "case selection": "CPU-bound filtering",
    "database candidate resolution": "filesystem I/O + database probing",
    "staging or copying": "filesystem I/O",
    "database connection and ingestion": "database I/O",
    "per-case orchestration outside named stages": "mixed per-case orchestration overhead",
    "event normalization": "CPU-bound transformation",
    "event enrichment": "mixed CPU + filesystem I/O",
    "state labeling": "CPU-bound transformation",
    "interval construction": "CPU-bound transformation",
    "detailed aggregation": "CPU-bound transformation + filesystem I/O",
    "all artifact writes": "filesystem I/O",
    "CSV export": "CPU-bound serialization + filesystem I/O",
    "global plot orchestration": "mixed CPU + filesystem I/O",
    "plot generation": "CPU-bound rendering + filesystem I/O",
    "final output discovery": "filesystem I/O",
    "validation and reconciliation": "CPU-bound validation + filesystem I/O",
    "report assembly and serialization": "CPU-bound formatting and serialization",
    "report generation": "CPU-bound formatting + filesystem I/O",
    "shutdown": "mixed teardown overhead",
}


def _empty_timing() -> dict[str, float | int]:
    return {
        "wall_seconds": 0.0,
        "process_cpu_seconds": 0.0,
        "non_cpu_wall_seconds": 0.0,
        "inclusive_wall_seconds": 0.0,
        "inclusive_process_cpu_seconds": 0.0,
        "inclusive_non_cpu_wall_seconds": 0.0,
        "invocation_count": 0,
    }


class _StageTimer(AbstractContextManager[None]):
    def __init__(self, profiler: "PerformanceProfiler", stage: str, case_id: str | None) -> None:
        self.profiler = profiler
        self.stage = stage
        self.case_id = case_id
        self.wall_started = 0.0
        self.cpu_started = 0.0
        self.child_wall_seconds = 0.0
        self.child_cpu_seconds = 0.0

    def __enter__(self) -> None:
        self.wall_started = time.perf_counter()
        self.cpu_started = time.process_time()
        self.profiler._timer_stack.append(self)
        return None

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        inclusive_wall = max(0.0, time.perf_counter() - self.wall_started)
        inclusive_cpu = max(0.0, time.process_time() - self.cpu_started)
        if not self.profiler._timer_stack or self.profiler._timer_stack[-1] is not self:
            raise RuntimeError(f"Profiling stage stack is unbalanced at {self.stage!r}.")
        self.profiler._timer_stack.pop()
        if self.profiler._timer_stack:
            parent = self.profiler._timer_stack[-1]
            parent.child_wall_seconds += inclusive_wall
            parent.child_cpu_seconds += inclusive_cpu
        self.profiler.record_stage(
            self.stage,
            wall_seconds=max(0.0, inclusive_wall - self.child_wall_seconds),
            process_cpu_seconds=max(0.0, inclusive_cpu - self.child_cpu_seconds),
            inclusive_wall_seconds=inclusive_wall,
            inclusive_process_cpu_seconds=inclusive_cpu,
            case_id=self.case_id,
        )
        return False


class PerformanceProfiler:
    """Collect opt-in, nested timings and uniquely owned output metrics.

    ``wall_seconds`` is exclusive time and therefore additive across stages.
    ``inclusive_wall_seconds`` retains the complete duration of each span for
    drill-down. Files are assigned to exactly one case or to the global scope so
    shared artifacts and their bytes cannot be counted more than once.
    """

    def __init__(
        self,
        *,
        site_code: str,
        output_dir: Path,
        wall_started: float | None = None,
        cpu_started: float | None = None,
    ) -> None:
        self.site_code = site_code
        self.output_dir = output_dir
        self.started_at = datetime.now(timezone.utc)
        self.wall_started = time.perf_counter() if wall_started is None else wall_started
        self.cpu_started = time.process_time() if cpu_started is None else cpu_started
        self.wall_finished: float | None = None
        self.cpu_finished: float | None = None
        self.stage_totals: dict[str, dict[str, float | int]] = {
            stage: _empty_timing() for stage in PROFILE_STAGES
        }
        self.cases: dict[str, dict[str, Any]] = {}
        self._timer_stack: list[_StageTimer] = []
        self._artifact_owners: dict[str, str] = {}
        self._global_output_paths: list[str] = []

    def stage(self, stage: str, *, case_id: str | None = None) -> _StageTimer:
        if stage not in PROFILE_STAGES:
            raise ValueError(f"Unknown profiling stage: {stage}")
        if case_id is not None:
            self._case(case_id)
        return _StageTimer(self, stage, case_id)

    def _case(self, case_id: str) -> dict[str, Any]:
        return self.cases.setdefault(
            case_id,
            {
                "case_id": case_id,
                "stages": {stage: _empty_timing() for stage in PROFILE_STAGES},
                "database_rows_read": 0,
                "normalized_events": 0,
                "labeled_events": 0,
                "intervals": 0,
                "output_paths": [],
                "warnings": [],
                "failures": [],
            },
        )

    def record_stage(
        self,
        stage: str,
        *,
        wall_seconds: float,
        process_cpu_seconds: float,
        inclusive_wall_seconds: float | None = None,
        inclusive_process_cpu_seconds: float | None = None,
        case_id: str | None,
    ) -> None:
        """Record one stage span using exclusive and inclusive durations."""
        exclusive_wall = max(0.0, wall_seconds)
        exclusive_cpu = max(0.0, process_cpu_seconds)
        inclusive_wall = max(exclusive_wall, inclusive_wall_seconds or exclusive_wall)
        inclusive_cpu = max(exclusive_cpu, inclusive_process_cpu_seconds or exclusive_cpu)
        timing: dict[str, float | int] = {
            "wall_seconds": exclusive_wall,
            "process_cpu_seconds": exclusive_cpu,
            "non_cpu_wall_seconds": max(0.0, exclusive_wall - exclusive_cpu),
            "inclusive_wall_seconds": inclusive_wall,
            "inclusive_process_cpu_seconds": inclusive_cpu,
            "inclusive_non_cpu_wall_seconds": max(0.0, inclusive_wall - inclusive_cpu),
            "invocation_count": 1,
        }
        self._accumulate_timing(self.stage_totals[stage], timing)
        if case_id is not None:
            self._accumulate_timing(self._case(case_id)["stages"][stage], timing)

    def record_external_stage(
        self,
        stage: str,
        *,
        wall_seconds: float,
        process_cpu_seconds: float,
    ) -> None:
        """Record a completed non-nested span, such as startup before profiler creation."""
        if stage not in PROFILE_STAGES:
            raise ValueError(f"Unknown profiling stage: {stage}")
        self.record_stage(
            stage,
            wall_seconds=wall_seconds,
            process_cpu_seconds=process_cpu_seconds,
            case_id=None,
        )

    @staticmethod
    def _accumulate_timing(target: dict[str, float | int], timing: dict[str, float | int]) -> None:
        for key, value in timing.items():
            target[key] += value

    def set_case_metrics(
        self,
        case_id: str,
        *,
        database_rows_read: int | None = None,
        normalized_events: int | None = None,
        labeled_events: int | None = None,
        intervals: int | None = None,
    ) -> None:
        case = self._case(case_id)
        for key, value in {
            "database_rows_read": database_rows_read,
            "normalized_events": normalized_events,
            "labeled_events": labeled_events,
            "intervals": intervals,
        }.items():
            if value is not None:
                case[key] = int(value)

    def add_case_warnings(self, case_id: str, warnings: list[str]) -> None:
        case = self._case(case_id)
        for warning in warnings:
            if warning not in case["warnings"]:
                case["warnings"].append(warning)

    def add_case_failure(self, case_id: str, failure: str) -> None:
        case = self._case(case_id)
        if failure and failure not in case["failures"]:
            case["failures"].append(failure)

    @staticmethod
    def _existing_file_path(raw_path: str | Path | None) -> str | None:
        if raw_path is None:
            return None
        path = Path(str(raw_path))
        if not path.exists() or not path.is_file():
            return None
        return str(path.resolve())

    def record_output_paths(self, case_id: str, paths: list[str | Path | None]) -> None:
        """Assign case-specific output files to one case exactly once."""
        case = self._case(case_id)
        owner = f"case:{case_id}"
        for raw_path in paths:
            normalized = self._existing_file_path(raw_path)
            if normalized is None:
                continue
            prior_owner = self._artifact_owners.get(normalized)
            if prior_owner is not None and prior_owner != owner:
                warning = f"artifact_owner_conflict:{normalized}:{prior_owner}"
                if warning not in case["warnings"]:
                    case["warnings"].append(warning)
                continue
            self._artifact_owners[normalized] = owner
            if normalized not in case["output_paths"]:
                case["output_paths"].append(normalized)

    def record_global_output_paths(self, paths: list[str | Path | None]) -> None:
        """Assign shared or run-level output files to the global scope once."""
        for raw_path in paths:
            normalized = self._existing_file_path(raw_path)
            if normalized is None:
                continue
            prior_owner = self._artifact_owners.get(normalized)
            if prior_owner is not None and prior_owner != "global":
                continue
            self._artifact_owners[normalized] = "global"
            if normalized not in self._global_output_paths:
                self._global_output_paths.append(normalized)

    @staticmethod
    def _output_bytes(paths: list[str]) -> int:
        total = 0
        for raw_path in paths:
            try:
                total += Path(raw_path).stat().st_size
            except OSError:
                continue
        return total

    def _final_case(self, case: dict[str, Any]) -> dict[str, Any]:
        total_wall = sum(float(timing["wall_seconds"]) for timing in case["stages"].values())
        total_cpu = sum(float(timing["process_cpu_seconds"]) for timing in case["stages"].values())
        output_paths = list(case["output_paths"])
        return {
            "case_id": case["case_id"],
            "total_duration_seconds": total_wall,
            "total_process_cpu_seconds": total_cpu,
            "total_non_cpu_wall_seconds": max(0.0, total_wall - total_cpu),
            "stages": case["stages"],
            "database_rows_read": case["database_rows_read"],
            "normalized_events": case["normalized_events"],
            "labeled_events": case["labeled_events"],
            "intervals": case["intervals"],
            "output_file_count": len(output_paths),
            "output_bytes_written": self._output_bytes(output_paths),
            "output_paths": output_paths,
            "warnings": case["warnings"],
            "failures": case["failures"],
        }

    def finalize(self) -> None:
        """Freeze the reported wall-clock endpoint after all measured shutdown work."""
        if self._timer_stack:
            raise RuntimeError("Cannot finalize profiling while stage timers are active.")
        self.wall_finished = time.perf_counter()
        self.cpu_finished = time.process_time()

    def build_payload(self) -> dict[str, Any]:
        wall_endpoint = self.wall_finished if self.wall_finished is not None else time.perf_counter()
        cpu_endpoint = self.cpu_finished if self.cpu_finished is not None else time.process_time()
        total_wall = max(0.0, wall_endpoint - self.wall_started)
        total_cpu = max(0.0, cpu_endpoint - self.cpu_started)
        instrumented_wall = sum(float(timing["wall_seconds"]) for timing in self.stage_totals.values())
        unaccounted_wall = total_wall - instrumented_wall
        tolerance_seconds = max(0.01, total_wall * 0.005)
        stage_rows: list[dict[str, Any]] = []
        for rank, (stage, timing) in enumerate(
            sorted(self.stage_totals.items(), key=lambda item: float(item[1]["wall_seconds"]), reverse=True),
            start=1,
        ):
            stage_rows.append(
                {
                    "rank": rank,
                    "stage": stage,
                    **timing,
                    "percent_of_total_runtime": (
                        float(timing["wall_seconds"]) / total_wall * 100.0
                    ) if total_wall else 0.0,
                    "inclusive_percent_of_total_runtime": (
                        float(timing["inclusive_wall_seconds"]) / total_wall * 100.0
                    ) if total_wall else 0.0,
                    "cpu_share_percent_of_stage": (
                        min(100.0, float(timing["process_cpu_seconds"]) / float(timing["wall_seconds"]) * 100.0)
                    ) if float(timing["wall_seconds"]) else 0.0,
                    "work_class": STAGE_WORK_CLASS[stage],
                }
            )
        case_rows = [self._final_case(case) for case in self.cases.values()]
        case_rows.sort(key=lambda row: row["total_duration_seconds"], reverse=True)
        for rank, row in enumerate(case_rows, start=1):
            row["rank"] = rank
        global_paths = list(self._global_output_paths)
        all_unique_paths = sorted(self._artifact_owners)
        return {
            "profiling_mode": "opt_in",
            "timing_model": "nested_exclusive",
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "site_code": self.site_code,
            "output_dir": str(self.output_dir),
            "total_run_time_seconds": total_wall,
            "total_process_cpu_seconds": total_cpu,
            "total_non_cpu_wall_seconds": max(0.0, total_wall - total_cpu),
            "instrumented_stage_total_seconds": instrumented_wall,
            "unaccounted_runtime_seconds": unaccounted_wall,
            "stage_coverage_percent": (instrumented_wall / total_wall * 100.0) if total_wall else 0.0,
            "reconciliation_tolerance_seconds": tolerance_seconds,
            "timing_reconciliation_status": (
                "PASS" if abs(unaccounted_wall) <= tolerance_seconds else "FAIL"
            ),
            "stage_totals_ranked": stage_rows,
            "case_totals_ranked": case_rows,
            "artifact_metrics": {
                "case_output_file_count": sum(row["output_file_count"] for row in case_rows),
                "case_output_bytes_written": sum(row["output_bytes_written"] for row in case_rows),
                "global_output_file_count": len(global_paths),
                "global_output_bytes_written": self._output_bytes(global_paths),
                "total_unique_output_file_count": len(all_unique_paths),
                "total_unique_output_bytes_written": self._output_bytes(all_unique_paths),
                "global_output_paths": global_paths,
            },
            "notes": [
                "Wall time uses time.perf_counter().",
                "Stage wall_seconds is exclusive and additive; inclusive_wall_seconds retains complete nested-span duration.",
                "process_cpu_seconds uses time.process_time(); non_cpu_wall_seconds is an I/O/waiting proxy, not a direct I/O measurement.",
                "Each output file has one owner: one case or the global run scope. Shared artifacts are counted globally once.",
                "Profiling is observational and does not alter default pipeline behavior, selection, database handling, output contracts, or publication gates.",
            ],
        }

    @staticmethod
    def _case_csv_text(payload: dict[str, Any]) -> str:
        stage_columns = [stage.replace(" ", "_") + "_seconds" for stage in PROFILE_STAGES]
        fieldnames = [
            "rank",
            "case_id",
            "total_duration_seconds",
            "total_process_cpu_seconds",
            "total_non_cpu_wall_seconds",
            *stage_columns,
            "database_rows_read",
            "normalized_events",
            "labeled_events",
            "intervals",
            "output_file_count",
            "output_bytes_written",
            "warning_count",
            "failure_count",
            "warnings",
            "failures",
        ]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for case in payload["case_totals_ranked"]:
            row: dict[str, Any] = {
                "rank": case["rank"],
                "case_id": case["case_id"],
                "total_duration_seconds": f"{case['total_duration_seconds']:.6f}",
                "total_process_cpu_seconds": f"{case['total_process_cpu_seconds']:.6f}",
                "total_non_cpu_wall_seconds": f"{case['total_non_cpu_wall_seconds']:.6f}",
                "database_rows_read": case["database_rows_read"],
                "normalized_events": case["normalized_events"],
                "labeled_events": case["labeled_events"],
                "intervals": case["intervals"],
                "output_file_count": case["output_file_count"],
                "output_bytes_written": case["output_bytes_written"],
                "warning_count": len(case["warnings"]),
                "failure_count": len(case["failures"]),
                "warnings": " | ".join(case["warnings"]),
                "failures": " | ".join(case["failures"]),
            }
            for stage in PROFILE_STAGES:
                row[stage.replace(" ", "_") + "_seconds"] = (
                    f"{case['stages'][stage]['wall_seconds']:.6f}"
                )
            writer.writerow(row)
        return buffer.getvalue()

    def write_reports(self, reports_dir: Path) -> tuple[Path, Path]:
        """Write profiling reports after measuring their first serialization/write pass."""
        reports_dir.mkdir(parents=True, exist_ok=True)
        summary_path = reports_dir / "performance_summary.json"
        csv_path = reports_dir / "performance_by_case.csv"

        with self.stage("report assembly and serialization"):
            preliminary_payload = self.build_payload()
            preliminary_json = json.dumps(preliminary_payload, indent=2, sort_keys=True) + "\n"
            preliminary_csv = self._case_csv_text(preliminary_payload)
        with self.stage("all artifact writes"):
            summary_path.write_text(preliminary_json, encoding="utf-8")
            csv_path.write_text(preliminary_csv, encoding="utf-8", newline="")
        with self.stage("final output discovery"):
            self.record_global_output_paths([summary_path, csv_path])
        with self.stage("shutdown"):
            pass
        self.finalize()

        previous_sizes: tuple[int, int] | None = None
        for _ in range(5):
            payload = self.build_payload()
            summary_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            csv_path.write_text(self._case_csv_text(payload), encoding="utf-8", newline="")
            current_sizes = (summary_path.stat().st_size, csv_path.stat().st_size)
            if current_sizes == previous_sizes:
                break
            previous_sizes = current_sizes
        return summary_path, csv_path
