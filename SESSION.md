# SESSION.md

## Project

Site Timing Analysis: a staged, provenance-preserving Python pipeline for
clinical operational timing, validated wide exports, acquisition preflight, and
historical SQL-backed analysis.

## Current Objective

TODO #6 is complete. Schema-v2 exact read-only cache reuse and SQL-native
reporting passed live ASUI and UCLA acceptance. TODO #7 is now active: design
and validate a reusable pre-execution test snapshot because repeated full-suite
preflight is the measured runtime bottleneck. No optimization has been
implemented yet.

## Governing Files

1. `AGENTS.md`
2. `SOP.md`
3. `ARCHITECTURE.md`
4. `SESSION.md`
5. `TODO.md`

Completed TODO #1–#6 evidence is in `docs/TODO_HISTORY.md`. Historical session
detail remains in `Legacy/SESSION_HISTORY.md`.

## Implemented Baseline

- Deterministic case discovery, explicit selection, database-candidate
  resolution, read-only SQLite ingestion, normalization, enrichment, state
  labeling, interval construction, plotting, validation, reconciliation, and
  publication gating.
- Compact run layout: technical artifacts under `Backend/` and the public
  20-column CSV plus operator report under `Report/`.
- Clock-only public `starttime`/`endtime`; full ISO endpoints and provenance
  remain in technical reports and the analytical store.
- Opt-in performance profiling with nested exclusive timings, greater than
  99.99% wall-time reconciliation, per-case metrics, and non-duplicated artifact
  ownership.
- Read-only Sync/Teams site availability checks and explicit single-, five-,
  and bulk-case `local.db` acquisition workflows. Acquisition backend data stays
  outside sanitized site destinations; `applog` behavior remains unchanged.
- Legacy wrappers and reference material remain available for parity work.

## Durable Store and Cache

The sole operational store is:

```text
C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite
```

- Schema v1 stores immutable source/parser/configuration history, runs, case
  analyses, full endpoint provenance, canonical labeled events, unrounded
  detailed intervals, wide snapshots, validation, and reconciliation.
- Schema v2 records exact clinical-source/ZIP-member and timing-log dependencies
  (including explicit absence), parser/configuration/cache-contract
  fingerprints, and case-result materialization metadata.
- `scripts/timeline_store.py` provides explicit `init`, `upgrade`, `import-run`,
  `export-wide`, `export-long`, `compare-runs`, `summarize-runs`, and
  `list-runs` commands.
- `scripts/run_timeline_analysis.py --cache-mode read-only --database <path>` is
  opt-in. Default behavior is `off`; imports remain a separate explicit write.
- Cache lookup occurs only after normal source resolution and validation. Exact
  hits use the standard artifact writers and all existing validation,
  reconciliation, plot, exit-code, and publication paths. Invalid case entries
  fall back to source parsing; an invalid store aborts cache-enabled execution.
- Version-1 analyses remain valid history but are cache-ineligible.
- The current live store is schema 2 with integrity `ok`, zero foreign-key
  issues, 7 runs, 50 run cases, 34 analyses, 25 cache entries, 4,700 canonical
  events, 4,700 intervals, and 180 reconciliation rows.

The store uses `DELETE` journaling, `synchronous=FULL`, bounded busy waiting,
and immediate write transactions. This workstation is the only writer. Keep the
store pinned locally; synchronized copies on other computers remain closed or
read-only. Stop OneDrive and close all SQLite connections for schema copy-up or
relocation.

## Live Acceptance

- Schema-v2 copy-up preserved deterministic legacy content, migration checksums,
  integrity, foreign keys, and the canonical ASUI export. OneDrive resumed with
  no WAL/SHM or migration sidecars.
- ASUI: a fresh nine-case uncached run and a 9/9 exact-hit run both published.
  The public CSV, all 27 event CSVs, 9 interval CSVs, plots, and 45-row
  reconciliation artifact were byte-identical. The run retained 1,226 events
  and 1,226 intervals.
- UCLA: a fresh five-case uncached run and a 5/5 exact-hit run both published.
  The public CSV, all 15 event CSVs, 5 interval CSVs, plots, and empty
  no-comparator reconciliation artifact were byte-identical. The run retained
  673 events and 673 intervals.
- All 14 clinical source files retained identical size, modification time, and
  SHA-256 before and after acceptance.
- SQL long export produced 135 ASUI case/state rows; ASUI seed-versus-hit
  comparison produced 135 matched rows with zero difference; the ASUI/UCLA
  summary produced 30 site/state rows. SQL-wide exports matched both pipeline
  CSVs cell-for-cell.
- Importing cache-hit runs reused all 14 analyses and inserted zero duplicate
  events or intervals.

## Profiling Result

Three repetitions per condition used the same UCLA cases `008_01-201`,
`008_01-202`, `008_01-206`, and `008_01-207`:

| Condition | Median wall | Change vs disabled |
| --- | ---: | ---: |
| Cache disabled | 65.601s | baseline |
| Two hits / two misses | 83.110s | +26.69% |
| Four hits | 126.644s | +93.05% |

All runs reconciled at least 99.9989% of wall time and produced the same public
CSV hash plus byte-identical event, interval, and plot artifacts. The mandatory
repository-test preflight consumed about 92% of median wall time and varied
substantially by condition. Exact hashing/store lookup also slightly exceeded
direct parse-stage time for these small local databases. See
`docs/CACHE_BENCHMARK_2026-08-11.md` for attribution and caveats.

## Current Decisions and Data Governance

- Preserve source databases read-only and detailed intervals as analytical
  truth. Wide snapshots remain parity evidence only.
- Preserve selection semantics, identity checks, publication gates, public CSV
  fields, plots, and intermediate diagnostic artifacts.
- Keep cache reuse read-only, explicit, and exact. Never use size or modified
  time instead of SHA-256, and never auto-write the OneDrive store.
- Keep clinical databases, analytical stores, acquisition outputs, generated
  run folders, profiling artifacts, and SQL exports outside Git.
- Keep raw workbooks outside the repository. Integration fixtures remain
  deterministic and synthetic.
- Preserve the 2026.03.19 ASUI roll-up as an unchanged validation comparator,
  never as authoritative detailed timing truth.

## Validation Status

- Full repository suite: `200 passed` in `54.10s` with the repo-local `.venv`.
- Focused analytical-store/cache suite: `29 passed`.
- Live store: schema 2, integrity `ok`, zero foreign-key violations, OneDrive
  running, locally pinned, `DELETE` journaling, and no persistent WAL/SHM or
  migration files.
- Core pipeline/store/report CLI help checks pass; `pip check` reports no broken
  requirements and `git diff --check` reports no whitespace errors.
- The 2026.03.19 ASUI roll-up remains unchanged at SHA-256
  `81E3C37C1F05A3999974D381DE71DF32C28FC4F63B630DEA1DE9EC79EC64B546`.

## Known and Deferred Work

- TODO #7: design a verified reusable baseline snapshot bound to repository,
  interpreter, dependency, test-command, result, and freshness fingerprints.
  Default live validation remains unchanged until parity is proven.
- Rebenchmark before/after three times on the fixed four-case manifest. Require
  byte-identical public, event, interval, plot, and reconciliation artifacts.
- Source-hash or plot optimization is deferred until post-preflight profiling
  identifies a repeatable bottleneck.
- Formal historical R parity, `.xlsx` timing-log enrichment, `local2.db`, and
  eventual large-module splitting remain separate deferred work.

## Resume Instructions

1. Read the governing files in order.
2. Treat TODO #6 as complete and preserve schema-v2 cache/store contracts.
3. Continue only TODO #7’s verified-baseline design; do not weaken default
   preflight, source hashing, artifacts, or publication behavior.
4. Use explicit repo-local `.venv` executables for all Python commands.
5. Keep generated and clinical-derived artifacts outside Git.
