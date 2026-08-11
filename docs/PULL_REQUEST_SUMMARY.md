# Timeline Analysis Cleanup — Reviewer Summary

## Why

This change set stabilizes the Timeline Analysis workflow, makes the validated
wide export reusable across sites, and removes repository data and generated
artifacts that should not be versioned. It preserves the staged pipeline and
legacy wrappers while improving reproducibility, auditability, and headless
execution.

## What changed

- Added a site-agnostic validated timeline runner that separates discovery from
  selection, enforces semantic case/database/identity/interval gates, and writes
  the human-facing CSV under `Report/` with technical artifacts under `Backend/`.
- Preserved the 20-column wide CSV contract. `starttime` and `endtime` are
  clock-only `h:mm:ss AM/PM` values; full ISO datetimes and endpoint provenance
  remain in the audit report.
- Added optional nested performance profiling with exclusive/inclusive stage
  timings, per-case metrics, unique artifact ownership, and wall-time
  reconciliation.
- Kept default discovery behavior unchanged while allowing explicit extra
  prefixes for the known TFF exclusion path.
- Made legacy plotting headless, replaced the deprecated matplotlib boxplot
  argument, declared `openpyxl`, and made batch helpers use the repo-local
  virtual environment explicitly.
- Added standardized timing-Gantt deliverable tooling and updated the operator,
  architecture, session, changelog, and provenance documentation.
- Added an isolated, explicit single-case commercial `local.db` acquisition
  test using the repository-local ProfoundTools Sync transport and Windows
  Credential Manager. It follows the verified case/session hierarchy, ignores
  `applog`, quarantines ambiguity, validates SQLite before publication, and
  keeps credentials and acquired data outside Git.
- Removed committed Python bytecode, two duplicate clinical-derived SQLite
  fixtures, and their tracked generated CSV/PNG validation outputs. Integration
  tests now create a deterministic, minimal, non-clinical SQLite fixture at run
  time.

## Important behavior and contracts

- Existing staged-pipeline schemas and legacy wrapper behavior remain
  compatible unless explicitly described above.
- Default case discovery is unchanged. The validated exporter derives folder
  counts at runtime and gates on unique IDs, canonical-prefix selection,
  complete discovery accounting, exactly one usable database per selected case,
  and no duplicate processed cases.
- Detailed unrounded state intervals remain the analytical source of truth.
  Optional five-phase roll-ups are validation comparators only.
- Final publication remains gated; partial output is clearly identified and is
  available only when the operator explicitly requests partial publication.
- Source clinical databases are read-only. Profiling is opt-in and does not
  alter case selection, database resolution, output schemas, or publication
  gates.

## Validation

- Full pytest suite after the completed acquisition slice: `130 passed`.
- Focused single-case acquisition regression: `16 passed`.
- Synthetic SQLite pipeline regression: `3 passed`.
- CLI help checks passed for the staged pipeline, validated wide exporter, and
  timing-Gantt deliverable builder.
- `pip check`: no broken requirements.
- `git diff --check`: no whitespace errors; Git reports only expected Windows
  LF/CRLF conversion notices.
- The four-case profiling benchmark reconciled more than `99.99%` of total wall
  time. Disabling plots reduced the measured run by `10.81%` while preserving an
  identical final CSV.

## Data-integrity evidence

- The existing 2026.03.19 ASUI roll-up remains unchanged at SHA-256
  `81E3C37C1F05A3999974D381DE71DF32C28FC4F63B630DEA1DE9EC79EC64B546`.
- Existing ASUI and Stanford run integrity reports recorded `PASS` for every
  source database actually ingested. A live size/modified-time comparison found
  zero mismatches across those source paths during this housekeeping pass.
- No source clinical database, raw workbook, profiling output, or generated
  timeline output is included in the proposed source-control changes.
- Live acceptance case `122_01-001` passed immutable read-only SQLite integrity,
  schema, relationship, size, SHA-256, report-sanitization, and post-download
  source-presence checks. Its database and report were written outside Git.

## Known limitations and follow-up work

- Timing-log enrichment supports CSV, not `.xlsx`.
- Intermediate diagnostic CSV suppression is not supported because those files
  are part of the current staged artifact contract.
- The current Stanford run contains 148 processed cases and one pre-ingestion
  quarantine (`064_01-039`, no usable database candidate); it was explicitly
  published as partial and is not a complete 149-case deliverable.
- Formal R-output parity, a durable analytical database, and further measured
  optimization remain separate follow-up work in `TODO.md`.
- Multi-case acquisition remains dependency-gated behind the explicit five-case
  validation in TODO #3; scalable bulk acquisition has not been implemented.
