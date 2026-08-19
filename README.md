# Site Timing Analysis

## Purpose

This repository supports internal retrospective timing analysis of clinical site
workflows and procedure events. It organizes, processes, summarizes, and plots
timing-related data so site performance, workflow bottlenecks, and procedural
timing patterns can be reviewed consistently.

This is an internal analysis repository. It is not treatment software, not a
clinical decision system, and not a regulatory-validated product.

## What This Repository Does

The current Python codebase contains two related workflow surfaces:

- A staged timing pipeline in `src/site_timing_analysis/` that discovers case
  data, reads `local.db` audit-log databases, normalizes events, enriches events
  from Sessions rows and optional timing-log CSV/XLSX files, reconstructs operational
  states, computes state intervals, and generates timeline plots.
- Legacy-compatible `tulsa_*` scripts and root-level wrappers that preserve the
  older script-oriented workflow for collecting audit logs, applying a state
  machine, building timing summaries, generating plots, and running QA checks.

Supported analysis outputs include case manifests, normalized/enriched/state
event tables, state intervals, diagnostics summaries, per-case timing tables,
workflow summaries, workflow tertiles, by-year rollups, site-comparison plots,
and standardized timing Gantt final deliverables.

## Repository Layout

```text
.
|-- AGENTS.md                 # Agent rules and source-provenance policy
|-- SOP.md                    # Standard operating procedure for repo work
|-- ARCHITECTURE.md           # Module boundaries and migration architecture
|-- SESSION.md                # Current handoff/status checkpoint
|-- TODO.md                   # Prioritized follow-up work
|-- README.md
|-- pyproject.toml
|-- requirements.txt
|-- requirements-dev.txt
|-- src/site_timing_analysis/ # Staged pipeline and legacy-compatible modules
|-- scripts/                  # Thin repo-local helper entry points
|-- docs/                     # Repository documentation; raw workbooks excluded
|-- testing/                  # Tests, smoke checks, and test fixtures
|-- Legacy/                   # Legacy R reference and archived notes
|-- outputs/                  # Generated analysis outputs, mostly ignored
|-- tulsa_*.py                # Root compatibility wrappers into src modules
`-- *.bat                     # Windows batch helpers for legacy workflows
```

Generated outputs, staged databases, exported data, and analysis artifacts should
stay out of source control unless repository governance explicitly says
otherwise.

## Installation

Use Python 3.12 or newer. Create the repo-local virtual environment once if it
does not already exist:

```powershell
py -3.12 -m venv .venv
```

After `.venv` exists, use explicit repo-local executables for all Python work:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\pip.exe install -r requirements-dev.txt
.\.venv\Scripts\pip.exe install -e .
```

Do not rely on an activated shell, and do not use bare `python`, `pip`, or
`pytest` commands when working in this repository.

## First-time setup and handoff

On Windows, the guided initializer can create the repository `.venv`, install
declared dependencies after confirmation, validate the command-line tools, and
generate a reusable site runner without editing a script:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  ".\scripts\initialize_timeline_analysis.ps1"
```

When `.venv` is absent, the bootstrap detects an available Python 3.12 or newer
interpreter; it does not require an exact Python 3.12 launcher registration and
never installs system Python or Git. Its checks cover the staged pipeline,
validated exporter, deliverable builder, analytical-store CLI, `pip check`, and
an optional full test suite.

The wizard asks for a three-digit site ID, finds exactly one Teams-synced site
directory under `%USERPROFILE%\Profound Medical`, inventories its canonical
case/database candidates read-only, and previews the selection. It can select
all canonical cases or an explicit case-list manifest. Optional roll-up and
read-only cache paths may be supplied; cache defaults to off and the wizard
never writes an analytical store.

Profiles and generated runners are per-user files outside Git:

```text
%LOCALAPPDATA%\Profound Medical\SiteTimingAnalysis\
|-- profiles\<site-code>.json
`-- runners\run_<site-code>.ps1
```

The generated runner creates a fresh collision-safe dated run directory each
time and prints the exact public CSV path. Sync.com credentials and acquisition
are intentionally separate; if local cases are missing, use the availability
and acquisition commands after completing this local analysis-first setup.

## CLI Usage

### Staged Timing Pipeline

Primary entry point:

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.first_slice_cli `
  --site "UCSD_109" `
  --years "All" `
  --root "C:\Users\NicholasSisco\Profound Medical" `
  --site-path "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - UCSD_109" `
  --output ".\outputs\timing_gantt\2026.03.20_UCSD_109_timing_Gantt" `
  --diagnostics
```

Required inputs are `--site`, `--root`, and `--output`. `--years` accepts `All`,
`CurrentYear`, `PastYears`, or a specific year. Use `--site-path` when the site
folder does not resolve as `<root>\<site>`.

Common optional arguments:

- `--timing-log-dir`: directory containing optional exact `<case_id>.csv` or
  `<case_id>.xlsx` timing logs. Missing case files are recorded as warnings and
  do not stop processing. See
  [`docs/TIMING_LOG_XLSX.md`](docs/TIMING_LOG_XLSX.md).
- `--allow-ambiguous-db`, `--db-candidate-index`, `--zip-member-index`:
  deterministic controls for ambiguous database discovery.
- `--diagnostics` and `--diagnostics-file`: write an operator-facing diagnostics
  summary.
- `--enable-tff-adapter`, `--tff-normalized-case-table`,
  `--tff-filter-known-exclusions`: optional read-only TFF metadata adapter.

### Validated Wide Timeline Export

Run the site-agnostic validator/exporter when the desired deliverable is one
wide CSV row per case with the operational-state columns:

```powershell
.\.venv\Scripts\python.exe scripts\run_timeline_analysis.py `
  --site "Stanford_064" `
  --site-root "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - Stanford_064" `
  --canonical-prefix "064_" `
  --timing-log-dir "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - Timing Data\TimingLogs" `
  --run-dir ".\outputs\timing_gantt\2026.08.10_Stanford_064_timing_Gantt"
```

Without `--case-list`, all discovered folders matching `--canonical-prefix` are
selected, except that ASUI_122 retains its built-in nine-case compatibility
allowlist. Use explicit `--select-all-canonical` to override that compatibility
default. Use `--case-list` for an explicit allowlist; it accepts case IDs or
full case-folder paths, one per line. Non-directory lines and noncanonical
folders are reported and excluded. The strict default treats additional
canonical folders as an abort condition; guided subset runners explicitly add
`--allow-unselected-canonical` so unselected canonical cases are reported as
excluded. Add `--rollup <path>` when a five-phase
roll-up comparator is available. The discovery count summary is calculated from
the folders found at runtime. The run gates on unique case IDs, valid
canonical-prefix selection, complete discovered-folder accounting, exactly one
usable database per selected case, and no duplicate processed cases.

Add `--profile` for temporary performance instrumentation. It writes
`Backend/reports/performance_summary.json` and
`Backend/reports/performance_by_case.csv` with ranked wall-clock stages/cases,
exclusive and inclusive nested timings, coverage reconciliation, process CPU
time, a non-CPU wall-time proxy, row/event/interval counts, uniquely owned
case/global output file and byte counts, warnings, and failures. To profile a
representative subset, pass a temporary `--case-list` containing three to five
case IDs; profiling is opt-in and does not otherwise change selection or
publication behavior. The
published layout is intentionally compact:

```text
<run-dir>/
|-- Backend/   # manifests, events, intervals, plots, diagnostics, staging
|-- Report/    # <site>_timeline_analysis.csv and validation report
|-- normalized_timeline.png
`-- original_hour_timeline.png
```

The two top-level PNGs are byte-identical published copies of the required
sources under `Backend/plots/timelines/`; the backend originals remain in place.

For ASUI_122, omitting `--case-list` uses the built-in nine-case allowlist. The
existing ASUI roll-up can be supplied with `--rollup` for reconciliation.

### Reusable preflight evidence

Every validated run performs the full live repository preflight by default. An
operator may capture that evidence once at an explicit path outside Git and
reuse it only while the execution identity remains exact:

```powershell
$snapshot = "$env:LOCALAPPDATA\Profound Medical\SiteTimingAnalysis\preflight\baseline.json"

.\.venv\Scripts\python.exe scripts\preflight_baseline.py capture `
  --output $snapshot

.\.venv\Scripts\python.exe scripts\run_timeline_analysis.py `
  --site "UCLA_008" `
  --site-root "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - UCLA_008" `
  --canonical-prefix "008_" `
  --baseline-mode reuse `
  --baseline-snapshot $snapshot `
  --run-dir ".\outputs\timing_gantt\<fresh-run-directory>"
```

Reuse defaults to a 24-hour maximum age and requires exact Git commit and dirty
contents, interpreter path/version/binary, installed dependencies, test command,
and successful gate results. A stale or mismatched snapshot aborts the run; it
is never silently accepted or refreshed. Each run retains the original evidence
plus reuse validation details in `Backend/reports/pre_execution_baseline.json`.

### Durable Timeline Analysis Store

Import validated run artifacts into the versioned cross-site SQLite store, then
recreate the public wide CSV from unrounded SQL-backed interval totals:

```powershell
$database = "C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite"
$wideExport = "C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\exports\asui_122_timeline_analysis.csv"

.\.venv\Scripts\python.exe scripts\timeline_store.py init `
  --database $database

.\.venv\Scripts\python.exe scripts\timeline_store.py import-run `
  --database $database `
  --run-dir ".\outputs\timing_gantt\2026.08.10_ASUI_122_timing_Gantt"

.\.venv\Scripts\python.exe scripts\timeline_store.py export-wide `
  --database $database `
  --run-id "34314961-6763-4682-b400-6627ff459d37" `
  --output $wideExport

.\.venv\Scripts\python.exe scripts\timeline_store.py list-runs `
  --database $database

.\.venv\Scripts\python.exe scripts\timeline_store.py export-long `
  --database $database `
  --run-id "<run-id>" `
  --output "C:\path\outside\Git\timeline_long.csv"

.\.venv\Scripts\python.exe scripts\timeline_store.py compare-runs `
  --database $database `
  --baseline-run-id "<baseline-run-id>" `
  --comparison-run-id "<comparison-run-id>" `
  --output "C:\path\outside\Git\run_comparison.csv"

.\.venv\Scripts\python.exe scripts\timeline_store.py summarize-runs `
  --database $database `
  --run-id "<run-id-1>" `
  --run-id "<run-id-2>" `
  --output "C:\path\outside\Git\run_summary.csv"

.\.venv\Scripts\python.exe scripts\relocate_timeline_store.py verify `
  --database $database `
  --output $wideExport `
  --run-id "34314961-6763-4682-b400-6627ff459d37" `
  --require-pinned
```

The database argument is always required. The store rejects locations inside
this repository or the imported run directory. Import validates the complete
artifact set before opening a write transaction, hashes source databases using
read-only file access, preserves failed cases from partial runs, and rejects a
reused run ID whose content changed. Reimporting identical content is a no-op.

Schema v2 records exact clinical-source and timing-log dependencies, including
an explicit absent timing-log marker, with parser, configuration, and cache-
contract fingerprints. Upgrade an existing schema-v1 store only while OneDrive
is stopped and every SQLite connection is closed:

```powershell
.\.venv\Scripts\python.exe scripts\timeline_store.py upgrade `
  --database $database `
  --confirm-onedrive-stopped `
  --cleanup-backup `
  --require-pinned
```

The validated runner can use the store as an explicit read-only exact cache:

```powershell
.\.venv\Scripts\python.exe scripts\run_timeline_analysis.py `
  --site "UCLA_008" `
  --site-root "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - UCLA_008" `
  --canonical-prefix "008_" `
  --database $database `
  --cache-mode read-only `
  --run-dir ".\outputs\timing_gantt\<new-run-directory>"
```

Cache mode defaults to `off`, and `read-only` requires `--database`; there is no
hidden OneDrive path or automatic store write. Source candidate resolution,
validation, and SHA-256 hashing occur before lookup. Exact hits recreate all
standard artifacts and continue through the normal identity, interval,
reconciliation, plotting, and publication gates. A corrupt case entry is
reported as `cache_entry_invalid` and parsed normally; a corrupt store aborts
cache-enabled execution. Seed new entries only with the separate explicit
`import-run` command. Schema-v1 analyses remain historical but cache-ineligible.

Detailed state intervals are the analytical source of truth. Full ISO endpoint
datetimes and their provenance remain queryable; `export-wide` applies only the
public boundary formatting: clock-only `h:mm:ss AM/PM` endpoints and one-decimal
state minutes. Imported wide rows are retained as parity snapshots, not as the
calculation source. Keep the clinical-derived store and its exports outside Git.

The path above is the sole operational store. Writable connections use SQLite
`DELETE` journaling, full synchronization, a bounded busy timeout, and an
immediate write transaction. This workstation is the only writer; synchronized
copies on other computers must remain closed or read-only. Keep the database
available locally through OneDrive's **Always keep on this device** setting.
OneDrive synchronization must be stopped during any future store relocation or
schema copy-up; use `scripts/relocate_timeline_store.py migrate --help` or
`scripts/timeline_store.py upgrade --help` for the explicit, non-overwriting
interfaces.

### Read-Only Site Availability and Case Parity

Before acquiring or analyzing a new site, check its configured Sync.com share
and Teams-synced local directory using only the three-digit site ID:

```powershell
Set-Location "C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis"

$site = "122"
& .\.venv\Scripts\python.exe .\scripts\check_site_availability.py --site $site
$LASTEXITCODE
```

The defaults are `tools\profoundtools\sites.json` for the ignored Sync registry
and `%USERPROFILE%\Profound Medical` for the local parent. Use `--sites-file` or
`--local-root` only when those locations differ. Add, for example,
`--report-json ".\outputs\availability\site_${site}.json"` for a sanitized
machine-readable report outside the Teams-synced tree.

The checker accepts exactly one remote root named `TDC Sessions` or `TDC Data`,
matches exact `<case-id> TDC Sessions` folders, skips `applog`, and inventories
only immediate timestamped session children and direct nonempty `local.db`
metadata. Locally, it resolves one immediate site directory ending in the site
ID and inventories canonical `<case-id>\local.db` paths. It never downloads,
extracts, stages, opens, hashes, copies, or modifies a database. Exit `0` means
complete canonical parity, `1` means both endpoints exist but differences
remain, and `2` means configuration, access, local-site, or remote-root failure.

### Single-Case Commercial `local.db` Acquisition Test

This isolated test retrieves one `local.db` from one explicitly selected case.
It matches the exact `<case-id> TDC Sessions` folder, ignores `applog`, inspects
timestamped session-folder children, and prefers one direct case-insensitive
`local.db` match. It does not change the existing ProfoundTools `applog`
workflow or write to the source share.

The required `sync-tdc-logs` transport is available locally at
`tools\profoundtools`. This is a preserved snapshot of the ProfoundTools
`Python/sync-tdc-logs` component; Timeline Analysis imports it as a transport
without changing its existing planner or `applog` behavior.

Install the optional transport dependencies into the repo-local environment:

```powershell
.\.venv\Scripts\pip.exe install -e ".[acquisition]"
```

Keep the credential-bearing `sites.json`, downloaded database, and result report
outside Git. Store or replace the shared Sync.com password in Windows Credential
Manager using the concealed ProfoundTools setup prompt:

```powershell
& .\scripts\setup_sync_credential.ps1
```

Running setup again replaces the existing entry for the current Windows user.
To remove the entry, run `& .\scripts\setup_sync_credential.ps1 -Forget`. Never
place the password or full share URL on the command line or in a committed file.

```powershell
.\.venv\Scripts\python.exe scripts\test_single_case_localdb_acquisition.py `
  --site "122" `
  --case-id "122_01-001" `
  --sites-file ".\tools\profoundtools\sites.json" `
  --sync-tool-root ".\tools\profoundtools" `
  --destination "C:\path\outside\git\single_case_acquisition_test"
```

The command requires exactly one exact case folder and one valid timestamped
session-folder database candidate. Missing, multiple, conflicting, or unexpected
folders and files are quarantined rather than guessed through. Add
`--allow-session-zip-fallback` to inspect exactly one non-`Raw.zip` session
export only when no direct database exists. Downloads pass through staging;
size, SHA-256, SQLite integrity, required tables, relationship columns, and
orphan links are validated before publication as
`<destination>\<case-id>\local.db`. The exact saved or quarantine path is
printed and recorded in a JSON result report.

### Five-Case Commercial Acquisition Validation

After the single-case gate succeeds, validate at least five unique, explicit
cases with one read-only connection:

```powershell
.\.venv\Scripts\python.exe scripts\test_multi_case_localdb_acquisition.py `
  --site "122" `
  --case-id "122_01-001" `
  --case-id "122_01-002" `
  --case-id "122_01-003" `
  --case-id "122_01-004" `
  --case-id "122_01-005" `
  --sites-file ".\tools\profoundtools\sites.json" `
  --sync-tool-root ".\tools\profoundtools" `
  --destination "C:\path\outside\git\five_case_acquisition_test"
```

The command requires five or more unique case IDs using the selected site
prefix. Each case independently passes the single-case folder/database gates
plus required internal case-identity verification. It continues after a case
failure so the aggregate JSON and Markdown summaries classify every requested
case as success, failure, or quarantine. Outputs are written beneath the
external destination, including `_reports\acquisition_summary.json` and
`_reports\acquisition_summary.md`. This is a validation tool, not the resumable
bulk acquisition workflow planned in TODO #4.

### Resumable Bulk Commercial Acquisition

Create a UTF-8 text manifest containing one explicit case ID per line, then run:

```powershell
.\.venv\Scripts\python.exe scripts\acquire_localdb_bulk.py `
  --site "122" `
  --case-manifest "C:\path\outside\git\asui_122_cases.txt" `
  --sites-file ".\tools\profoundtools\sites.json" `
  --sync-tool-root ".\tools\profoundtools" `
  --destination "C:\path\to\clean\ASUI_122" `
  --backend-dir ".\outputs\acquisition\ASUI_122\Backend"
```

Alternatively, repeat `--case-id` for every selected case. The command never
discovers an implicit bulk selection. It requires unique case IDs using the
selected site prefix and preserves the established
`<destination>\<case-id>\local.db` structure.

The required `--backend-dir` must be outside the final destination. The final
destination remains limited to `<case-id>\local.db`; technical records are kept
beneath the backend:

```text
Backend/
|-- _staging/
|-- _quarantine/
`-- _acquisition/
    |-- inventory.json
    |-- inventory.csv
    |-- acquisition.lock
    `-- runs/<run-id>/
        |-- run_report.json
        |-- run_report.md
        |-- case_results.csv
        `-- cases/<case-id>_acquisition.json
```

Inventory is checkpointed after every case. A valid existing database without
inventory is reported and skipped locally, with `remote_content_not_compared`
recorded; it is never silently ignored or overwritten. Use
`--verify-and-adopt-existing` when an exact fresh remote download/hash comparison
is required to establish its first verified inventory record. Once verified,
reruns reuse it only when local validation/hash, prior inventory, and current
remote path/size/modification metadata all agree. Interrupted staging files are
moved to backend quarantine before retry. Case failures are isolated, and the
backend lock prevents concurrent runs. When `PatientId` is unavailable, required
download identity may fall back only to an unambiguous match between the sole
internal `Sessions.Start` and the exact selected session-folder timestamp within
two seconds.
Add `--allow-session-zip-fallback` only when the operator intends to permit the
same ambiguity-safe non-`Raw.zip` fallback validated by the smaller runners.

### Standardized Timing Gantt Deliverables

Build human-facing final deliverables from existing timing Gantt run folders:

```powershell
.\.venv\Scripts\python.exe scripts\build_timing_gantt_deliverables.py `
  --timing-root ".\outputs\timing_gantt"
```

This post-processing layer reads existing run artifacts and writes standardized
`final/` folders, top-level timing Gantt README/index files, audit reports, and
validation summaries. It does not delete, move, or overwrite raw reconstruction
outputs.

### Plot-Source Tables

Export numeric tables behind timeline plots for a completed run:

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.plot_tables `
  --run-dir ".\outputs\timing_gantt\<run_folder>"
```

Expected outputs include `tables/per_case_state_durations.csv` and
`tables/per_case_summary.csv`.

### Workflow Summaries

Create summary, chronological tertile, or calendar-year workflow rollups:

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.workflow_summary `
  --run-dir ".\outputs\timing_gantt\<run_folder>" `
  --site-id "UCSD_109" `
  --mode tertiles
```

Supported `--mode` values are `summary`, `tertiles`, and `by-year`.

### Site Comparison

Create anonymized two-site state-duration comparison artifacts:

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.site_comparison `
  --site-a-intervals ".\outputs\timing_gantt\<run_a>\intervals\state" `
  --site-b-intervals ".\outputs\timing_gantt\<run_b>\intervals\state" `
  --outdir ".\outputs\comparisons\<comparison_name>"
```

The comparison exporter writes an anonymized summary CSV plus PNG/PDF plots.

### Legacy-Compatible Site Pipeline

The root `tulsa_*.py` files are compatibility wrappers that delegate into
matching modules under `src/site_timing_analysis/`. The broad site-level wrapper
is:

```powershell
.\.venv\Scripts\python.exe .\tulsa_site_pipeline.py `
  --site "Stanford_064" `
  --years "All" `
  --analysis-root ".\outputs\timing_gantt" `
  --trend-with-gantt
```

Use this surface when comparing against the older script workflow. Prefer the
staged package entry points for new pipeline work.

## Typical Workflow

1. Confirm source data are available locally and should be used for internal
   retrospective analysis.
2. Run `site_timing_analysis.first_slice_cli` for one site/run folder.
3. Review `manifests/`, `reports/diagnostics_summary.md`, and interval warning
   fields for ingestion or timing anomalies.
4. Review generated timeline plots and per-case tables.
5. Run `scripts/build_timing_gantt_deliverables.py` to create the standardized
   `final/` deliverables and top-level timing Gantt index.
6. Archive outputs with clear date/site/run identifiers under `outputs/`.

## Inputs

The staged pipeline expects local site data, not uploaded data. Confirmed inputs
include:

- Case-level SQLite databases named `local.db`, either directly available or
  inside archives discovered by the DB source resolver.
- Required `AuditLogRecords` table data.
- Optional `Sessions` table data used for synthetic timing-event enrichment.
- Optional timing-log CSV or XLSX files named exactly `<case_id>.csv` or
  `<case_id>.xlsx`.
- Site and case identifiers inferred from the site folder/case folder structure
  and/or manifest rows.

The pipeline treats source databases as read-only. When a synced or archived DB
cannot be opened in place, staged copies may be made inside the run output
scratch area for analysis.

## Outputs

The selected `--output` directory is one run folder. Current staged-pipeline
outputs use this unified layout:

```text
manifests/run_manifest.json
manifests/case_manifest.csv
events/normalized/<case_id>_normalized_events.csv
events/enriched/<case_id>_enriched_events.csv
events/state_labeled/<case_id>_state_labeled_events.csv
intervals/state/<case_id>_state_intervals.csv
plots/timelines/normalized_timeline.png
plots/timelines/original_hour_timeline.png
tables/per_case_state_durations.csv
tables/per_case_summary.csv
reports/diagnostics_summary.md
reports/workflow_summary/*.csv
reports/workflow_summary/*.png
scratch/db_extract/
```

Historical run folders may still contain root-level `case_manifest.csv`,
`state_intervals/`, `plots/`, `tables/`, or `summary/` directories. Reader
utilities generally tolerate both the current layout and those historical paths.

Standardized timing Gantt final deliverables are written under:

```text
outputs/timing_gantt/<run_folder>/final/
outputs/timing_gantt/<run_folder>/final/plot_data/
outputs/timing_gantt/final_index.csv
outputs/timing_gantt/audit_report.md
outputs/timing_gantt/validation_summary.md
```

## Data Governance and Privacy

This repository is intended for internal retrospective analysis. Do not commit
patient-identifiable data, exported clinical datasets, DICOM-derived outputs,
logs containing protected health information, or site-specific confidential data
unless the repository governance explicitly permits it.

Source databases and generated analysis outputs should generally remain local
and ignored by git. When sharing results, prefer sanitized summaries and
attributable, reproducible output folders.

## Provenance

Source files include provenance headers identifying Nicholas J. Sisco, Ph.D. as
primary author or material implementer where appropriate, with Profound Medical,
LLC as the organizational/proprietary context. Existing source headers and
third-party or legacy author notices must be preserved.

AI tools are not listed as source-file authors. Keep provenance headers intact
when editing source files, and add the standard header to new maintained source
files.

## Testing And Validation

Run the test suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Pytest discovery is configured for `testing/tests`. Focused validation commands
can target individual areas, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest testing\tests\test_timing_gantt_deliverables.py -q
.\.venv\Scripts\python.exe -m pytest testing\tests\test_workflow_summary.py -q
```

For quick CLI smoke checks:

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.first_slice_cli --help
.\.venv\Scripts\python.exe scripts\run_timeline_analysis.py --help
.\.venv\Scripts\python.exe scripts\build_timing_gantt_deliverables.py --help
.\.venv\Scripts\python.exe scripts\timeline_store.py --help
.\.venv\Scripts\python.exe scripts\timeline_store.py upgrade --help
.\.venv\Scripts\python.exe scripts\timeline_store.py export-long --help
.\.venv\Scripts\python.exe scripts\timeline_store.py compare-runs --help
.\.venv\Scripts\python.exe scripts\timeline_store.py summarize-runs --help
.\.venv\Scripts\python.exe scripts\relocate_timeline_store.py --help
.\.venv\Scripts\python.exe scripts\initialize_timeline_analysis.py --help
.\.venv\Scripts\python.exe scripts\preflight_baseline.py --help
```

See `SESSION.md` for the latest known validation status and any currently
tracked legacy test failures.

## Maintenance Notes

- Keep generated data, raw databases, exported reports, caches, and output
  folders out of git unless explicitly approved.
- Keep raw workbooks outside the repository; `docs/*.xlsx` is ignored by policy.
- Keep integration fixtures synthetic. `testing/synthetic_test_db.py` creates
  the disposable SQLite fixture used by the legacy-compatible smoke path.
- Keep source provenance headers intact.
- Update CLI examples when entry points or argument names change.
- Prefer reproducible scripted analysis over manual spreadsheet edits.
- Preserve legacy behavior during refactors until parity expectations are
  explicitly changed.
- Update `SESSION.md` after material workflow, architecture, or validation
  changes.
