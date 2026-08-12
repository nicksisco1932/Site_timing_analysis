# Project: Site Timing Analysis
# File: testing/tests/test_onboarding.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Tests guided Windows onboarding, safe profile persistence, and runner generation.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess
import shutil
import tempfile
from types import SimpleNamespace

import pytest

from site_timing_analysis import onboarding
from site_timing_analysis.onboarding import (
    OnboardingError,
    SiteInventory,
    build_profile,
    environment_creation_plan,
    inventory_local_site,
    read_case_manifest,
    render_runner,
    resolve_local_site,
    run_environment_checks,
    save_profile_and_runner,
    validate_profile_safety,
    validate_windows_runtime,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _site_tree(tmp_path: Path, *, site_code: str = "TEST_122") -> tuple[Path, Path]:
    local_root = tmp_path / "Profound Medical"
    site_root = local_root / f"Clinical Science Team - {site_code}"
    for case_id in ("122_01-001", "122_01-002"):
        case_dir = site_root / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "local.db").write_bytes(b"synthetic-read-only-candidate")
    (site_root / "STA_legacy").mkdir()
    return local_root, site_root


def _inventory(tmp_path: Path) -> SiteInventory:
    local_root, _ = _site_tree(tmp_path)
    return inventory_local_site(
        repository_root=REPOSITORY_ROOT,
        local_root=local_root,
        site_id="122",
    )


def _profile(tmp_path: Path, *, selection_mode: str = "all", case_list: Path | None = None):
    inventory = _inventory(tmp_path)
    return build_profile(
        repository_root=REPOSITORY_ROOT,
        inventory=inventory,
        selection_mode=selection_mode,
        case_list_path=case_list,
        selected_case_count=1 if case_list else len(inventory.case_ids),
        rollup_path=None,
        cache_database=None,
        output_root=tmp_path / "outputs",
    )


def test_runtime_validation_rejects_non_windows_and_old_python() -> None:
    with pytest.raises(OnboardingError, match="requires Windows"):
        validate_windows_runtime(platform_name="posix", version_info=(3, 12, 0))
    with pytest.raises(OnboardingError, match="Python 3.12"):
        validate_windows_runtime(platform_name="nt", version_info=(3, 11, 9))
    validate_windows_runtime(platform_name="nt", version_info=(3, 12, 0))


def test_environment_creation_plan_detects_missing_and_present_python(tmp_path: Path) -> None:
    missing = environment_creation_plan(tmp_path)
    assert missing["creation_required"] is True
    python_executable = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_bytes(b"")
    present = environment_creation_plan(tmp_path)
    assert present["creation_required"] is False
    assert present["python_exists"] is True


def test_environment_check_reports_dependency_failure() -> None:
    def fail_pip(command, *, cwd):
        assert Path(cwd) == REPOSITORY_ROOT
        return SimpleNamespace(returncode=1, stdout="", stderr="broken dependency")

    with pytest.raises(OnboardingError, match="broken dependency"):
        run_environment_checks(
            REPOSITORY_ROOT,
            include_full_tests=False,
            command_runner=fail_pip,
        )


def test_environment_checks_cover_operational_clis_and_optional_full_suite() -> None:
    commands: list[tuple[str, ...]] = []

    def pass_all(command, *, cwd):
        assert Path(cwd) == REPOSITORY_ROOT
        commands.append(tuple(command))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    results = run_environment_checks(
        REPOSITORY_ROOT,
        include_full_tests=True,
        command_runner=pass_all,
    )
    names = {result.name for result in results}
    assert names == {
        "pip_check",
        "staged_pipeline_help",
        "timeline_analysis_help",
        "deliverable_builder_help",
        "timeline_store_help",
        "full_test_suite",
    }
    assert any("site_timing_analysis.first_slice_cli" in command for command in commands)
    assert any(
        any(part.endswith("build_timing_gantt_deliverables.py") for part in command)
        for command in commands
    )
    assert any("pytest" in command for command in commands)


def test_resolve_local_site_reports_missing_and_ambiguous_directories(tmp_path: Path) -> None:
    local_root = tmp_path / "Profound Medical"
    local_root.mkdir()
    with pytest.raises(OnboardingError, match="Sync the site directory ending in _122"):
        resolve_local_site(local_root, "122")
    (local_root / "Clinical Science Team - A_122").mkdir()
    (local_root / "Clinical Science Team - B_122").mkdir()
    with pytest.raises(OnboardingError, match="ambiguous"):
        resolve_local_site(local_root, "122")


def test_inventory_discovers_only_canonical_cases_and_database_candidates(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path)
    assert inventory.site_code == "TEST_122"
    assert inventory.canonical_prefix == "122_"
    assert inventory.case_ids == ("122_01-001", "122_01-002")
    assert inventory.usable_case_ids == inventory.case_ids
    assert inventory.case_issues == ()


def test_inventory_quarantines_ambiguous_database_candidates(tmp_path: Path) -> None:
    local_root, site_root = _site_tree(tmp_path)
    nested = site_root / "122_01-001" / "_alternate"
    nested.mkdir()
    (nested / "local.db").write_bytes(b"second-candidate")
    inventory = inventory_local_site(
        repository_root=REPOSITORY_ROOT,
        local_root=local_root,
        site_id="122",
    )
    assert "122_01-001" not in inventory.usable_case_ids
    assert any(
        issue["case_id"] == "122_01-001" and issue["status"] == "quarantined"
        for issue in inventory.case_issues
    )


def test_all_and_manifest_selection_are_distinct(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path)
    manifest = tmp_path / "selected.txt"
    manifest.write_text("122_01-002\n", encoding="utf-8")
    selected = read_case_manifest(manifest, inventory)
    assert selected == ("122_01-002",)

    all_profile = build_profile(
        repository_root=REPOSITORY_ROOT,
        inventory=inventory,
        selection_mode="all",
        case_list_path=None,
        selected_case_count=2,
        rollup_path=None,
        cache_database=None,
        output_root=tmp_path / "outputs",
    )
    manifest_profile = build_profile(
        repository_root=REPOSITORY_ROOT,
        inventory=inventory,
        selection_mode="manifest",
        case_list_path=manifest,
        selected_case_count=1,
        rollup_path=None,
        cache_database=None,
        output_root=tmp_path / "outputs",
    )
    assert "--select-all-canonical" in render_runner(all_profile)
    manifest_runner = render_runner(manifest_profile)
    assert "--case-list" in manifest_runner
    assert "--allow-unselected-canonical" in manifest_runner


def test_validated_exporter_subset_mode_is_explicit_and_default_remains_strict(tmp_path: Path) -> None:
    script_path = REPOSITORY_ROOT / "scripts" / "run_asui_122_timeline_analysis.py"
    spec = importlib.util.spec_from_file_location("onboarding_exporter_contract", script_path)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)

    site_root = tmp_path / "Clinical Science Team - TEST_122"
    for name in ("122_01-001", "122_01-002", "STA_legacy"):
        (site_root / name).mkdir(parents=True)
    manifest = tmp_path / "selected.txt"
    manifest.write_text("122_01-001\n", encoding="utf-8")

    strict = exporter._discover_and_select(
        site_root,
        tmp_path / "strict",
        site_code="TEST_122",
        case_list_path=manifest,
        canonical_prefix="122_",
    )
    assert strict["unexpected_canonical_case_ids"] == ["122_01-002"]

    subset = exporter._discover_and_select(
        site_root,
        tmp_path / "subset",
        site_code="TEST_122",
        case_list_path=manifest,
        canonical_prefix="122_",
        allow_unselected_canonical=True,
    )
    assert subset["unexpected_canonical_case_ids"] == []
    assert subset["unselected_canonical_case_ids"] == ["122_01-002"]
    assert subset["category_counts"]["excluded_unselected_canonical"] == 1

    all_cases = exporter._discover_and_select(
        site_root,
        tmp_path / "all",
        site_code="ASUI_122",
        case_list_path=None,
        canonical_prefix="122_",
        select_all_canonical=True,
    )
    assert all_cases["selected_case_ids"] == ["122_01-001", "122_01-002"]


def test_runner_quotes_apostrophes_and_defaults_cache_off(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["site_root"] = r"C:\Users\O'Brien\Profound Medical\Clinical Science Team - TEST_122"
    runner = render_runner(profile)
    assert "O''Brien" in runner
    assert "--cache-mode" not in runner
    assert ".venv\\Scripts\\python.exe" in runner
    assert "while (Test-Path -LiteralPath $runDir)" in runner
    assert "Report\\test_122_timeline_analysis.csv" in runner


def test_runner_includes_only_explicit_existing_rollup_and_read_only_cache(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path)
    rollup = tmp_path / "rollup.csv"
    cache = tmp_path / "timeline.sqlite"
    rollup.write_text("Site,PtId\n", encoding="utf-8")
    cache.write_bytes(b"synthetic-path-contract")
    profile = build_profile(
        repository_root=REPOSITORY_ROOT,
        inventory=inventory,
        selection_mode="all",
        case_list_path=None,
        selected_case_count=len(inventory.case_ids),
        rollup_path=rollup,
        cache_database=cache,
        output_root=tmp_path / "outputs",
    )
    runner = render_runner(profile)
    assert "--rollup" in runner
    assert str(rollup.resolve()) in runner
    assert "--cache-mode" in runner and "read-only" in runner
    assert str(cache.resolve()) in runner
    assert "timeline_store.py" not in runner


def test_profile_rejects_secrets_urls_and_unconfirmed_overwrite(tmp_path: Path) -> None:
    with pytest.raises(OnboardingError, match="forbidden secret field"):
        validate_profile_safety({"password": "do-not-store"})
    with pytest.raises(OnboardingError, match="forbidden remote URL"):
        validate_profile_safety({"endpoint": "https://example.invalid/share"})

    profile = _profile(tmp_path / "site")
    with tempfile.TemporaryDirectory(prefix="site-timing-profile-") as external_text:
        profile_root = Path(external_text)
        profile_path, runner_path = save_profile_and_runner(
            profile=profile,
            profile_root=profile_root,
            overwrite=False,
        )
        saved = json.loads(profile_path.read_text(encoding="utf-8"))
        serialized = json.dumps(saved).casefold()
        assert "password" not in serialized
        assert "sync_url" not in serialized
        assert "122_01-001" not in serialized
        assert runner_path.is_file()
        with pytest.raises(OnboardingError, match="Refusing to overwrite"):
            save_profile_and_runner(profile=profile, profile_root=profile_root, overwrite=False)
    with pytest.raises(OnboardingError, match="outside the repository"):
        save_profile_and_runner(
            profile=profile,
            profile_root=REPOSITORY_ROOT / ".forbidden_onboarding_profile",
            overwrite=False,
        )


def test_main_propagates_generated_runner_exit_code(tmp_path: Path, monkeypatch) -> None:
    local_root, _ = _site_tree(tmp_path)

    def pass_check(command, *, cwd):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    def runner_exit(command, *, check):
        assert command[:4] == [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
        ]
        assert check is False
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(onboarding.subprocess, "run", runner_exit)
    with tempfile.TemporaryDirectory(prefix="site-timing-main-") as external_text:
        profile_root = Path(external_text)
        exit_code = onboarding.main(
            [
                "--site",
                "122",
                "--local-root",
                str(local_root),
                "--selection",
                "all",
                "--profile-root",
                str(profile_root),
                "--output-root",
                str(tmp_path / "outputs"),
                "--non-interactive",
                "--run-now",
            ],
            command_runner=pass_check,
        )
        assert exit_code == 7
        assert (profile_root / "profiles" / "test_122.json").is_file()
        assert (profile_root / "runners" / "run_test_122.ps1").is_file()


def test_powershell_bootstrap_parses_without_execution() -> None:
    script = REPOSITORY_ROOT / "scripts" / "initialize_timeline_analysis.ps1"
    command = (
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$null, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_powershell_bootstrap_reports_missing_system_python(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "scripts" / "initialize_timeline_analysis.ps1"
    temporary_scripts = tmp_path / "repo" / "scripts"
    temporary_scripts.mkdir(parents=True)
    copied = temporary_scripts / source.name
    shutil.copyfile(source, copied)
    environment = dict(__import__("os").environ)
    environment["PATH"] = ""
    completed = subprocess.run(
        [
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(copied),
            "-Yes",
            "-SkipDependencyInstall",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode != 0
    assert "Python 3.12+ was not found" in (completed.stdout + completed.stderr)


def test_powershell_bootstrap_creates_venv_with_newer_supported_python(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "scripts" / "initialize_timeline_analysis.ps1"
    temporary_repository = tmp_path / "fresh-repository"
    temporary_scripts = temporary_repository / "scripts"
    temporary_scripts.mkdir(parents=True)
    copied = temporary_scripts / source.name
    shutil.copyfile(source, copied)
    (temporary_scripts / "initialize_timeline_analysis.py").write_text(
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(copied),
            "-Yes",
            "-SkipDependencyInstall",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    created_python = temporary_repository / ".venv" / "Scripts" / "python.exe"
    assert created_python.is_file()
    version_check = subprocess.run(
        [
            str(created_python),
            "-c",
            "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 2)",
        ],
        check=False,
    )
    assert version_check.returncode == 0


def test_generated_runner_parses_without_execution(tmp_path: Path) -> None:
    runner_path = tmp_path / "generated.ps1"
    runner_path.write_text(render_runner(_profile(tmp_path / "site")), encoding="utf-8")
    command = (
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{runner_path}', [ref]$null, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
