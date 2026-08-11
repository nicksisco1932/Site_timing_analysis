# Timeline Analysis TODO History

This archive preserves completion evidence for TODOs #1 through #5. The active
work list remains in [`TODO.md`](../TODO.md).

## 1. Standard GitHub housekeeping — Completed 2026-08-10

The repository branch, recent commits, and complete diff from reviewed baseline
`92f6ec9` were classified for reviewer scope. Temporary profiling runs,
generated validation artifacts, committed bytecode, and duplicate tracked
SQLite fixtures were removed. Integration tests now create a deterministic,
non-clinical SQLite fixture at runtime.

Validation at completion included 114 passing tests, CLI help checks,
`pip check`, and `git diff --check`. `docs/PULL_REQUEST_SUMMARY.md` records the
reviewer-facing rationale, behavior changes, contracts, validation, and known
limitations. The 2026.03.19 ASUI roll-up remained unchanged at SHA-256
`81E3C37C1F05A3999974D381DE71DF32C28FC4F63B630DEA1DE9EC79EC64B546`,
and live integrity records found no source-database changes across the ASUI and
Stanford cases actually ingested.

## 2. Single-case `local.db` acquisition — Completed 2026-08-11

The isolated acquisition CLI follows the verified Sync.com hierarchy:

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

It requires an explicit site/case, inspects immediate timestamped session
children, prefers one direct case-insensitive `local.db`, quarantines ambiguity,
uses ZIP fallback only when requested, keeps `applog` untouched, validates
SQLite read-only, and publishes `<destination>\<case-id>\local.db`.

Live case `122_01-001` downloaded successfully. The 11,608,064-byte database
had SHA-256
`BBB5044A982075FDF31E60B14EEA93A0DDB1CDE04D8DC1716B788A13D24DCD99`,
integrity `ok`, all required tables, and no treatment/session relationship
orphans. The command printed the exact saved path and wrote a sanitized JSON
report without credentials or signed tokens. Focused acquisition tests reported
16 passing tests; the repository suite reported 130.

## 3. Five-case acquisition validation — Completed 2026-08-11

Cases `122_01-001` through `122_01-005` were acquired in 94.7 seconds using
exact case/session matching. Results were 5 successes, 0 failures, and 0
quarantines, with no ZIP fallback. Every file used the expected case-specific
layout and independently passed immutable SQLite integrity, required-schema,
relationship, case-identity, size, and SHA-256 checks.

Five case reports plus machine-readable and human-readable summaries were
written outside Git. A post-run remote listing matched every recorded source
size and modification timestamp, and `applog` was never traversed. Focused
acquisition tests reported 23 passing tests; the repository suite reported 137.

## 4. Scalable bulk `local.db` acquisition — Completed 2026-08-11

`scripts/acquire_localdb_bulk.py` requires exactly one explicit selection
mechanism: repeated case IDs or a UTF-8 manifest. It reuses the validated
case/session/database logic, supports opt-in ZIP fallback, validates database
identity and integrity, and keeps the clean case destination separate from a
required backend containing inventory, reports, staging, and quarantine.

Reruns reuse a database only when validation, path, size, SHA-256, prior
inventory, and current remote metadata agree. Valid local databases without
inventory are reported as local-only skips and are never overwritten or
misrepresented as remote-equivalent. A process lock and recoverable staging
quarantine make runs resumable.

A synthetic 25-case scale run downloaded all files once and reused all 25 on an
identical rerun. The corrected live ASUI run completed with 19 successes, 0
failures, and 0 quarantines: 5 downloads, 11 inventory-verified reuses, and 3
reported local-only skips. All acquisition bookkeeping resides under the
Git-ignored backend, not the shared sanitized site root. Focused acquisition
tests reported 39 passing tests; the repository suite reported 153.

## 5. Site availability and case parity — Completed 2026-08-11

`scripts/check_site_availability.py --site <three-digit-id>` inventories the
configured Sync.com share and one Teams-synced local site directory read-only.
It accepts exactly one remote `TDC Sessions` or `TDC Data` root, never traverses
`applog`, inventories only immediate case/session children, reports canonical
and noncanonical folders separately, and never downloads, extracts, stages, or
opens remote database contents.

The command reports matched, remote-only, local-only, missing, duplicate, and
ambiguous database cases. Exit `0` means complete parity, `1` means both
endpoints exist with differences, and `2` means configuration, access,
missing-site, or root ambiguity failure. Optional JSON output is sanitized.

Focused regression reported 18 passing tests across endpoint, authentication,
root ambiguity, local-site ambiguity, parity, database, noncanonical-folder,
sanitization, and no-mutation cases. The live site-122 check returned exit `0`
with 19 remote canonical cases, 19 local canonical cases, and 19 complete
matches; noncanonical folders were reported separately. The repository suite
reported 171 passing tests.

## 6. Durable analytical database — Completed 2026-08-11

Schema v1 established the explicit cross-site store, immutable source/parser/
configuration history, canonical events, unrounded detailed intervals, endpoint
provenance, validation, reconciliation, and SQL-backed 20-column export. The
sole operational store was relocated safely to the locally pinned OneDrive
`Documents\10_Databases` directory with `DELETE` journaling and a one-workstation
writer rule.

Schema v2 was applied by validated copy-up migration and records exact clinical
source/ZIP-member and timing-log dependencies, including explicit absence,
plus parser, configuration, and cache-contract fingerprints. The validated
runner now supports opt-in `--cache-mode read-only --database <path>`; default
behavior remains cache-off and imports remain a separate explicit command.
Exact hits reconstruct normalized, enriched, labeled, interval, plot, report,
and public artifacts through the standard writers and gates. Corrupt entries
fall back to normal parsing with `cache_entry_invalid` diagnostics.

Live ASUI acceptance produced 9/9 hits and live UCLA acceptance produced 5/5
hits. Their public CSVs, event/interval artifacts, plots, and reconciliation
artifacts were byte-identical to uncached runs, and source hashes, sizes, and
modification times were unchanged. SQL `export-long`, `compare-runs`,
`summarize-runs`, and wide exports reconciled to stored detailed intervals;
the ASUI comparison contained 135 zero-difference rows. The canonical store
remained integrity-clean, foreign-key-clean, pinned, and free of WAL/SHM files
after OneDrive resumed.
