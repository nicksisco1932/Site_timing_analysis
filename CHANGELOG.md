# Changelog

## 2026-08-11 - Validated Single-Case Acquisition

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
