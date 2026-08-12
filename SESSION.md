# SESSION.md

## Project

Site Timing Analysis: a staged, provenance-preserving Python pipeline for
clinical operational timing, validated wide exports, read-only acquisition
preflight, guided Windows handoff, and historical SQL-backed analysis.

## Current Objective

The numbered repository TODO is complete through #8. Current work should focus
on review and acceptance of the guided initializer and exact reusable preflight
slice. No additional optimization is selected.

## Governing Files

1. `AGENTS.md`
2. `SOP.md`
3. `ARCHITECTURE.md`
4. `SESSION.md`
5. `TODO.md`

Completion evidence is in `docs/TODO_HISTORY.md`; detailed preflight benchmark
evidence is in `docs/PREFLIGHT_BASELINE_BENCHMARK_2026-08-11.md`, and the final
requirement matrix is in `docs/TODO_COMPLETION_AUDIT_2026-08-11.md`. Historical
session detail remains in `Legacy/SESSION_HISTORY.md`.

## Implemented Baseline

- Deterministic discovery, explicit selection, ambiguity-safe read-only SQLite
  ingestion, normalization, enrichment, state labeling, unrounded intervals,
  plotting, reconciliation, and gated 20-column publication.
- Technical artifacts stay under `Backend/`; public CSV and operator report
  stay under `Report/`. Public endpoints are clock-only while full ISO endpoint
  provenance remains in reports and the analytical store.
- Read-only Sync/Teams availability checks and explicit single-, five-, and
  bulk-case acquisition remain separate from analysis and onboarding.
- The schema-v2 cross-site store supports exact opt-in read-only cache reuse and
  SQL wide/long/comparison/summary reporting. Imports remain explicit writes.
- `scripts/initialize_timeline_analysis.ps1` bootstraps the Windows repository
  environment after confirmation and invokes a Python wizard. The wizard
  resolves one local site, inventories candidates read-only, previews all or
  manifest selection, and writes secret-free profiles/runners under Local
  AppData. Acquisition and analytical-store writes are excluded.
- Generated runners use the repository `.venv`, explicit site root/prefix,
  collision-safe dated run directories, exact exit propagation, and public CSV
  verification. Explicit subset support does not change the exporter's strict
  default or ASUI compatibility allowlist.
- Live preflight remains the default. Explicit `--baseline-mode reuse` accepts
  only a fresh external snapshot with successful prior gates and exact Git
  commit/dirty contents, interpreter path/version/binary, dependencies, and
  test-command contract. Reuse evidence is preserved per run.

## Durable Store and Governance

The sole operational store is:

```text
C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite
```

It uses `DELETE` journaling, `synchronous=FULL`, bounded busy waiting, and one
workstation writer. Other synchronized copies remain closed or read-only.
Clinical databases, stores, exports, run folders, onboarding profiles/runners,
baseline snapshots, and profiling artifacts remain outside Git. Detailed state
intervals are analytical truth; the 2026.03.19 ASUI roll-up remains an unchanged
validation comparator.

## Acceptance and Profiling

- Focused onboarding tests: `17 passed`; focused reusable-preflight tests:
  `13 passed`.
- Final external snapshot gate: `230 passed`; `pip check`, required CLI help
  checks, and `git diff --check` passed.
- Fresh-user acceptance used a disposable local clone with no `.venv`, detected
  Python 3.13 as satisfying the 3.12+ contract, installed all declared
  dependencies, and passed all 229 tests present in its clean-clone snapshot.
  An invented
  one-case database published one-row, 20-column CSVs on two runner executions;
  the second used the `_2` collision-safe directory and both CSV hashes matched.
- Three live and three verified-reuse benchmarks used UCLA cases `008_01-201`,
  `008_01-202`, `008_01-206`, and `008_01-207`. Median wall time fell from
  `20.970s` to `4.188s` (`-80.03%`). Median CPU changed `-17.35%`; non-CPU wall
  proxy changed `-90.84%`.
- Timing coverage remained above `99.986%`. The public CSV, 12 event CSVs, four
  interval CSVs, two plots, and reconciliation CSV were byte-identical across
  all six benchmark runs.

## Decisions and Deferred Work

- Default live preflight, source identity checks, publication gates, plots, and
  intermediate artifact contracts remain unchanged.
- Plot generation is now the largest measured post-reuse stage, but plot
  suppression remains diagnostic-only because plots are required artifacts.
  Do not optimize it without a new explicit TODO and byte-parity criteria.
- Acquisition-assisted onboarding may be considered later as a separate mode;
  do not add credential handling or automatic acquisition to the first slice.
- Formal historical R parity, `.xlsx` timing-log enrichment, `local2.db`, and
  eventual large-module splitting remain separate future work.

## Resume Instructions

1. Read the governing files in order.
2. Treat TODO #1 through #8 as complete and preserve their interface contracts.
3. Review the current uncommitted implementation and validation evidence before
   adding new scope.
4. Use explicit repository `.venv` executables for every Python command.
5. Keep generated and clinical-derived artifacts outside Git.
