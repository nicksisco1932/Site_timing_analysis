<!--
Project: Site Timing Analysis
File: docs/TODO_COMPLETION_AUDIT_2026-08-11.md
Primary author: Nicholas J. Sisco, Ph.D.
Organization: Profound Medical, LLC
Created: 2026-08-11
Purpose: Maps the final guided-handoff and profiling requirements to acceptance evidence.

Provenance: Original implementation or material contribution by
Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.

Rights status: Proprietary / internal use unless otherwise specified
by Profound Medical, LLC.
-->

# TODO Completion Audit

## TODO #7 — Guided handoff and pipeline initialization

| Requirement | Authoritative evidence | Result |
| --- | --- | --- |
| Windows/PowerShell and Python 3.12+ validation without installing system Python or Git | `initialize_timeline_analysis.ps1`; isolated missing-runtime and real Python 3.13 `.venv` tests | Pass |
| Confirmed `.venv`, runtime, development, and editable-project setup | Disposable local clone installed all declared dependencies into a new `.venv` | Pass |
| `pip check`, operational CLI help, and optional full tests | `run_environment_checks`; clean-clone pipeline preflight passed 229 tests | Pass |
| Exact three-digit site and one immediate Teams-synced directory | `resolve_local_site`; missing/ambiguous/canonical tests | Pass |
| Read-only canonical case/database inventory with no guessing | `inventory_local_site`; usable and ambiguous-candidate quarantine tests | Pass |
| All-versus-manifest selection and preview | Profile/runner contract tests and explicit strict/subset exporter tests | Pass |
| Optional roll-up and explicit read-only cache; no store writes | Generated-runner argument test; no store command exists in onboarding | Pass |
| No passwords, Sync URLs, tokens, decryption keys, or copied case IDs in profiles | Recursive profile safety validation plus serialized-profile tests | Pass |
| Versioned profile and quoted runner outside Git | External-path enforcement, PowerShell parser test, overwrite test | Pass |
| Collision-safe run directory, exact exit propagation, and public CSV path | Disposable runner published base and `_2` runs; both CSVs had one row, 20 columns, and identical SHA-256 | Pass |
| Acquisition remains separate | Onboarding only prints availability/acquisition guidance for missing candidates | Pass |

## TODO #8 — Profile and optimize the pipeline

| Requirement | Authoritative evidence | Result |
| --- | --- | --- |
| Live preflight remains default; reuse is explicit | Exporter CLI defaults and argument-validation tests | Pass |
| Exact repository, Git commit/dirty contents, interpreter, dependency, and test-command identity | `preflight_baseline.py`; independent mismatch tests | Pass |
| Fresh, previously passing snapshots only | Stale and failed-gate unit tests plus live stale-CLI exit `2` | Pass |
| Complete attributable evidence retained per run | Reuse report contains original gates, source snapshot SHA-256, age, and identity checks | Pass |
| Windows encoding cannot weaken dirty-diff identity | Raw stdout/stderr hashes and invalid-code-page-byte regression test | Pass |
| Three live and three reuse benchmarks on one fixed four-case manifest | Final benchmark: live median `20.970s`; reuse median `4.188s` (`-80.03%`) | Pass |
| Timing reconciliation remains complete | Minimum coverage `99.9861%`; maximum unaccounted time `0.000591s`; every run `PASS` | Pass |
| Required outputs remain byte-identical | Zero mismatches across public CSV, 12 event CSVs, four interval CSVs, two plots, and reconciliation CSV | Pass |
| CPU, database, and filesystem attribution is distinguishable | Performance reports and `PREFLIGHT_BASELINE_BENCHMARK_2026-08-11.md` | Pass |
| Generated evidence stays outside Git | Snapshot, fresh-clone acceptance, runs, and benchmark outputs reside under Windows temp paths | Pass |

## Final repository gates

- Final external snapshot suite: `230 passed`.
- Focused onboarding/preflight suite: `30 passed`.
- Operational CLI help checks: pass.
- `pip check`: pass.
- `git diff --check`: pass.
- No database, ZIP, workbook, generated CSV, analytical store, profile, runner,
  or benchmark output appears in the repository change set.
