# ARCHITECTURE.md

## Purpose

This file defines the current system structure and module boundaries for the
staged Python timing-analysis pipeline. It is not a task log or session diary.

## Control-Flow Position

Read this file after `AGENTS.md` and `SOP.md`, and before `SESSION.md`.

## Supported Pipeline Flow

```text
site root
  -> discovery.py
  -> db_source.py
  -> ingestion.py
  -> normalization.py
  -> enrichment.py / timing_log.py
  -> state_machine.py
  -> timing.py
  -> manifest.py / plotting.py
  -> plot_tables.py / workflow_summary.py / site_comparison.py
  -> timing_gantt_deliverables.py
```

An optional, pre-pipeline acquisition test is isolated from that core flow:

```text
explicit commercial site + case selection
  -> single_case_acquisition.py
  -> exact <case-id> TDC Sessions folder
  -> one timestamped session folder with direct local.db
  -> validated <destination>/<case_id>/local.db
  -> ordinary site-root discovery when explicitly selected for analysis
```

The dependency-gated representative validation composes that contract without
changing the core timing pipeline:

```text
explicit site + at least five unique case IDs
  -> multi_case_acquisition.py
  -> sequential single-case acquisition through one read-only connection
  -> required internal case-identity verification
  -> case-level JSON + aggregate JSON/Markdown summaries
```

The production-oriented acquisition layer remains explicit and composes the
same case gate:

```text
explicit site + repeated case IDs or text manifest
  -> bulk_acquisition.py
  -> separate backend lock + durable case inventory
  -> single-case acquisition, reported existing-file skip, or verified reuse
  -> <destination>/<case_id>/local.db
  -> <backend>/{_acquisition,_staging,_quarantine}
```

A separate preflight inventory checks endpoint availability without entering
the acquisition or timing pipelines:

```text
explicit three-digit site ID
  -> site_availability.py
  -> read-only Sync.com folder metadata + Teams-synced local folder metadata
  -> canonical case/artifact parity summary
  -> console and optional sanitized JSON (no acquisition or database reads)
```

The durable analytical store has two explicit roles. Post-run imports are the
only write path; the validated runner may opt into exact read-only reuse without
changing publication gates:

```text
validated Backend/ + Report/ run artifacts
  -> analytical_store.py complete pre-transaction validation
  -> explicit cross-site SQLite import with source/parser/config history
  -> canonical events + unrounded detailed intervals as analytical truth
  -> SQL views/exports for wide, long, comparison, and run/site summaries

validated source candidate + timing-log dependency
  -> SHA-256 exact cache key (source + timing log/absence + parser + config + contract)
  -> timeline_cache.py read-only hit/miss/invalid decision
  -> standard normalized/enriched/labeled/interval writers
  -> unchanged identity, interval, plot, reconciliation, and publication gates
```

`first_slice_cli.py` is the staged-pipeline orchestrator. It coordinates the
flow above and records run-level, case-level, and artifact-level status without
embedding the implementation of each stage.

## Module Boundaries

- `models.py` contains typed contracts for run configuration, discovered cases,
  raw/normalized/enriched events, state-labeled events, intervals, and manifests.
- `errors.py` contains the typed exception hierarchy used at stage boundaries.
- `config.py` validates CLI/mapping configuration and year selection.
- `discovery.py` enumerates cases and candidate database sources deterministically.
  Canonical site-prefix filtering is the default; extra prefixes are explicit
  opt-in compatibility behavior.
- `db_source.py` resolves database candidates using deterministic precedence and
  explicit ambiguity handling.
- `ingestion.py` reads `AuditLogRecords` and optional `Sessions` data read-only.
- `normalization.py`, `enrichment.py`, and `timing_log.py` produce immutable
  derived event streams from raw inputs.
- `state_machine.py` assigns workflow states and records cleanup attribution.
- `timing.py` computes state intervals, rebasing, truncation, and quality flags.
- `manifest.py` writes the canonical run, event, and interval artifacts.
- `plotting.py` produces timeline figures from interval contracts only.
- `plot_tables.py`, `workflow_summary.py`, and `site_comparison.py` are
  downstream analytical/reporting consumers of derived timing artifacts.
- `timing_gantt_deliverables.py` builds human-facing final deliverables from
  completed timing-Gantt run folders without changing raw reconstruction data.
- `tff_adapter.py`, `tff_bounded.py`, and `hardware_lookup.py` are optional,
  provenance-oriented integration surfaces and are not required for the core
  timing pipeline.
- `single_case_acquisition.py` is an optional, read-only validation surface for
  acquiring one explicitly selected commercial `local.db`. It matches the exact
  case folder, ignores `applog`, inspects timestamped session children, rejects
  ambiguity, and supports opt-in session-export ZIP fallback only when no direct
  database exists. It reuses the ProfoundTools Sync transport snapshot under
  `tools/profoundtools` without changing its `applog` planner.
- `multi_case_acquisition.py` is the dependency-gated five-or-more-case
  validation surface. It requires unique explicit same-site IDs, isolates case
  failures, requires internal case identity, and produces machine- and
  human-readable summaries.
- `bulk_acquisition.py` is the scalable explicit-selection layer. It checkpoints
  a case-level JSON/CSV inventory after every case, requires a technical backend
  outside the clean destination, isolates failures, and recovers interrupted
  staging files. It reports and skips valid pre-existing databases, supports
  opt-in exact remote-hash adoption, and reuses verified files only when local
  validation, prior inventory, and current remote metadata agree. Required
  identity uses `PatientId` when available; otherwise a downloaded artifact must
  have one `Sessions.Start` matching the exact selected session-folder timestamp
  within two seconds. It does not discover cases implicitly or call source-share
  mutation APIs.
- `site_availability.py` is the non-acquiring site preflight. It resolves one
  configured Sync share and one Teams-synced site directory, enforces one
  recognized `TDC Sessions`/`TDC Data` root, inventories exact case/session
  hierarchy and direct `local.db` metadata, and reports canonical case parity.
  It uses remote listing and local filesystem metadata only; it does not call
  download, extraction, SQLite, staging, or source-write paths.
- `onboarding.py` owns analysis-first Windows handoff validation. It resolves
  one Teams-synced site, inventories canonical case/database candidates
  read-only, validates all-versus-manifest selection, and writes versioned
  non-secret profiles plus safely quoted collision-safe runners under the
  user's Local AppData. It does not handle credentials, acquire data, or write
  an analytical store.
- `preflight_baseline.py` captures and verifies reusable repository gates.
  Exact reuse requires a fresh snapshot with passing tests/checks and matching
  repository path, Git commit plus dirty-content fingerprint, interpreter
  path/version/binary hash, installed-dependency fingerprint, and test-command
  contract. Live preflight remains the default; stale or mismatched reuse is a
  hard failure.
- `analytical_store.py` owns schema migrations and the explicit post-run
  `init`, `import-run`, `export-wide`, `export-long`, `compare-runs`,
  `summarize-runs`, and `list-runs` operations. Schema v1 stores parser
  provenance, source observations, run/case status, full endpoint provenance,
  state-labeled canonical events, detailed intervals, imported wide snapshots,
  validation, and reconciliation history. Schema v2 adds exact analysis-input,
  timing-log/absence, cache-contract, configuration, and materialization
  metadata. Imports validate every artifact and source before a transaction,
  reuse only an identical source/parser/configuration analysis, and reject
  changed content under an existing run ID. It does not acquire source data or
  write automatically during pipeline execution.
- `timeline_cache.py` validates one explicit store read-only, hashes already-
  resolved source inputs, and returns exact hit/miss/invalid decisions. Hits
  reconstruct typed events and intervals for the standard writers. An invalid
  case entry falls back to normal parsing; store-level schema, integrity, or
  foreign-key failure aborts cache-enabled execution.
- `store_upgrade.py` owns schema copy-up. It requires stopped OneDrive sync,
  uses SQLite backup into a sibling temporary database, verifies deterministic
  legacy content and migration checksums, closes all connections, and swaps
  files atomically without overwriting an unrelated destination.
- `store_relocation.py` owns rollback-safe store movement and post-sync
  verification. It uses SQLite backup rather than file copying, deterministic
  schema/data hashing, staged non-overwriting publication, explicit source-file
  cleanup, and Windows local/pinned-state checks. It never recursively deletes
  a store directory.

## Legacy Compatibility Surface

Root-level `tulsa_*.py` files are compatibility wrappers into matching modules
under `src/site_timing_analysis/`. Legacy batch files and the R reference under
`Legacy/` remain available for comparison and historical workflow support.

New pipeline work should compose from normalized events and downstream contracts;
it should not bypass the staged interfaces or add summary/plot logic to ingestion
or normalization modules.

## Data and Output Rules

- Source databases are treated as read-only.
- Raw databases, analysis workbooks, generated outputs, and caches stay outside
  source control unless explicitly approved.
- Derived artifacts are written beneath the selected run directory using the
  canonical layout in `output_layout.py`.
- Case/site identifiers and provenance fields must remain attributable through
  every downstream export.
- Clinical-derived analytical stores and their exports must use an explicit
  path outside both the repository and imported run directories.
- Pipeline cache mode defaults to off. Read-only reuse requires an explicit
  store path, and successful runs are seeded only by a later explicit import.
- Pre-execution baseline mode defaults to live. Reuse requires an explicit
  external snapshot and a positive freshness window; the run report retains
  both the original gate evidence and exact-match validation details.
- The sole operational store is
  `C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite`.
  It uses `DELETE` journaling and one workstation may write it. Other OneDrive-
  synchronized copies are backup/read-only; OneDrive is not a database-locking
  mechanism.

## Deferred Work

- Formal parity diffing against historical R outputs.
- Further plot or source-resolution optimization only after a separately
  approved benchmark and byte-parity contract. Plot suppression remains
  diagnostic-only while plots are required artifacts.
- Splitting large compatibility/reporting modules after interface behavior is
  stabilized and covered by the test suite.
