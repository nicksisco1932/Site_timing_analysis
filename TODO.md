# TODO

## Current checkpoint

- Before the 2026-08-11 local checkpoint, `feature/workflow-analytics` matched
  `origin/feature/workflow-analytics` at `92f6ec9`; no pull entry was present in
  the available reflog, so that commit remains the reviewed comparison baseline.
- GitHub housekeeping for the current Timeline Analysis slice was completed on
  2026-08-10. The reviewed scope and reviewer-ready narrative are recorded in
  `docs/PULL_REQUEST_SUMMARY.md`.
- Clinical-derived SQLite fixtures, generated validation outputs, profiling
  runs, caches, and committed bytecode were removed. Integration tests now
  generate a deterministic non-clinical SQLite fixture at runtime.

## 1. Complete standard GitHub housekeeping — Completed 2026-08-10

**Rationale:** The recent Timeline Analysis work is broad and uncommitted. It
needs a deliberate scope, data-governance, and reviewer-readiness pass before it
is published.

Completion evidence:

- Reviewed branch/upstream state, recent commits, and the complete diff from
  upstream baseline `92f6ec9`; the intended functional, documentation,
  provenance, test, and cleanup changes are classified in the reviewer summary.
- Removed temporary profiling runs, generated test files, two duplicate tracked
  SQLite fixtures, nine tracked validation outputs, and committed Python
  bytecode. No untracked database, workbook, CSV, JSON, image, or PDF is exposed
  for staging.
- Replaced the database fixture with `testing/synthetic_test_db.py`, which
  generates deterministic non-clinical input in disposable test directories.
- Full suite: `114 passed`, zero failures and warnings. The synthetic database
  regression reports `3 passed`.
- Help checks pass for `site_timing_analysis.first_slice_cli`,
  `scripts/run_timeline_analysis.py`, and
  `scripts/build_timing_gantt_deliverables.py`.
- `pip check` reports no broken requirements; `git diff --check` reports no
  whitespace errors.
- Updated `README.md`, `ARCHITECTURE.md`, `SESSION.md`, `CHANGELOG.md`, and
  supporting documentation. `docs/PULL_REQUEST_SUMMARY.md` explains scope,
  rationale, contracts, validation, limitations, and follow-up work for a new
  reviewer.
- The existing 2026.03.19 ASUI roll-up remains unchanged at SHA-256
  `81E3C37C1F05A3999974D381DE71DF32C28FC4F63B630DEA1DE9EC79EC64B546`.
  Existing run-integrity records and live metadata comparisons show zero source
  database changes across 9 ASUI and 148 Stanford ingested cases.

## 2. Test single-case `local.db` acquisition — Completed 2026-08-11

**Status:** Completed. The isolated one-case CLI now follows the verified live
hierarchy, uses the repository-local ProfoundTools transport, preserves the
existing `applog` workflow, and has passed a real site-122 acquisition.

**Rationale:** Prove the authenticated, read-only acquisition path with the
smallest possible scope before testing multiple cases or designing bulk
behavior.

Create a minimal end-to-end test that:

- connects to the relevant commercial Sync.com share;
- requires one explicitly supplied site and case ID;
- locates the exact case folder named `<case-id> TDC Sessions`;
- finds and retrieves that case's `local.db`;
- validates that the result is a readable SQLite database containing the
  required tables;
- saves it to a configurable temporary or test destination; and
- reports its identity, basic schema, and exact saved path for manual
inspection.

Verified live hierarchy, with the site-level container shown explicitly:

```text
Link for Site - <site>
+-- TDC Sessions
    +-- <case-id> TDC Sessions
        +-- <timestamped session folder>
        |   +-- local.db
        |   +-- <session-export>.zip
        |   +-- Raw.zip
        +-- applog
```

Required traversal and selection behavior:

- Match the exact case folder named `<case-id> TDC Sessions`.
- Treat `applog` as unrelated to `local.db` acquisition and leave the existing
  `applog` workflow unchanged.
- Inspect the timestamped session-folder children beneath the case folder.
- Select a valid session folder containing a direct child named `local.db`,
  case-insensitively.
- Require an unambiguous match. Quarantine missing, multiple, or conflicting
  candidates rather than guessing.
- Inspect a session-export ZIP only when the direct `local.db` is absent.
- Validate the selected SQLite database before copying it.
- Save a successful result as `<destination>\<case-id>\local.db`, matching the
  Timeline Analysis/PEDA input structure.

The test must keep the source database read-only, preserve the existing
`applog` workflow unchanged, and quarantine missing, ambiguous, or invalid
sources rather than guessing. The destination will be supplied when the test
is run.

**Completion criteria:** One explicitly selected case is downloaded
successfully through the verified hierarchy; its `local.db` opens and passes
basic schema validation; its identity and exact local path are printed for
manual inspection; and every missing, ambiguous, multiple, conflicting, or
invalid condition produces a clear failure or quarantine reason.

Completion evidence:

- Acquired explicit site/case `122` / `122_01-001` through
  `TDC Sessions/122_01-001 TDC Sessions/`
  `_2025-03-24--10-01-59 105064141/local.db` using listing and download-only
  transport operations.
- Published the validated database at
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_acquisition_test\`
  `2026-08-11_site122_case001\122_01-001\local.db` and printed that exact path.
- Saved the machine-readable result at the adjacent
  `_reports\122_01-001_single_case_acquisition.json` path.
- Verified `11,608,064` bytes and SHA-256
  `BBB5044A982075FDF31E60B14EEA93A0DDB1CDE04D8DC1716B788A13D24DCD99`;
  report path, size, and digest all match the published file.
- Opened SQLite independently with `mode=ro&immutable=1`; integrity is `ok`,
  required tables are present, row counts are `271` AuditLogRecords, `1`
  Session, and `2` Treatments, with zero treatment/session relationship
  orphans.
- Confirmed no staging or quarantine files remain and no Sync URL, password,
  signed-download token, or signature marker appears in the JSON report.
- Re-listed the selected remote folder after acquisition; the same four source
  files and `11.1 MB` `local.db` remain present. `applog` was not traversed.
- Focused acquisition regression: `16 passed`. Full repository suite:
  `130 passed`. CLI help, `pip check`, and `git diff --check` pass.

## 3. Validate acquisition with at least five cases — Completed 2026-08-11

**Depends on:** Successful completion of TODO #2.

**Status:** Completed. Five explicitly selected site-122 cases passed the live,
read-only acquisition and independent verification gates with no unresolved
issues.

**Rationale:** A multi-case test is needed to expose real differences in remote
folder structure, naming, identity, and database packaging before bulk use.

Extend the single-case test to acquire at least five explicitly selected cases
and review:

- incorrect or ambiguous session-folder matching;
- missing or multiple `local.db` candidates;
- download or extraction failures;
- SQLite integrity or schema problems;
- case-identity mismatches;
- duplicate or incorrectly named destination files; and
- structural differences between cases.

Do not proceed to bulk acquisition while any five-case issue remains
unresolved. Keep all source data read-only.

**Completion criteria:** At least five requested cases are acquired; every case
maps to exactly one valid `local.db`; files use the expected case-specific
directory structure; machine-readable and human-readable summaries classify
success, failure, quarantine, and reasons; and no source data is modified.

Completion evidence:

- Acquired the explicit set `122_01-001` through `122_01-005` to
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_acquisition_test\`
  `2026-08-11_site122_five_case_validation` in `94.7` seconds.
- All five cases resolved through one exact case folder and one timestamped
  session folder to a direct case-insensitive `local.db`; results were `5`
  success, `0` failure, and `0` quarantine. No ZIP fallback was enabled.
- Every database was saved as `<destination>\<case-id>\local.db`. Independent
  immutable read-only checks matched each reported size and SHA-256, returned
  SQLite integrity `ok`, found all required tables, found zero relationship
  orphans, and verified the normalized internal `PatientId` against the selected
  case ID. Saved paths and database hashes are unique.
- Wrote five case-level JSON reports plus
  `_reports\acquisition_summary.json` and
  `_reports\acquisition_summary.md`. The summaries contain no Sync URL,
  password, signed token, data key, or signature marker.
- No staging or quarantine files remain. A post-run read-only remote listing
  found exactly one direct database for every selected case and matched the
  recorded source size and modification timestamp for all five; `applog` was
  present but not traversed.
- Focused acquisition regression: `23 passed`. Full repository suite:
  `137 passed`. CLI help and Python compilation checks pass.

## 4. Add scalable bulk `local.db` acquisition

**Depends on:** Successful completion of TODO #3.

**Status:** Completed 2026-08-11.

**Rationale:** Once representative cases establish safe matching and
validation rules, provide a resumable command that eliminates manual
case-by-case web downloads while producing inputs Timeline Analysis already
understands.

Create a reusable command that acquires `local.db` files for explicitly
supplied site and case selections. The destination root will be supplied after
the single-case and five-case tests are complete. The command must:

- require explicit site and case selection;
- match each case to the exact `<case-id> TDC Sessions` folder and exactly one
  valid timestamped session-folder child;
- prefer that timestamped folder's direct child named `local.db`,
  case-insensitively;
- optionally inspect that timestamped folder's session-export ZIP when no
  direct database exists;
- quarantine missing, ambiguous, invalid, or conflicting candidates;
- validate SQLite integrity, required tables, case identity, file size, and
  SHA-256;
- maintain a case-level acquisition inventory;
- keep the final destination clean: it may contain case directories and their
  sanitized `local.db` files, but technical inventory, reports, staging, and
  quarantine artifacts must be written to a separately supplied backend path;
- detect an existing `<destination>\<case-id>\local.db`, validate it read-only,
  skip download/overwrite, and record that explicit skip in the inventory and
  run report; do not claim remote-content equivalence unless a prior inventory
  or an explicit remote hash-verification run proves it;
- avoid silently overwriting an existing valid file;
- be resumable and safe to rerun;
- place files in the exact case-specific structure expected by Timeline
  Analysis; and
- preserve the existing `applog` behavior unchanged.

**Completion criteria:** One documented command acquires a large explicitly
requested case set; the expected Timeline Analysis directory structure is
produced; a complete acquisition report and inventory are written; failures
are isolated by case without guessed or fabricated files; reruns are safe; and
the source share and databases remain read-only.

Implementation evidence:

- Added `scripts\acquire_localdb_bulk.py` with exactly one required selection
  mechanism: repeated `--case-id` arguments or a UTF-8 `--case-manifest`.
- The command composes the validated exact-folder/session/database logic,
  requires internal case identity, supports opt-in session-export ZIP fallback,
  and preserves `<destination>\<case-id>\local.db`.
- Added durable inventory, run-specific JSON/Markdown/CSV reports, staging, and
  quarantine under a required backend path that must be outside the clean final
  destination.
- Safe reruns reuse a database only when its validation, size, SHA-256, saved
  path, prior inventory, and current remote path/size/modification metadata all
  agree. A valid pre-existing database without inventory is explicitly reported
  and skipped without download or overwrite; its remote equivalence remains
  unverified unless the operator opts into exact remote hash verification.
- Added a destination process lock and recoverable quarantine of interrupted
  staging files. Case failures remain isolated and processing continues.
- A 25-case synthetic scale run downloaded all cases once; an identical rerun
  reused all 25 with zero additional downloads. Focused acquisition tests:
  `39 passed`; final full repository suite: `153 passed`.
- The first explicit ASUI_122 live run requested 19 numeric cases. It produced
  11 successes and eight safe quarantines: every database passed SQLite,
  required-schema, and relational-link checks, while the eight quarantines had
  unavailable internal `PatientId` identity. Technical artifacts initially
  written beside the case folders were moved intact to the Git-ignored
  `outputs\acquisition\ASUI_122\Backend`; the shared destination now contains no
  `_acquisition`, `_quarantine`, or `_staging` directory.
- The corrected 19-case run completed with `19` successes, `0` failures, and `0`
  quarantines: `5` downloaded, `11` inventory-verified reuses, and `3` explicitly
  reported local-only existing-file skips. Cases `010` through `014` passed the
  exact case-folder plus `Sessions.Start` identity fallback.
- Independent immutable read-only validation confirmed all 19 files, SQLite
  headers, integrity checks, required tables, relational links, and report
  invariants. The shared root contains only case-level content; all acquisition
  bookkeeping remains in the separate Git-ignored backend.
- Final checks: CLI help passed, `pip check` passed, and `git diff --check`
  reported no whitespace errors beyond normal Windows line-ending notices.

## 5. Add site availability and case parity — Completed 2026-08-11

**Rationale:** Before acquiring or analyzing another site, provide a safe,
read-only way to confirm that its configured Sync.com share and Teams-synced
local directory are both available and to identify case-level differences
without downloading or changing data.

**Status:** Completed. The site-ID-only checker is implemented as an isolated
inventory command and has passed focused, repository-wide, and live site-122
validation.

Planned command:

```powershell
.\.venv\Scripts\python.exe scripts\check_site_availability.py --site 122
```

The command will accept a three-digit site ID and default to:

- Sync registry `tools\profoundtools\sites.json`;
- local parent `%USERPROFILE%\Profound Medical`; and
- optional overrides `--sites-file`, `--local-root`, and `--report-json`.

Remote inventory requirements:

- Confirm that the site is configured and its Sync.com share is reachable
  read-only.
- Accept exactly one recognized root: either `TDC Sessions` or `TDC Data`. If
  both or neither are available, report a root ambiguity or failure and exit
  `2`.
- Match exact `<case-id> TDC Sessions` folders and inspect only their immediate
  timestamped session-folder children.
- Treat a case-insensitive direct child named `local.db` as a candidate only
  when it belongs to one of those session folders and is nonempty according to
  available artifact metadata.
- Require exactly one candidate per case. Logically quarantine and report
  missing, duplicate, or conflicting candidates rather than guessing.
- Do not traverse `applog`.

Local inventory requirements:

- Resolve exactly one immediate site directory ending in `_<site-id>`, such as
  `Clinical Science Team - ASUI_122`.
- Inventory canonical local case folders using the selected site prefix and
  recognize `<case-id>\local.db` as the canonical local artifact.
- Report missing or duplicate case-level databases separately, and report
  noncanonical and local-only folders separately.
- Do not download, copy, rename, or modify local files.
- If the site directory is missing, print:

  ```text
  Site 122 is not available locally. Sync the site directory ending in _122 from the Clinical Science Team through the Teams app, then rerun.
  ```

Case-parity output must distinguish:

- matched remote and local cases;
- remote-only and local-only cases;
- local cases with missing or duplicate `local.db` artifacts;
- remote cases with missing or ambiguous session-level candidates;
- duplicate or ambiguous case IDs; and
- noncanonical folders excluded from canonical parity.

Always print an actionable console summary. Optionally write sanitized JSON
containing endpoint status, the resolved local path, counts, case-level
differences, warnings, and failure reasons. Console and JSON results must agree.
Exit `0` for complete canonical parity, `1` when both endpoints exist but
differences remain, and `2` for configuration, access, missing-site, or
root-ambiguity failures.

The command must never print or serialize passwords, Sync URLs, signed tokens,
or decryption keys. It must never download, extract, stage, acquire, or inspect
the contents of remote `local.db` files; it only inventories already-available
remote and local artifacts. Preserve the existing acquisition and `applog`
workflows unchanged.

**Completion criteria:** Tests cover reachable and missing Sync sites,
authentication failure, both/neither recognized roots, missing or ambiguous
local site directories, parity differences, missing/duplicate databases,
noncanonical folders, and sanitized reporting. A live read-only site-122 check
identifies its configured Sync share and
`Clinical Science Team - ASUI_122`; a simulated missing-local-site check prints
the Teams synchronization guidance; console and JSON results agree; and no
remote or local artifact is downloaded, copied, staged, extracted, or modified.

Completion evidence:

- Added `scripts\check_site_availability.py` and the isolated
  `site_availability.py` implementation with the requested defaults, overrides,
  sanitized JSON option, and exit-code contract.
- Remote inventory accepts exactly one `TDC Sessions` or `TDC Data` root,
  matches exact canonical case folders, never traverses `applog`, and uses only
  immediate-folder listing plus direct `local.db` size metadata. The code has no
  acquisition, ZIP, SQLite, hashing, staging, or source-write path.
- Local inventory resolves exactly one immediate `_<site-id>` directory,
  classifies canonical case-level databases, preserves complete folder
  accounting, and reports noncanonical folders separately without modifying the
  Teams-synced tree.
- Focused regression: `18 passed`, covering reachable/missing endpoints,
  authentication, both/neither roots, local-site ambiguity, parity differences,
  missing/duplicate/empty databases, duplicate case IDs, noncanonical folders,
  sanitization, console/JSON agreement, exact Teams guidance, and no mutation.
- Live read-only site-122 acceptance returned exit `0`: remote root
  `TDC Sessions`, `19` remote canonical cases, `19` local canonical cases,
  `19` complete matches, and no case/artifact issues. One remote and two local
  noncanonical folders were reported and excluded as designed.
- Full repository suite: `171 passed`. CLI help and Python compilation pass.

## 6. Create a durable analytical database — In progress

**Status:** Phase 1 completed 2026-08-11. Pipeline cache reuse and broader
SQL-native reporting/comparison work remain open under this item.

**Rationale:** Parsing every source database for every report is slow and makes
historical comparison harder. A separate analytical store would make ingestion
repeatable while preserving complete provenance and prior results.

The phase-1 implementation adds an explicit, cross-site SQLite store so
validated run artifacts can be imported once and queried historically. It
preserves:

- source case identity and provenance;
- site and case ID;
- source database path, modified time, and hash;
- parser/version information;
- analysis run metadata;
- canonical enriched events;
- detailed state intervals;
- wide case-level timing results;
- validation and reconciliation results;
- timestamp provenance;
- processing status and failure reasons.

Requirements:

- Keep source clinical databases read-only.
- Make ingestion idempotent: rerunning the same case with the same source and
  parser version must not silently duplicate records.
- Preserve prior analysis runs when the parser or source data changes.
- Treat detailed state intervals as the analytical source of truth.
- Generate the 20-column wide CSV from SQL interval views without rereading the
  source database.
- Keep the analytical database outside Git if it contains generated or
  clinical-derived data.

Phase 1 completion evidence:

- Added schema version 1, checksummed transactional migration, foreign-key
  enforcement, content-addressed source/parser/configuration history, canonical
  events, unrounded intervals, run cases, wide snapshots, reconciliation and
  validation records, and four SQL views.
- Added explicit `init`, `import-run`, `export-wide`, and `list-runs` commands in
  `scripts/timeline_store.py`. Store paths inside Git or the imported run are
  rejected.
- Synthetic store regression covers complete and partial runs, raw payload
  round-trip, exact export formatting, idempotency, historical versions,
  conflicts, invalid artifacts, rollback, and destination safety.
- Validation completed with `15` focused store tests and `186` passing tests in
  the full repository suite; CLI help, `pip check`, and `git diff --check` pass.
- Live ASUI import stored 9 run cases, 1,226 canonical events, 1,226 detailed
  intervals, and 45 reconciliation rows. An identical second import added zero
  records. SQLite integrity, foreign keys, and all nine source hash/size/mtime
  comparisons passed.
- The SQL export has the exact 20-column contract and matches the historical
  ASUI values after converting its older full-ISO endpoint cells to the current
  clock-only format. The store and export are outside Git under
  `C:\Users\NicholasSisco\Documents\Site_timing_analysis_store`.

Remaining completion criteria:

- Integrate an explicit cache lookup/reuse path into Timeline Analysis without
  weakening discovery, source identity, validation, or publication gates.
- Generate broader reports and site comparisons from stable SQL views/exports.
- Validate cache invalidation across multiple sites and changed source, parser,
  and configuration fingerprints before marking TODO #6 complete.

## 7. Profile and optimize the pipeline

**Rationale:** The reconciled profiler now accounts for total wall time, but
controlled follow-up measurements are needed before choosing optimizations.

- Continue measuring startup, preflight, discovery, database work, event/state
  processing, artifact writes, plotting, validation, reporting, and shutdown.
- Distinguish computation from database and filesystem I/O using wall time,
  process CPU time, row/event counts, and output file/byte metrics.
- Benchmark targeted changes on the same representative case manifest,
  including plot suppression, reduced intermediate artifacts where contracts
  safely permit it, local staging, and cached database resolution.
- Preserve case selection, source-database handling, publication gates, detailed
  interval truth, and public output contracts unless a change is separately
  approved.

**Completion criteria:** Nested timings reconcile to total wall time within the
documented tolerance; repeated comparable benchmarks identify stage and case
costs with percentages; every proposed optimization has measured before/after
results and output-parity checks; and the final recommendation distinguishes
CPU, database, and filesystem bottlenecks without committing generated outputs.
