# Project: Site Timing Analysis
# File: src/site_timing_analysis/onboarding.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Guides Windows users through read-only site discovery and reusable runner generation.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Sequence
import uuid

from .config import build_run_config
from .db_source import resolve_database_source
from .discovery import discover_cases


PROFILE_SCHEMA_VERSION = 1
MINIMUM_PYTHON = (3, 12)
DEFAULT_PROFILE_DIRECTORY = Path("Profound Medical") / "SiteTimingAnalysis"
_SITE_ID_PATTERN = re.compile(r"^\d{3}$")
_SITE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*_(\d{3})$")
LOGGER = logging.getLogger(__name__)


class OnboardingError(RuntimeError):
    """Raised when guided initialization cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Sanitized result for one onboarding environment check."""

    name: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class SiteInventory:
    """Read-only summary of one local site and its canonical case sources."""

    site_id: str
    site_code: str
    site_root: Path
    canonical_prefix: str
    case_ids: tuple[str, ...]
    usable_case_ids: tuple[str, ...]
    case_issues: tuple[dict[str, str], ...]


def validate_windows_runtime(
    *,
    platform_name: str | None = None,
    version_info: Sequence[int] | None = None,
) -> None:
    """Validate the supported Windows and Python runtime without modifying it."""
    platform_value = os.name if platform_name is None else platform_name
    version_value = tuple(sys.version_info[:3] if version_info is None else version_info)
    if platform_value != "nt":
        raise OnboardingError("Timeline Analysis guided initialization currently requires Windows.")
    if version_value[:2] < MINIMUM_PYTHON:
        raise OnboardingError(
            f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required; "
            f"found {'.'.join(str(part) for part in version_value[:3])}."
        )


def environment_creation_plan(repository_root: Path) -> dict[str, object]:
    """Describe whether the repository virtual environment must be created."""
    repository_root = repository_root.resolve()
    environment_root = repository_root / ".venv"
    python_executable = environment_root / "Scripts" / "python.exe"
    return {
        "repository_root": str(repository_root),
        "environment_root": str(environment_root),
        "python_executable": str(python_executable),
        "environment_exists": environment_root.is_dir(),
        "python_exists": python_executable.is_file(),
        "creation_required": not python_executable.is_file(),
    }


def _run_command(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def run_environment_checks(
    repository_root: Path,
    *,
    include_full_tests: bool,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[CommandResult, ...]:
    """Run dependency and CLI checks with the current repository interpreter."""
    repository_root = repository_root.resolve()
    expected_python = (repository_root / ".venv" / "Scripts" / "python.exe").resolve()
    actual_python = Path(sys.executable).resolve()
    if actual_python != expected_python:
        raise OnboardingError(
            f"Initializer must run with the repository virtual environment: {expected_python}"
        )

    commands: list[tuple[str, tuple[str, ...]]] = [
        ("pip_check", (str(actual_python), "-m", "pip", "check")),
        (
            "staged_pipeline_help",
            (str(actual_python), "-m", "site_timing_analysis.first_slice_cli", "--help"),
        ),
        (
            "timeline_analysis_help",
            (str(actual_python), "scripts/run_timeline_analysis.py", "--help"),
        ),
        (
            "deliverable_builder_help",
            (str(actual_python), "scripts/build_timing_gantt_deliverables.py", "--help"),
        ),
        ("timeline_store_help", (str(actual_python), "scripts/timeline_store.py", "--help")),
    ]
    if include_full_tests:
        commands.append(
            (
                "full_test_suite",
                (
                    str(actual_python),
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp=.pytest_tmp_onboarding",
                ),
            )
        )

    results: list[CommandResult] = []
    for name, command in commands:
        completed = command_runner(command, cwd=repository_root)
        result = CommandResult(
            name=name,
            command=tuple(command),
            returncode=int(completed.returncode),
            stdout=str(completed.stdout or ""),
            stderr=str(completed.stderr or ""),
        )
        results.append(result)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            raise OnboardingError(f"Environment check '{name}' failed: {detail}")
    return tuple(results)


def normalize_site_id(value: str) -> str:
    """Return a validated three-digit site identifier."""
    normalized = str(value).strip()
    if not _SITE_ID_PATTERN.fullmatch(normalized):
        raise OnboardingError("Site ID must contain exactly three digits, for example 122.")
    return normalized


def teams_sync_guidance(site_id: str) -> str:
    """Return the standard actionable message for a missing Teams site folder."""
    return (
        f"Site {site_id} is not available locally. Sync the site directory ending in _{site_id} "
        "from the Clinical Science Team through the Teams app, then rerun."
    )


def resolve_local_site(local_root: Path, site_id: str) -> tuple[Path, str]:
    """Resolve exactly one immediate Teams-synced directory for a site ID."""
    site_id = normalize_site_id(site_id)
    local_root = local_root.expanduser().resolve()
    if not local_root.is_dir():
        raise OnboardingError(f"Local parent directory does not exist: {local_root}")
    suffix = f"_{site_id}".casefold()
    matches = sorted(
        (
            path
            for path in local_root.iterdir()
            if path.is_dir() and path.name.casefold().endswith(suffix)
        ),
        key=lambda path: path.name.casefold(),
    )
    if not matches:
        raise OnboardingError(teams_sync_guidance(site_id))
    if len(matches) != 1:
        joined = ", ".join(str(path) for path in matches)
        raise OnboardingError(
            f"Site {site_id} is ambiguous under {local_root}; expected one immediate directory, "
            f"found {len(matches)}: {joined}"
        )

    site_root = matches[0].resolve()
    candidate_code = site_root.name.split(" - ")[-1].strip()
    match = _SITE_CODE_PATTERN.fullmatch(candidate_code)
    if match is None or match.group(1) != site_id:
        raise OnboardingError(
            f"Could not derive a valid site code ending in _{site_id} from {site_root.name}."
        )
    return site_root, candidate_code


def inventory_local_site(
    *,
    repository_root: Path,
    local_root: Path,
    site_id: str,
) -> SiteInventory:
    """Inventory canonical case folders and database candidates without writing sources."""
    site_root, site_code = resolve_local_site(local_root, site_id)
    canonical_prefix = f"{site_id}_"
    config = build_run_config(
        site_code=site_code,
        year_selection="All",
        root_dir=local_root,
        output_dir=repository_root / "outputs" / "timing_gantt",
        site_path=site_root,
    )
    records = discover_cases(config)
    usable: list[str] = []
    issues: list[dict[str, str]] = []
    for record in records:
        try:
            source = resolve_database_source(record)
        except Exception as exc:
            issues.append(
                {
                    "case_id": record.case_id,
                    "status": "quarantined",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        usable.append(record.case_id)
        if source.ambiguous_candidates:
            issues.append(
                {
                    "case_id": record.case_id,
                    "status": "quarantined",
                    "reason": "ambiguous_database_source",
                }
            )

    return SiteInventory(
        site_id=site_id,
        site_code=site_code,
        site_root=site_root,
        canonical_prefix=canonical_prefix,
        case_ids=tuple(record.case_id for record in records),
        usable_case_ids=tuple(usable),
        case_issues=tuple(issues),
    )


def read_case_manifest(path: Path, inventory: SiteInventory) -> tuple[str, ...]:
    """Validate a newline-delimited explicit canonical case selection."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise OnboardingError(f"Case-list manifest does not exist: {path}")
    selected: list[str] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    invalid: list[str] = []
    available = set(inventory.case_ids)
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        token = raw_line.strip().strip('"')
        if not token or token.startswith("#"):
            continue
        case_id = Path(token).name if ("/" in token or "\\" in token) else token
        if case_id in seen:
            duplicates.append(case_id)
            continue
        seen.add(case_id)
        if not case_id.startswith(inventory.canonical_prefix) or case_id not in available:
            invalid.append(case_id)
            continue
        selected.append(case_id)
    if duplicates:
        raise OnboardingError(f"Case-list manifest contains duplicates: {', '.join(sorted(duplicates))}")
    if invalid:
        raise OnboardingError(
            "Case-list manifest contains missing or noncanonical cases: "
            + ", ".join(sorted(invalid))
        )
    if not selected:
        raise OnboardingError("Case-list manifest does not select any canonical cases.")
    return tuple(selected)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _site_slug(site_code: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", site_code.casefold()).strip("_")


def build_profile(
    *,
    repository_root: Path,
    inventory: SiteInventory,
    selection_mode: str,
    case_list_path: Path | None,
    selected_case_count: int,
    rollup_path: Path | None,
    cache_database: Path | None,
    output_root: Path,
) -> dict[str, object]:
    """Build the versioned non-secret per-user onboarding profile."""
    if selection_mode not in {"all", "manifest"}:
        raise OnboardingError("Selection mode must be 'all' or 'manifest'.")
    if selection_mode == "manifest" and case_list_path is None:
        raise OnboardingError("Manifest selection requires an explicit case-list path.")
    if rollup_path is not None and not rollup_path.is_file():
        raise OnboardingError(f"Roll-up comparator does not exist: {rollup_path}")
    if cache_database is not None and not cache_database.is_file():
        raise OnboardingError(f"Read-only cache database does not exist: {cache_database}")

    selection: dict[str, object] = {
        "mode": selection_mode,
        "selected_case_count": selected_case_count,
        "case_list_path": str(case_list_path.resolve()) if case_list_path else None,
        "case_list_sha256": _sha256_file(case_list_path) if case_list_path else None,
    }
    profile: dict[str, object] = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(repository_root.resolve()),
        "site_id": inventory.site_id,
        "site_code": inventory.site_code,
        "site_root": str(inventory.site_root),
        "canonical_prefix": inventory.canonical_prefix,
        "selection": selection,
        "rollup_path": str(rollup_path.resolve()) if rollup_path else None,
        "cache": {
            "mode": "read-only" if cache_database else "off",
            "database": str(cache_database.resolve()) if cache_database else None,
        },
        "output_root": str(output_root.resolve()),
        "inventory": {
            "canonical_case_count": len(inventory.case_ids),
            "usable_database_count": len(inventory.usable_case_ids),
            "quarantined_case_count": len(inventory.case_issues),
        },
    }
    validate_profile_safety(profile)
    return profile


def validate_profile_safety(profile: dict[str, object]) -> None:
    """Reject secret-bearing keys or Sync endpoint values before persistence."""
    forbidden_key_parts = ("password", "credential", "signed_token", "sync_url", "decryption_key")

    def walk(value: object, trail: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold()
                if any(part in normalized for part in forbidden_key_parts):
                    raise OnboardingError(f"Profile contains forbidden secret field: {'.'.join((*trail, str(key)))}")
                walk(child, (*trail, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*trail, str(index)))
        elif isinstance(value, str):
            normalized_value = value.casefold()
            if normalized_value.startswith(("http://", "https://")):
                raise OnboardingError(f"Profile contains a forbidden remote URL at {'.'.join(trail)}")
            if any(part in normalized_value for part in ("password=", "pltoken=", "access_token=")):
                raise OnboardingError(f"Profile contains forbidden credential material at {'.'.join(trail)}")

    walk(profile)


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def render_runner(profile: dict[str, object]) -> str:
    """Render a safely quoted PowerShell runner for the validated exporter."""
    selection = dict(profile["selection"])  # type: ignore[arg-type]
    cache = dict(profile["cache"])  # type: ignore[arg-type]
    repo_root = Path(str(profile["repository_root"]))
    site_code = str(profile["site_code"])
    site_slug = _site_slug(site_code)
    arguments = [
        "scripts\\run_timeline_analysis.py",
        "--site",
        site_code,
        "--site-root",
        str(profile["site_root"]),
        "--canonical-prefix",
        str(profile["canonical_prefix"]),
    ]
    if selection["mode"] == "all":
        arguments.append("--select-all-canonical")
    else:
        arguments.extend(
            [
                "--case-list",
                str(selection["case_list_path"]),
                "--allow-unselected-canonical",
            ]
        )
    if profile.get("rollup_path"):
        arguments.extend(["--rollup", str(profile["rollup_path"])])
    if cache["mode"] == "read-only":
        arguments.extend(
            ["--database", str(cache["database"]), "--cache-mode", "read-only"]
        )

    argument_lines = "\n".join(f"  {_ps_literal(value)}" for value in arguments)
    return f"""# Project: Site Timing Analysis
# Generated per-user runner for {site_code}; contains no credentials.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = {_ps_literal(repo_root)}
$python = Join-Path $repoRoot '.venv\\Scripts\\python.exe'
$siteRoot = {_ps_literal(str(profile['site_root']))}
$outputRoot = {_ps_literal(str(profile['output_root']))}
$siteCode = {_ps_literal(site_code)}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {{
  throw "Repository Python executable is missing: $python"
}}
if (-not (Test-Path -LiteralPath $siteRoot -PathType Container)) {{
  throw "Local site directory is missing: $siteRoot"
}}

$datePrefix = Get-Date -Format 'yyyy.MM.dd'
$baseName = "${{datePrefix}}_${{siteCode}}_timing_Gantt"
$runDir = Join-Path $outputRoot $baseName
$suffix = 2
while (Test-Path -LiteralPath $runDir) {{
  $runDir = Join-Path $outputRoot "${{baseName}}_${{suffix}}"
  $suffix += 1
}}

$arguments = @(
{argument_lines}
  '--run-dir'
  $runDir
)

Set-Location -LiteralPath $repoRoot
& $python @arguments
$analysisExitCode = $LASTEXITCODE
$expectedCsv = Join-Path $runDir {_ps_literal(f'Report\\{site_slug}_timeline_analysis.csv')}

if ($analysisExitCode -eq 0 -and -not (Test-Path -LiteralPath $expectedCsv -PathType Leaf)) {{
  Write-Error "Timeline Analysis reported success but the expected CSV is missing: $expectedCsv"
  exit 2
}}
if ($analysisExitCode -eq 0) {{
  Write-Host "Timeline Analysis CSV: $expectedCsv"
}}
exit $analysisExitCode
"""


def _atomic_write(path: Path, content: str, *, overwrite: bool) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise OnboardingError(f"Refusing to overwrite existing file without confirmation: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_profile_and_runner(
    *,
    profile: dict[str, object],
    profile_root: Path,
    overwrite: bool,
) -> tuple[Path, Path]:
    """Atomically save a profile and generated runner outside the repository."""
    profile_root = profile_root.expanduser().resolve()
    repository_root = Path(str(profile["repository_root"])).resolve()
    try:
        profile_root.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise OnboardingError(
            f"Onboarding profiles and runners must remain outside the repository: {profile_root}"
        )
    site_slug = _site_slug(str(profile["site_code"]))
    profile_path = profile_root / "profiles" / f"{site_slug}.json"
    runner_path = profile_root / "runners" / f"run_{site_slug}.ps1"
    if not overwrite:
        existing = [path for path in (profile_path, runner_path) if path.exists()]
        if existing:
            raise OnboardingError(
                "Refusing to overwrite existing onboarding files without confirmation: "
                + ", ".join(str(path) for path in existing)
            )
    _atomic_write(
        profile_path,
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        overwrite=overwrite,
    )
    _atomic_write(runner_path, render_runner(profile), overwrite=overwrite)
    return profile_path, runner_path


def _prompt(input_fn: Callable[[str], str], message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input_fn(f"{message}{suffix}: ").strip()
    return value or (default or "")


def _confirm(input_fn: Callable[[str], str], message: str, *, default: bool = False) -> bool:
    label = "Y/n" if default else "y/N"
    value = input_fn(f"{message} [{label}]: ").strip().casefold()
    if not value:
        return default
    return value in {"y", "yes"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guide a Windows user through local Timeline Analysis setup and runner generation."
    )
    parser.add_argument("--site", help="Three-digit site ID, for example 122.")
    parser.add_argument("--local-root", help="Parent containing Teams-synced site directories.")
    parser.add_argument("--selection", choices=("all", "manifest"), default=None)
    parser.add_argument("--case-list", help="Explicit newline-delimited case-list manifest.")
    parser.add_argument("--rollup", help="Optional existing roll-up comparator CSV.")
    parser.add_argument("--cache-database", help="Optional existing read-only analytical store.")
    parser.add_argument("--profile-root", help="Override the per-user profile and runner directory.")
    parser.add_argument("--output-root", help="Override generated run output root.")
    parser.add_argument("--full-tests", action="store_true", help="Run the full test suite during checks.")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--run-now", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
) -> int:
    """Run the guided onboarding workflow and optionally execute its runner."""
    args = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        LOGGER.info("Validating repository environment and command-line interfaces.")
        validate_windows_runtime()
        run_environment_checks(
            repository_root,
            include_full_tests=args.full_tests,
            command_runner=command_runner,
        )
        user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        local_root_value = args.local_root
        site_value = args.site
        selection_mode = args.selection
        if not args.non_interactive:
            site_value = site_value or _prompt(input_fn, "Three-digit site ID")
            local_root_value = local_root_value or _prompt(
                input_fn,
                "Local Teams parent",
                str(user_profile / "Profound Medical"),
            )
            selection_mode = selection_mode or _prompt(
                input_fn,
                "Analyze all canonical cases or a manifest (all/manifest)",
                "all",
            ).casefold()
        if not site_value:
            raise OnboardingError("--site is required in non-interactive mode.")
        site_id = normalize_site_id(site_value)
        local_root = Path(local_root_value or (user_profile / "Profound Medical"))
        selection_mode = selection_mode or "all"
        inventory = inventory_local_site(
            repository_root=repository_root,
            local_root=local_root,
            site_id=site_id,
        )
        LOGGER.info(
            "Discovered %d canonical cases for %s; %d have one usable database candidate.",
            len(inventory.case_ids),
            inventory.site_code,
            len(inventory.usable_case_ids),
        )

        case_list_path = Path(args.case_list).expanduser().resolve() if args.case_list else None
        if selection_mode == "manifest" and case_list_path is None and not args.non_interactive:
            case_list_path = Path(_prompt(input_fn, "Case-list manifest path")).expanduser().resolve()
        if selection_mode == "manifest":
            if case_list_path is None:
                raise OnboardingError("--case-list is required for manifest selection.")
            selected_ids = read_case_manifest(case_list_path, inventory)
        elif selection_mode == "all":
            selected_ids = inventory.case_ids
        else:
            raise OnboardingError("Selection must be 'all' or 'manifest'.")

        rollup_value = args.rollup
        cache_value = args.cache_database
        if not args.non_interactive:
            rollup_value = rollup_value or _prompt(input_fn, "Optional roll-up CSV (blank for none)")
            cache_value = cache_value or _prompt(
                input_fn,
                "Optional read-only cache database (blank keeps cache off)",
            )
        rollup_path = Path(rollup_value).expanduser().resolve() if rollup_value else None
        cache_database = Path(cache_value).expanduser().resolve() if cache_value else None
        output_root = Path(args.output_root).expanduser().resolve() if args.output_root else (
            repository_root / "outputs" / "timing_gantt"
        ).resolve()
        local_app_data = os.environ.get("LOCALAPPDATA")
        if args.profile_root:
            profile_root = Path(args.profile_root)
        elif local_app_data:
            profile_root = Path(local_app_data) / DEFAULT_PROFILE_DIRECTORY
        else:
            raise OnboardingError("LOCALAPPDATA is unavailable; provide --profile-root explicitly.")

        profile = build_profile(
            repository_root=repository_root,
            inventory=inventory,
            selection_mode=selection_mode,
            case_list_path=case_list_path,
            selected_case_count=len(selected_ids),
            rollup_path=rollup_path,
            cache_database=cache_database,
            output_root=output_root,
        )
        print(
            f"Preview: site={inventory.site_code}; canonical={len(inventory.case_ids)}; "
            f"usable_database_candidates={len(inventory.usable_case_ids)}; "
            f"quarantined={len(inventory.case_issues)}; selected={len(selected_ids)}; "
            f"cache={dict(profile['cache'])['mode']}"
        )
        if inventory.case_issues:
            LOGGER.warning("%d case(s) require separate availability/acquisition review.", len(inventory.case_issues))
            print(
                "Some local cases do not have one unambiguous database candidate. "
                "Review scripts/check_site_availability.py and the separate credential/acquisition "
                "workflow before expecting a complete publication; onboarding will not acquire files."
            )
        if not args.non_interactive and not _confirm(input_fn, "Save this profile and runner?"):
            print("Initialization cancelled; no profile or runner was written.")
            return 1

        overwrite = args.overwrite
        expected_profile = profile_root / "profiles" / f"{_site_slug(inventory.site_code)}.json"
        expected_runner = profile_root / "runners" / f"run_{_site_slug(inventory.site_code)}.ps1"
        if not overwrite and (expected_profile.exists() or expected_runner.exists()) and not args.non_interactive:
            overwrite = _confirm(input_fn, "Existing profile or runner found. Overwrite both?")
        profile_path, runner_path = save_profile_and_runner(
            profile=profile,
            profile_root=profile_root,
            overwrite=overwrite,
        )
        LOGGER.info("Saved non-secret per-user profile and runner.")
        print(f"Profile: {profile_path}")
        print(f"Runner: {runner_path}")
        print(
            f"Expected CSV: <fresh-run-dir>\\Report\\{_site_slug(inventory.site_code)}_timeline_analysis.csv"
        )

        run_now = args.run_now
        if not args.non_interactive and not run_now:
            run_now = _confirm(input_fn, "Run Timeline Analysis now?")
        if run_now:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(runner_path),
                ],
                check=False,
            )
            return int(completed.returncode)
        return 0
    except OnboardingError as exc:
        LOGGER.error("Initialization failed: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
