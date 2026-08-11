# Changelog

## 2026-08-11 - Durable Timeline Analysis Store Phase 1

- Added a schema-versioned, cross-site SQLite analytical store with checksummed
  transactional migration, enforced foreign keys, immutable historical source,
  parser, configuration, run, case, event, interval, validation, reconciliation,
  and endpoint-provenance records.
- Added explicit `init`, `import-run`, `export-wide`, and `list-runs` commands.
  Imports validate complete published artifacts before the write transaction;
  identical reimports are no-ops and changed content under one run ID is a hard
  conflict.
- Added SQL views for unrounded state totals, latest case-analysis versions,
  run status, and the 20-column wide timing contract. Final export alone applies
  clock-only endpoint formatting and one-decimal state rounding.
- Live ASUI acceptance imported 9 cases, 1,226 canonical events, 1,226 detailed
  intervals, and 45 reconciliation rows. The second import added zero records;
  SQLite integrity, foreign keys, source metadata/hash preservation, and
  normalized historical CSV parity passed.
- Kept the clinical-derived store and SQL export outside Git. Cache integration
  and broader SQL-native reporting remain TODO #6 follow-up work.
- Relocated the sole operational store and its ASUI export to the locally pinned
  `OneDrive - Profound Medical\Documents\10_Databases` directory through a
  validated SQLite backup and staged export publication. The old local store,
  its WAL/SHM sidecars, export, and now-empty directories were removed only
  after logical-content and export parity passed.
- Changed writable store connections to `DELETE` journaling with full
  synchronization and bounded lock waiting. Added a safe relocation/verification
  CLI and an explicit single-writer workstation rule for OneDrive.

## 2026-08-11 - Validated Single-Case Acquisition

- Added a site-ID-only, read-only availability and case-parity CLI for comparing
  configured Sync.com session artifacts with Teams-synced canonical
  `<case-id>\local.db` artifacts without downloading or inspecting databases.
- Live site-122 acceptance found 19 remote and 19 local canonical cases with
  complete parity; noncanonical remote/local folders were reported and excluded.
- Added the repository-local ProfoundTools Sync transport and Windows keyring
  setup helper without storing credentials or share URLs in Git.
- Corrected acquisition traversal to match an exact case folder, ignore
  `applog`, and inspect timestamped session-folder children for one unambiguous
  direct `local.db`.
- Added opt-in, ambiguity-safe session-export ZIP fallback and suppressed signed
  transport URLs from verbose logging.
- Completed the live `122_01-001` acceptance acquisition with independent
  SQLite, size, hash, report-sanitization, and source-read-only checks.
- Added a separate explicit multi-case validation runner with unique same-site
  selection, case isolation, required internal identity checks, and aggregate
  JSON/Markdown reporting.
- Completed the live `122_01-001` through `122_01-005` validation: all five
  direct databases passed with no failure or quarantine, and post-run remote
  metadata remained unchanged.
- Added the explicit resumable bulk acquisition CLI with text-manifest support,
  per-case inventory checkpoints, destination locking, safe existing-file
  reuse, stale-staging recovery, failure isolation, and per-run JSON/Markdown/CSV
  reports. Live bulk acceptance remains pending an operator-supplied destination
  and case manifest.
- Required bulk technical artifacts to use a backend path outside the clean
  case destination. Valid pre-existing databases are reported and skipped
  without overwrite; optional exact remote-hash adoption remains available.
- Added a strict identity fallback for databases without `PatientId`: the sole
  internal `Sessions.Start` must match the exact selected Sync session-folder
  timestamp within two seconds.
- Completed the explicit 19-case ASUI_122 bulk acceptance with 19 successes,
  no failures or quarantines, and independent read-only validation of every
  final database. Technical artifacts remain outside the shared case root.

## 2026-08-10 - Repository Stabilization and Hygiene

- Added the site-agnostic validated wide timeline exporter with semantic
  discovery/database/publication gates and the compact `Backend/` + `Report/`
  output layout.
- Kept the final wide CSV at 20 columns, formatting endpoint times as
  `h:mm:ss AM/PM` while retaining full ISO timestamps and provenance in the
  audit report.
- Added opt-in, nested performance profiling that reconciles to total wall time
  and avoids double-counting shared artifacts.
- Added standardized timing-Gantt deliverable tooling and regression coverage.
- Updated architecture and session documentation to match the implemented
  staged pipeline and preserve historical session detail in `Legacy/`.
- Added headless matplotlib handling for the legacy Gantt entry point.
- Added opt-in discovery of known Stanford TFF exclusion cases when the TFF
  exclusion filter is enabled, without changing default discovery behavior.
- Declared `openpyxl` as a runtime dependency for Excel-backed TFF processing.
- Updated legacy batch helpers to use the repository virtual environment
  explicitly.
- Added an ignore rule for raw workbooks under `docs/`.
- Removed committed clinical-derived SQLite fixtures, their generated validation
  artifacts, and committed Python bytecode. Tests now generate a deterministic,
  non-clinical SQLite fixture at runtime.

## 2026-03-11 - Stable Baseline Locked

- Locked a stable Python timing-pipeline baseline for legacy-style parity workflows.
- Baseline includes discovery, ingestion/normalization, enrichment, state reconstruction, timing/rebasing, plotting, interval hardening, residual outlier cleanup, and diagnostics CLI reporting.
- Full-site validation artifacts were generated and reviewed for structural stability prior to branching into the next TODO-driven expansion phase.
