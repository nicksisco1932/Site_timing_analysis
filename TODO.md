# TODO

## Current checkpoint

- The reviewed OneDrive-store relocation is published on
  `feature/workflow-analytics` at `4b7d8cc` (2026-08-11).
- The sole operational analytical store is the locally pinned
  `C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite`.
- Detailed evidence for completed TODOs #1 through #5 is archived in
  [`docs/TODO_HISTORY.md`](docs/TODO_HISTORY.md).
- Clinical databases, analytical stores, acquired data, generated outputs, and
  profiling artifacts remain outside Git.

## Completed work

| Item | Status | Outcome |
| --- | --- | --- |
| #1 GitHub housekeeping | Completed 2026-08-10 | Repository scope, data hygiene, tests, documentation, and reviewer summary completed. |
| #2 Single-case acquisition | Completed 2026-08-11 | One explicit Sync.com case acquired and independently validated read-only. |
| #3 Five-case acquisition | Completed 2026-08-11 | Five explicit cases acquired with no unresolved ambiguity or validation failure. |
| #4 Bulk acquisition | Completed 2026-08-11 | Resumable explicit-selection acquisition with separate backend and safe existing-file handling. |
| #5 Site availability and parity | Completed 2026-08-11 | Read-only remote/local inventory and case-parity CLI delivered and validated. |

## 6. Complete the durable analytical database — In progress

**Rationale:** Parsing every source database for every report is slow and makes
historical comparison harder. The analytical store should support exact reuse
without weakening source identity, provenance, validation, or publication
gates.

Phase 1 is complete:

- Schema version 1 stores source/parser/configuration history, canonical
  events, unrounded detailed intervals, run cases, wide snapshots,
  reconciliation, and validation results.
- Explicit `init`, `import-run`, `export-wide`, and `list-runs` commands are
  available; paths inside Git or an imported run are rejected.
- The canonical OneDrive store passed integrity and foreign-key checks with 1
  run, 9 run cases, 9 analyses, 1,226 events, 1,226 intervals, and 45
  reconciliation rows. Its SQL export matches the nine-case ASUI deliverable.
- Relocation uses `DELETE` journaling, deterministic logical parity, staged
  publication, locally pinned files, and a single-writer workstation rule.

Next phase:

- Add a validated schema-v2 copy-up migration that records every
  analysis-affecting input, including an explicit absent timing-log dependency.
- Add opt-in, read-only cache lookup to the validated Timeline Analysis runner.
  The exact key must include source, timing-log, parser, configuration, and
  cache-contract fingerprints; size and modification time are hints only.
- Materialize cache hits through the standard artifact writers, run the normal
  validation/reconciliation/publication gates, and report hit/miss/invalid
  outcomes under `Backend/reports`.
- Keep store import a separate explicit command; do not add a hidden database
  default or automatic OneDrive write.
- Add deterministic SQL-backed long export, run comparison, and run/site
  summary commands using detailed intervals as the source of truth.

Completion criteria:

- Schema migration, cache keys, materialization, corruption fallback, and all
  invalidation dimensions pass tests using temporary databases.
- Uncached and all-hit reruns of the same nine ASUI and five explicit UCLA
  cases produce identical public CSVs and matching validated event/interval
  artifacts without modifying source data.
- SQL reports reconcile to their source runs, and the canonical store remains
  pinned, sidecar-free after close, and valid after OneDrive resumes.

## 7. Profile and optimize the pipeline

**Rationale:** Profiling now reconciles total wall time, but optimization should
follow cache integration so measurements reflect the intended architecture.

Current evidence:

- The representative four-case profiler reconciles more than `99.99%` of wall
  time and distinguishes CPU, database, and filesystem work.
- A plot-disabled diagnostic reduced measured runtime by `10.81%` with an
  identical final CSV.
- Intermediate diagnostic CSV suppression remains unsupported because those
  artifacts are part of the current staged contract.

Next phase:

- Run three repeated benchmarks on one fixed representative manifest with
  cache disabled, all cases cached, and a controlled hit/miss mixture.
- Report median wall time, CPU time, database/filesystem attribution, stage and
  case percentages, output parity, and percentage change.
- Select an optimization only after the measurements identify a bottleneck;
  preserve case selection, source handling, detailed interval truth,
  publication gates, and public output contracts.

Completion criteria:

- Every benchmark reconciles nested timing to total wall time within tolerance.
- The chosen optimization has repeatable before/after evidence and exact public
  output parity.
- Generated profiling outputs remain outside Git and the recommendation clearly
  distinguishes CPU, database, and filesystem constraints.
