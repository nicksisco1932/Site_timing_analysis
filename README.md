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
  from Sessions rows and optional timing-log CSVs, reconstructs operational
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

- `--timing-log-dir`: directory containing optional `<case_id>.csv` timing logs.
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
  --run-dir ".\outputs\timing_gantt\2026.08.10_Stanford_064_timing_Gantt"
```

Without `--case-list`, all discovered folders matching `--canonical-prefix` are
selected. Use `--case-list` for an explicit allowlist; it accepts case IDs or
full case-folder paths, one per line. Non-directory lines and noncanonical
folders are reported and excluded. Add `--rollup <path>` when a five-phase
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
`-- Report/    # <site>_timeline_analysis.csv and validation report
```

For ASUI_122, omitting `--case-list` uses the built-in nine-case allowlist. The
existing ASUI roll-up can be supplied with `--rollup` for reconciliation.

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
- Optional timing-log CSV files, normally named `<case_id>.csv`.
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
