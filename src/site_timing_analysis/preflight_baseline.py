# Project: Site Timing Analysis
# File: src/site_timing_analysis/preflight_baseline.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Captures and verifies reusable repository preflight evidence for timeline runs.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Sequence
import uuid


SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_HOURS = 24.0
TEST_COMMAND_CONTRACT = (
    "$PYTHON",
    "-m",
    "pytest",
    "-q",
    "-p",
    "no:cacheprovider",
    "--basetemp=$BASE_TEMP",
)
REQUIRED_GATE_NAMES = (
    "git_diff_check",
    "pytest",
    "pip_check",
    "timeline_analysis_help",
    "timeline_store_help",
)
LOGGER = logging.getLogger(__name__)


class BaselineError(RuntimeError):
    """Raised when baseline evidence cannot be captured or safely reused."""


def _run_command(
    args: Sequence[str],
    *,
    cwd: Path,
) -> dict[str, Any]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
        capture_output=True,
        check=False,
    )
    stdout_bytes = bytes(completed.stdout or b"")
    stderr_bytes = bytes(completed.stderr or b"")
    return {
        "command": list(args),
        "returncode": int(completed.returncode),
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "stdout_sha256": _sha256_bytes(stdout_bytes),
        "stderr_sha256": _sha256_bytes(stderr_bytes),
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_command(
    command_runner: Callable[..., dict[str, Any]],
    args: Sequence[str],
    *,
    repository_root: Path,
    label: str,
) -> dict[str, Any]:
    result = command_runner(list(args), cwd=repository_root)
    if int(result.get("returncode", 1)) != 0:
        detail = str(result.get("stderr") or result.get("stdout") or "no output").strip()
        raise BaselineError(f"Could not establish {label}: {detail}")
    return result


def _dependency_inventory(
    repository_root: Path,
    *,
    python_executable: Path,
    command_runner: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    result = _required_command(
        command_runner,
        [str(python_executable), "-m", "pip", "freeze", "--all"],
        repository_root=repository_root,
        label="dependency inventory",
    )
    lines = sorted(
        line.strip()
        for line in str(result.get("stdout", "")).splitlines()
        if line.strip()
    )
    normalized = "\n".join(lines) + ("\n" if lines else "")
    return {
        "command": result["command"],
        "packages": lines,
        "sha256": _sha256_bytes(normalized.encode("utf-8")),
    }


def _git_identity(
    repository_root: Path,
    *,
    command_runner: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    head = _required_command(
        command_runner,
        ["git", "rev-parse", "HEAD"],
        repository_root=repository_root,
        label="Git commit",
    )
    branch = _required_command(
        command_runner,
        ["git", "branch", "--show-current"],
        repository_root=repository_root,
        label="Git branch",
    )
    status = _required_command(
        command_runner,
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        repository_root=repository_root,
        label="Git status",
    )
    diff = _required_command(
        command_runner,
        ["git", "diff", "--binary", "HEAD"],
        repository_root=repository_root,
        label="Git tracked diff",
    )
    untracked_result = _required_command(
        command_runner,
        ["git", "ls-files", "--others", "--exclude-standard"],
        repository_root=repository_root,
        label="Git untracked inventory",
    )
    untracked: list[dict[str, Any]] = []
    for relative_text in sorted(str(untracked_result.get("stdout", "")).splitlines()):
        relative_text = relative_text.strip()
        if not relative_text:
            continue
        path = (repository_root / relative_text).resolve()
        try:
            path.relative_to(repository_root)
        except ValueError as exc:
            raise BaselineError(f"Untracked path escaped repository root: {relative_text}") from exc
        if path.is_file():
            untracked.append(
                {
                    "path": relative_text.replace("\\", "/"),
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        else:
            untracked.append(
                {
                    "path": relative_text.replace("\\", "/"),
                    "size": None,
                    "sha256": None,
                }
            )
    tracked_diff_sha256 = str(
        diff.get("stdout_sha256")
        or _sha256_bytes(str(diff.get("stdout", "")).encode("utf-8"))
    )
    dirty_basis = {
        "status": str(status.get("stdout", "")),
        "tracked_diff_sha256": tracked_diff_sha256,
        "untracked": untracked,
    }
    dirty_serialized = json.dumps(
        dirty_basis,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "head_commit": str(head.get("stdout", "")).strip(),
        "branch": str(branch.get("stdout", "")).strip(),
        "status_short": str(status.get("stdout", "")),
        "dirty": bool(str(status.get("stdout", "")).strip()),
        "dirty_fingerprint_sha256": _sha256_bytes(dirty_serialized),
        "tracked_diff_sha256": dirty_basis["tracked_diff_sha256"],
        "untracked_files": untracked,
    }


def collect_identity(
    repository_root: Path,
    *,
    command_runner: Callable[..., dict[str, Any]] = _run_command,
) -> dict[str, Any]:
    """Collect repository, interpreter, dependency, and test-contract identity."""
    repository_root = repository_root.resolve()
    python_executable = Path(sys.executable).resolve()
    expected_python = (repository_root / ".venv" / "Scripts" / "python.exe").resolve()
    if python_executable != expected_python:
        raise BaselineError(f"Preflight must use the repository interpreter: {expected_python}")
    dependency_inventory = _dependency_inventory(
        repository_root,
        python_executable=python_executable,
        command_runner=command_runner,
    )
    return {
        "repository_root": str(repository_root),
        "git": _git_identity(repository_root, command_runner=command_runner),
        "interpreter": {
            "path": str(python_executable),
            "version": sys.version,
            "executable_sha256": _sha256_file(python_executable),
        },
        "dependencies": dependency_inventory,
        "test_command_contract": list(TEST_COMMAND_CONTRACT),
        "test_command_contract_sha256": _sha256_bytes(
            json.dumps(TEST_COMMAND_CONTRACT, separators=(",", ":")).encode("utf-8")
        ),
    }


def capture_baseline(
    *,
    repository_root: Path,
    basetemp: Path,
    command_runner: Callable[..., dict[str, Any]] = _run_command,
) -> dict[str, Any]:
    """Capture live preflight evidence and the identity required for later reuse."""
    repository_root = repository_root.resolve()
    identity = collect_identity(repository_root, command_runner=command_runner)
    python_executable = str(Path(sys.executable).resolve())
    gates = {
        "git_diff_check": command_runner(["git", "diff", "--check"], cwd=repository_root),
        "pytest": command_runner(
            [
                python_executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--basetemp={basetemp.resolve()}",
            ],
            cwd=repository_root,
        ),
        "pip_check": command_runner(
            [python_executable, "-m", "pip", "check"], cwd=repository_root
        ),
        "timeline_analysis_help": command_runner(
            [python_executable, "scripts/run_timeline_analysis.py", "--help"],
            cwd=repository_root,
        ),
        "timeline_store_help": command_runner(
            [python_executable, "scripts/timeline_store.py", "--help"],
            cwd=repository_root,
        ),
    }
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "captured_at_utc": now.isoformat(),
        "captured_at": now.astimezone().isoformat(timespec="seconds"),
        "baseline_mode": "live",
        "python_executable": python_executable,
        "identity": identity,
        "git_branch": {
            "command": ["git", "branch", "--show-current"],
            "returncode": 0,
            "stdout": str(identity["git"]["branch"]) + "\n",
            "stderr": "",
        },
        "git_status": {
            "command": ["git", "status", "--short"],
            "returncode": 0,
            "stdout": str(identity["git"]["status_short"]),
            "stderr": "",
        },
        **gates,
    }
    failed = [
        name for name in REQUIRED_GATE_NAMES if int(payload[name].get("returncode", 1)) != 0
    ]
    payload["gate_status"] = "PASS" if not failed else "FAIL"
    payload["failed_gates"] = failed
    return payload


def _parse_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise BaselineError(f"Snapshot captured_at_utc is invalid: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BaselineError("Snapshot captured_at_utc must include a timezone.")
    return parsed.astimezone(timezone.utc)


def validate_snapshot(
    snapshot: dict[str, Any],
    *,
    repository_root: Path,
    max_age_hours: float,
    now: datetime | None = None,
    command_runner: Callable[..., dict[str, Any]] = _run_command,
) -> dict[str, Any]:
    """Require a fresh exact match before accepting baseline reuse."""
    if int(snapshot.get("schema_version", 0)) != SNAPSHOT_SCHEMA_VERSION:
        raise BaselineError("Baseline snapshot schema version is unsupported.")
    if max_age_hours <= 0:
        raise BaselineError("Baseline snapshot max age must be greater than zero hours.")
    captured_at = _parse_utc(snapshot.get("captured_at_utc"))
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (current_time - captured_at).total_seconds()
    if age_seconds < -60:
        raise BaselineError("Baseline snapshot capture time is unexpectedly in the future.")
    if age_seconds > max_age_hours * 3600:
        raise BaselineError(
            f"Baseline snapshot is stale ({age_seconds / 3600:.2f} hours; "
            f"maximum {max_age_hours:.2f})."
        )

    failed = [
        name
        for name in REQUIRED_GATE_NAMES
        if not isinstance(snapshot.get(name), dict)
        or int(snapshot[name].get("returncode", 1)) != 0
    ]
    if failed or snapshot.get("gate_status") != "PASS":
        raise BaselineError(
            "Baseline snapshot did not pass every required gate: " + ", ".join(failed)
        )

    current_identity = collect_identity(repository_root, command_runner=command_runner)
    stored_identity = snapshot.get("identity")
    if not isinstance(stored_identity, dict):
        raise BaselineError("Baseline snapshot identity is missing.")
    comparisons = {
        "repository_root": (
            stored_identity.get("repository_root"),
            current_identity["repository_root"],
        ),
        "git_head_commit": (
            dict(stored_identity.get("git", {})).get("head_commit"),
            current_identity["git"]["head_commit"],
        ),
        "git_dirty_fingerprint": (
            dict(stored_identity.get("git", {})).get("dirty_fingerprint_sha256"),
            current_identity["git"]["dirty_fingerprint_sha256"],
        ),
        "interpreter_path": (
            dict(stored_identity.get("interpreter", {})).get("path"),
            current_identity["interpreter"]["path"],
        ),
        "interpreter_version": (
            dict(stored_identity.get("interpreter", {})).get("version"),
            current_identity["interpreter"]["version"],
        ),
        "interpreter_sha256": (
            dict(stored_identity.get("interpreter", {})).get("executable_sha256"),
            current_identity["interpreter"]["executable_sha256"],
        ),
        "dependency_fingerprint": (
            dict(stored_identity.get("dependencies", {})).get("sha256"),
            current_identity["dependencies"]["sha256"],
        ),
        "test_command_contract": (
            stored_identity.get("test_command_contract_sha256"),
            current_identity["test_command_contract_sha256"],
        ),
    }
    mismatches = [name for name, (stored, current) in comparisons.items() if stored != current]
    if mismatches:
        raise BaselineError(
            "Baseline snapshot does not match the current execution identity: "
            + ", ".join(mismatches)
        )
    return {
        "status": "PASS",
        "age_seconds": max(0.0, age_seconds),
        "max_age_hours": max_age_hours,
        "identity_checks": sorted(comparisons),
    }


def load_reusable_baseline(
    snapshot_path: Path,
    *,
    repository_root: Path,
    max_age_hours: float,
    command_runner: Callable[..., dict[str, Any]] = _run_command,
) -> dict[str, Any]:
    """Load, hash, verify, and annotate a reusable baseline snapshot."""
    snapshot_path = snapshot_path.expanduser().resolve()
    if not snapshot_path.is_file():
        raise BaselineError(f"Baseline snapshot does not exist: {snapshot_path}")
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"Could not read baseline snapshot {snapshot_path}: {exc}") from exc
    if not isinstance(snapshot, dict):
        raise BaselineError("Baseline snapshot root must be a JSON object.")
    validation = validate_snapshot(
        snapshot,
        repository_root=repository_root,
        max_age_hours=max_age_hours,
        command_runner=command_runner,
    )
    reused = dict(snapshot)
    reused["baseline_mode"] = "reused"
    reused["reused_snapshot"] = {
        "path": str(snapshot_path),
        "sha256": _sha256_file(snapshot_path),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        **validation,
    }
    return reused


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_snapshot(
    path: Path,
    snapshot: dict[str, Any],
    *,
    repository_root: Path,
    overwrite: bool,
) -> Path:
    """Atomically persist reusable evidence outside the repository."""
    path = path.expanduser().resolve()
    repository_root = repository_root.resolve()
    if _is_relative_to(path, repository_root):
        raise BaselineError("Reusable baseline snapshots must be stored outside the repository.")
    if path.exists() and not overwrite:
        raise BaselineError(f"Refusing to overwrite baseline snapshot: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture or validate reusable Timeline Analysis preflight evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture", help="Run live gates and save a snapshot.")
    capture_parser.add_argument("--output", required=True)
    capture_parser.add_argument("--overwrite", action="store_true")
    validate_parser = subparsers.add_parser("validate", help="Validate a snapshot without running tests.")
    validate_parser.add_argument("--snapshot", required=True)
    validate_parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Provide a PowerShell-friendly baseline capture and validation CLI."""
    args = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command == "capture":
            LOGGER.info("Capturing live repository, dependency, test, and CLI gate evidence.")
            output = Path(args.output).expanduser().resolve()
            snapshot = capture_baseline(
                repository_root=repository_root,
                basetemp=output.parent / ".baseline_pytest_tmp",
            )
            if snapshot["gate_status"] != "PASS":
                failed = ", ".join(snapshot["failed_gates"])
                raise BaselineError(f"Live baseline gates failed: {failed}")
            written = write_snapshot(
                output,
                snapshot,
                repository_root=repository_root,
                overwrite=args.overwrite,
            )
            print(f"Baseline snapshot: {written}")
            return 0
        LOGGER.info("Validating reusable baseline identity and freshness without rerunning tests.")
        validation = load_reusable_baseline(
            Path(args.snapshot),
            repository_root=repository_root,
            max_age_hours=args.max_age_hours,
        )
        print(
            f"Baseline snapshot valid: {Path(args.snapshot).expanduser().resolve()} "
            f"age_seconds={validation['reused_snapshot']['age_seconds']:.3f}"
        )
        return 0
    except BaselineError as exc:
        LOGGER.error("Baseline failed: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
