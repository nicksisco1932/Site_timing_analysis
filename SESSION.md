# SESSION.md

## Project

Site Timing Analysis (legacy R workflow migrated to a staged Python pipeline)

## Current Objective

TODO #6 is in progress. Phase 1 now provides an explicit, versioned cross-site
SQLite store that imports validated Timeline Analysis run artifacts and exports
the 20-column wide result from detailed SQL-backed intervals. The nine-case ASUI
run passed live import, idempotency, source-preservation, and export-parity
acceptance. Cache integration and broader SQL-native reporting remain open.

## Governing Files

1. `AGENTS.md`
2. `SOP.md`
3. `ARCHITECTURE.md`
4. `SESSION.md`

## Current State

### Implemented

- Deterministic case discovery and database-source resolution.
- Read-only SQLite ingestion and canonical event normalization.
- Session/timing-log enrichment, state reconstruction, and interval timing.
- Normalized/original-hour timeline plots and operator diagnostics.
- Plot tables, workflow summaries, site comparisons, TFF adapter outputs, and
  standardized timing-Gantt deliverables.
- Root compatibility wrappers and legacy reference material remain available.
- Current repository cleanup slice includes headless legacy plotting, opt-in TFF
  exclusion-case discovery, declared Excel support, and explicit batch entrypoint
  interpreters.
- The validated wide timeline exporter now derives discovery counts at runtime,
  gates on semantic discovery/database/processed-case invariants, and removes
  expected-count CLI switches.
- Final wide CSV timestamps are exported as clock-only `h:mm:ss AM/PM`; full ISO
  endpoint datetimes and provenance remain in the validation report.
- Added opt-in `--profile` instrumentation for the validated Timeline Analysis
  runner. Nested exclusive stage timings reconcile to total wall time, retain
  inclusive drill-down timings, and assign every artifact to one case or the
  global run scope.
- Added and live-validated an isolated single-case commercial `local.db`
  acquisition test. It requires explicit site/case selection, matches the exact
  case folder, ignores `applog`, inspects timestamped session children, rejects
  remote ambiguity, stages downloads, and publishes only after read-only SQLite
  integrity/schema/relationship validation. Session-export ZIP fallback is
  separately opt-in, and verbose logging suppresses signed transport URLs.
- Relocated the required ProfoundTools `sync-tdc-logs` snapshot to the stable
  repository path `tools/profoundtools`; its source and `applog` behavior remain
  unchanged, and credential-bearing runtime files remain ignored.
- Added and live-validated the dependency-gated multi-case acquisition runner.
  It requires at least five unique same-site case IDs, reuses one read-only
  connection, isolates per-case failures, requires internal case identity, and
  writes case JSON plus aggregate JSON/Markdown reports outside Git.
- Added the scalable explicit bulk acquisition runner. It checkpoints JSON/CSV
  inventory after every case in a required backend outside the final
  destination, recovers interrupted staging files to backend quarantine,
  reports and skips valid pre-existing databases, and reuses verified outputs
  only when local validation, prior inventory, and current remote metadata agree.
- Added the site-ID-only read-only availability and parity checker. It requires
  one recognized remote session root and one local site directory, inventories
  exact canonical case/database placement, excludes but reports noncanonical
  folders, prints actionable differences, and optionally writes sanitized JSON
  outside the Teams-synced tree.
- Added the phase-1 durable analytical store and `scripts/timeline_store.py`
  CLI. Schema v1 records source/parser/configuration history, run and case
  status, full endpoint provenance, canonical state-labeled events, unrounded
  detailed intervals, imported wide snapshots, validations, and reconciliation
  results. Imports are prevalidated and atomic; exact reimports are no-ops.

### Not Yet Implemented

- Full formal parity diffing against historical R outputs.
- `.xlsx` timing-log enrichment.
- Broader multi-site curated-store/catalog workflow.
- Timeline Analysis cache lookup/reuse and broader SQL-native reports and
  comparisons from the phase-1 store.

## Current Blocker

No blocker is active. TODO #6 remains intentionally in progress because its
cache-integration and broader reporting phase has not yet been designed or
approved.

## Data Governance

- The potentially sensitive workbook formerly under `docs/` is quarantined at
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_quarantine` and is
  ignored by the repository.
- The two duplicate tracked SQLite fixtures and their generated validation
  CSV/PNG outputs were removed after read-only review found populated identity
  fields. Tests now generate a deterministic, minimal, non-clinical SQLite
  fixture with `testing/synthetic_test_db.py`.
- SQLite databases, sidecars, raw workbooks, generated outputs, and profiling
  artifacts are ignored and are not part of the proposed source changes.

## Recent Decisions

- Preserve current user changes and legacy modules; do not perform broad rewrites.
- Keep staged-pipeline output contracts unchanged.
- Keep canonical discovery filtering unchanged by default; TFF known-exclusion
  prefixes are opt-in only.
- Keep `SESSION.md` concise; historical session detail is retained in
  `Legacy/SESSION_HISTORY.md`.
- Use explicit repo-local `.venv` executables for Python tooling.
- Keep the vendored Sync transport isolated under `tools/profoundtools` and
  continue to manage its shared password through the current Windows user's OS
  keyring.
- Use `scripts/setup_sync_credential.ps1` for concealed credential setup or
  removal; the script delegates storage to the unchanged ProfoundTools keyring
  utility and never accepts a password argument.
- Keep five-case validation separate from TODO #4: the current runner is
  sequential and deliberately does not add resumability or bulk overwrite
  behavior.
- Bulk selection is never discovered implicitly. Safe reuse requires matching
  local validation/hash, prior inventory, and current remote metadata; otherwise
  the case is quarantined without overwrite.
- Site availability is inventory-only: remote `listdir` calls and local metadata
  reads are permitted, while download, extraction, database inspection, staging,
  and source modification remain outside that command.
- Keep durable-store writes explicit and post-run. Never create a
  clinical-derived store implicitly, and reject database destinations inside
  Git or the imported run directory. Detailed intervals remain authoritative;
  wide snapshots are parity evidence only.

## Known Issues

- `local2.db` behavior remains outside the modern staged pipeline.
- Timing-log enrichment currently supports CSV only.
- Legacy behavior and warning-tier policies still require broader parity review.
- Large legacy-compatible modules remain intentionally unsplit until the
  stabilized baseline is green.

## Validation Status

- Full suite after fixture replacement: `114 passed`, `0 failed`, `0 warnings`
  in `59.74s` using the repo-local `.venv`.
- Synthetic SQLite pipeline regression: `3 passed`.
- Four-case Stanford profiling benchmark reconciled at greater than `99.99%`
  stage coverage. The plot-disabled diagnostic comparison preserved an
  identical final CSV; intermediate-CSV suppression remains intentionally
  unsupported because those paths are part of the staged artifact contract.
- Focused TFF/discovery regression checks: `3 passed`.
- CLI help checks pass for the staged pipeline, validated wide exporter, and
  deliverable builder.
- Single-case acquisition regression: `16 passed`; its CLI help check passes
  and the repository-local ProfoundTools transport imports successfully through
  the optional acquisition dependencies.
- Vendored ProfoundTools transport regression: `90 passed`, `3 skipped`; its
  top-level CLI help check passes without reading a stored credential.
- `scripts/setup_sync_credential.ps1` passes PowerShell parser validation; the
  site-122 runtime configuration is recognized and ignored by Git.
- Full suite after the completed acquisition slice: `130 passed` in `70.62s`.
- Live acceptance case `122_01-001` was saved outside Git at
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_acquisition_test\`
  `2026-08-11_site122_case001\122_01-001\local.db` (`11,608,064` bytes,
  SHA-256 `BBB5044A982075FDF31E60B14EEA93A0DDB1CDE04D8DC1716B788A13D24DCD99`).
  Independent immutable read-only verification reports SQLite integrity `ok`,
  all required tables, and zero treatment/session relationship orphans.
- The adjacent JSON report matches the published path, size, and digest; it
  contains no Sync URL, password, signed-download token, or signature marker.
  No staging or quarantine files remain, and a post-run listing confirmed the
  remote source remained present and unchanged.
- Multi-case acquisition regression, including the single-case tests:
  `23 passed`. Full repository suite after TODO #3: `137 passed` in `69.50s`.
- Live cases `122_01-001` through `122_01-005` completed in `94.7s` with `5`
  success, `0` failure, and `0` quarantine at
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_acquisition_test\`
  `2026-08-11_site122_five_case_validation`.
- Independent immutable read-only verification matched all five paths, sizes,
  SHA-256 digests, schemas, relationship checks, and internal case identities.
  The aggregate invariants all pass; five case reports and both aggregate
  reports are present, with zero staging/quarantine files and no sensitive URL
  or token markers.
- Post-run remote listing found one unchanged direct `local.db` per selected
  case by recorded size and modification timestamp; `applog` was not traversed.
- Bulk acquisition regression, including the single- and five-case surfaces:
  `39 passed`. A 25-case synthetic run downloaded each database once and an
  identical second run reused all 25 with zero additional downloads. Tests also
  cover manifest rejection, source/local mismatch, missing inventory,
  interruption recovery, destination locking, and case failure isolation.
- Live ASUI_122 bulk acceptance requested 19 numeric cases and completed with
  `19` successes, `5` downloads, `11` verified reuses, `3` reported local-only
  skips, `0` failures, and `0` quarantines. Independent immutable read-only
  validation passed for all 19 files. Technical records are under the ignored
  `outputs\acquisition\ASUI_122\Backend`; the shared site root contains no
  acquisition, quarantine, or staging directory.
- Full repository suite after final bulk amendments: `153 passed` in `68.02s`.
- Site-availability regression: `18 passed`. Full repository suite after TODO
  #5: `171 passed`; CLI help and compilation checks pass.
- Live site-122 availability acceptance returned exit `0` with remote root
  `TDC Sessions`, `19` remote canonical cases, `19` local canonical cases, and
  `19` complete matches. The checker reported one remote and two local
  noncanonical folders separately and performed no acquisition or report write.
- Durable-store focused regression: `15 passed`, covering schema/checksum
  reopening, complete and partial imports, raw payload round-trip, exact export
  formatting, idempotency, historical versioning, hard conflicts, invalid
  artifacts, atomic rollback, and destination rejection.
- Full repository suite after TODO #6 phase 1: `186 passed` in `67.46s`.
  All four store subcommand help checks pass, `pip check` reports no broken
  requirements, and `git diff --check` reports no whitespace errors.
- Live ASUI store acceptance imported 9 run cases, 1,226 canonical events,
  1,226 detailed intervals, and 45 reconciliation rows. A second identical
  import inserted zero analyses/events/intervals. SQLite integrity is `ok`,
  foreign-key checks report zero issues, and all nine current source hashes,
  sizes, and modification times match their imported observations.
- The external SQL export contains 9 rows and the exact 20 headers. All values
  match the historical ASUI deliverable after normalizing only that older
  file's full-ISO endpoint cells to the current clock-only contract. Store and
  export paths are under
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_store`, outside Git.
- `pip check` reports no broken requirements.
- `git diff --check` reports no whitespace errors; Git only reports normal
  Windows LF/CRLF conversion warnings.
- The 2026.03.19 ASUI roll-up remains unchanged at SHA-256
  `81E3C37C1F05A3999974D381DE71DF32C28FC4F63B630DEA1DE9EC79EC64B546`.
- Live size/modified-time comparisons found zero mismatches across the 9 ASUI
  and 148 Stanford source databases recorded by the existing integrity reports.

## Next Recommended Step

Design the next TODO #6 phase: explicit cache lookup/reuse in Timeline Analysis,
followed by broader reports and comparisons generated from stable SQL views.

## Resume Instructions

1. Read `AGENTS.md`.
2. Read `SOP.md`.
3. Read `ARCHITECTURE.md`.
4. Read `SESSION.md`.
5. Treat TODO #4 as complete and preserve its separate-backend and
   existing-file-awareness contracts for future sites.
6. Treat TODO #5 as complete and preserve its inventory-only, sanitized-output,
   and no-`applog` contracts.
7. Treat TODO #6 phase 1 as complete but the parent item as in progress.
   Continue with cache integration and broader SQL-native reporting only after
   their interface and invalidation rules are approved; profiling remains #7.
