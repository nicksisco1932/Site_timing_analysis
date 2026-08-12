# Project: Site Timing Analysis
# File: testing/tests/test_preflight_baseline.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Tests exact reusable preflight identity, freshness, persistence, and rejection behavior.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from site_timing_analysis.preflight_baseline import (
    BaselineError,
    _run_command,
    capture_baseline,
    load_reusable_baseline,
    validate_snapshot,
    write_snapshot,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_command_capture_hashes_raw_bytes_without_console_codepage_failure() -> None:
    raw = b"valid-utf8:\xe2\x80\x94 invalid-cp1252:\x9d"
    result = _run_command(
        [
            str(REPOSITORY_ROOT / ".venv" / "Scripts" / "python.exe"),
            "-c",
            f"import sys; sys.stdout.buffer.write({raw!r})",
        ],
        cwd=REPOSITORY_ROOT,
    )
    assert result["returncode"] == 0
    assert result["stdout_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "valid-utf8:—" in result["stdout"]


class FakeCommandRunner:
    def __init__(self, *, status: str = "", diff: str = "", dependencies: str = "a==1\n"):
        self.status = status
        self.diff = diff
        self.dependencies = dependencies
        self.failures: dict[tuple[str, ...], int] = {}

    def __call__(self, args, *, cwd):
        command = tuple(str(value) for value in args)
        returncode = self.failures.get(command, 0)
        stdout = ""
        if command[:3] == ("git", "rev-parse", "HEAD"):
            stdout = "a" * 40 + "\n"
        elif command[:3] == ("git", "branch", "--show-current"):
            stdout = "codex/test\n"
        elif command[:3] == ("git", "status", "--porcelain=v1"):
            stdout = self.status
        elif command[:4] == ("git", "diff", "--binary", "HEAD"):
            stdout = self.diff
        elif command[:3] == ("git", "ls-files", "--others"):
            stdout = ""
        elif command[-4:] == ("-m", "pip", "freeze", "--all"):
            stdout = self.dependencies
        elif command[-3:] == ("-m", "pip", "check"):
            stdout = "No broken requirements found.\n"
        elif "pytest" in command:
            stdout = "215 passed\n"
        elif command[-1:] == ("--help",):
            stdout = "usage: synthetic\n"
        return {
            "command": list(command),
            "returncode": returncode,
            "stdout": stdout,
            "stderr": "synthetic failure" if returncode else "",
        }


def _snapshot(tmp_path: Path, runner: FakeCommandRunner | None = None):
    return capture_baseline(
        repository_root=REPOSITORY_ROOT,
        basetemp=tmp_path / "pytest",
        command_runner=runner or FakeCommandRunner(),
    )


def test_capture_records_required_identity_and_passing_gates(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    assert snapshot["schema_version"] == 1
    assert snapshot["gate_status"] == "PASS"
    assert snapshot["identity"]["git"]["head_commit"] == "a" * 40
    assert len(snapshot["identity"]["git"]["dirty_fingerprint_sha256"]) == 64
    assert len(snapshot["identity"]["interpreter"]["executable_sha256"]) == 64
    assert len(snapshot["identity"]["dependencies"]["sha256"]) == 64
    assert snapshot["identity"]["test_command_contract"][-1] == "--basetemp=$BASE_TEMP"


def test_exact_fresh_snapshot_is_reusable_without_running_pytest(tmp_path: Path) -> None:
    runner = FakeCommandRunner()
    snapshot = _snapshot(tmp_path, runner)
    captured = datetime.fromisoformat(snapshot["captured_at_utc"])
    validation = validate_snapshot(
        snapshot,
        repository_root=REPOSITORY_ROOT,
        max_age_hours=24,
        now=captured + timedelta(minutes=1),
        command_runner=runner,
    )
    assert validation["status"] == "PASS"
    assert validation["age_seconds"] == pytest.approx(60.0)


def test_stale_failed_or_mismatched_snapshot_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    captured = datetime.fromisoformat(snapshot["captured_at_utc"])
    with pytest.raises(BaselineError, match="stale"):
        validate_snapshot(
            snapshot,
            repository_root=REPOSITORY_ROOT,
            max_age_hours=1,
            now=captured + timedelta(hours=2),
            command_runner=FakeCommandRunner(),
        )

    failed = deepcopy(snapshot)
    failed["pytest"]["returncode"] = 1
    failed["gate_status"] = "FAIL"
    with pytest.raises(BaselineError, match="did not pass"):
        validate_snapshot(
            failed,
            repository_root=REPOSITORY_ROOT,
            max_age_hours=24,
            now=captured,
            command_runner=FakeCommandRunner(),
        )

    with pytest.raises(BaselineError, match="git_dirty_fingerprint"):
        validate_snapshot(
            snapshot,
            repository_root=REPOSITORY_ROOT,
            max_age_hours=24,
            now=captured,
            command_runner=FakeCommandRunner(status=" M README.md\n", diff="changed"),
        )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (("identity", "repository_root"), "C:\\different-repository", "repository_root"),
        (("identity", "git", "head_commit"), "b" * 40, "git_head_commit"),
        (("identity", "interpreter", "version"), "different", "interpreter_version"),
        (("identity", "interpreter", "executable_sha256"), "0" * 64, "interpreter_sha256"),
        (("identity", "dependencies", "sha256"), "0" * 64, "dependency_fingerprint"),
        (("identity", "test_command_contract_sha256"), "0" * 64, "test_command_contract"),
    ],
)
def test_snapshot_identity_components_are_independently_required(
    tmp_path: Path,
    field: tuple[str, ...],
    value: str,
    expected: str,
) -> None:
    snapshot = _snapshot(tmp_path)
    target = snapshot
    for key in field[:-1]:
        target = target[key]
    target[field[-1]] = value
    captured = datetime.fromisoformat(snapshot["captured_at_utc"])
    with pytest.raises(BaselineError, match=expected):
        validate_snapshot(
            snapshot,
            repository_root=REPOSITORY_ROOT,
            max_age_hours=24,
            now=captured,
            command_runner=FakeCommandRunner(),
        )


def test_snapshot_persistence_is_external_atomic_and_overwrite_safe(tmp_path: Path) -> None:
    fake_repository = tmp_path / "repository"
    fake_repository.mkdir()
    external = tmp_path / "evidence" / "baseline.json"
    snapshot = {"schema_version": 1, "value": None, "blob_digest": "00ff"}
    written = write_snapshot(
        external,
        snapshot,
        repository_root=fake_repository,
        overwrite=False,
    )
    assert json.loads(written.read_text(encoding="utf-8")) == snapshot
    with pytest.raises(BaselineError, match="Refusing to overwrite"):
        write_snapshot(
            external,
            snapshot,
            repository_root=fake_repository,
            overwrite=False,
        )
    with pytest.raises(BaselineError, match="outside the repository"):
        write_snapshot(
            fake_repository / "baseline.json",
            snapshot,
            repository_root=fake_repository,
            overwrite=False,
        )


def test_loaded_snapshot_retains_full_gate_evidence_and_source_hash(tmp_path: Path) -> None:
    runner = FakeCommandRunner()
    snapshot = _snapshot(tmp_path, runner)
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    reused = load_reusable_baseline(
        path,
        repository_root=REPOSITORY_ROOT,
        max_age_hours=24,
        command_runner=runner,
    )
    assert reused["baseline_mode"] == "reused"
    assert reused["pytest"] == snapshot["pytest"]
    assert reused["reused_snapshot"]["status"] == "PASS"
    assert len(reused["reused_snapshot"]["sha256"]) == 64


def test_validated_exporter_requires_explicit_snapshot_for_reuse() -> None:
    script_path = REPOSITORY_ROOT / "scripts" / "run_asui_122_timeline_analysis.py"
    spec = importlib.util.spec_from_file_location("baseline_exporter_contract", script_path)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    with pytest.raises(SystemExit) as exc_info:
        exporter.parse_args(["--baseline-mode", "reuse"])
    assert exc_info.value.code == 2
    parsed = exporter.parse_args(
        ["--baseline-mode", "reuse", "--baseline-snapshot", "C:\\evidence\\baseline.json"]
    )
    assert parsed.baseline_mode == "reuse"
    assert parsed.baseline_max_age_hours == 24.0
