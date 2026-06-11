# Site Timing Analysis

## Purpose
This repository is a staged Python refactor of the legacy R timing-analysis workflow.  
It ingests treatment audit logs (`local.db`), reconstructs workflow events/states/timing, and produces legacy-style timeline/Gantt outputs.

The target is parity of end-product behavior, not line-by-line R translation.

## Current Status
Implemented pipeline slices:

1. Discovery and DB source resolution
2. Ingestion and normalization
3. Enrichment (Sessions + optional timing-log CSV)
4. State reconstruction
5. Timing and rebasing
6. Plotting (normalized timeline and original-hour timeline)

Still pending:

- Summary/parity hardening (final rollups/checks against legacy outputs)

## Control-File Workflow
For any non-trivial work, read in this order:

1. `AGENTS.md` (rules/constraints)
2. `SOP.md` (operating workflow)
3. `ARCHITECTURE.md` (system/module boundaries)
4. `SESSION.md` (current checkpoint/handoff)

## Environment Setup (Mandatory)
All Python commands must use the repo-local `.venv` explicitly.

Do not use bare commands like `python`, `pip`, or `pytest`.

Use:

- `.\.venv\Scripts\python.exe`
- `.\.venv\Scripts\pip.exe`

Install dependencies:

```powershell
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\pip.exe install -r requirements-dev.txt
.\.venv\Scripts\pip.exe install -e .
```

## Run Tests
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Pytest is configured to discover the suite under `testing/tests`.

## Basic Pipeline Run
Current orchestrator is `site_timing_analysis.first_slice_cli` (name retained from early slice work).

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.first_slice_cli `
  --site Stanford_064 `
  --years 2025 `
  --root C:\path\to\site_root_parent `
  --output .\run_outputs
```

Optional timing-log override:

```powershell
.\.venv\Scripts\python.exe -m site_timing_analysis.first_slice_cli `
  --site Stanford_064 `
  --years 2025 `
  --root C:\path\to\site_root_parent `
  --output .\run_outputs `
  --timing-log-dir C:\path\to\TimingLogs
```

## Output Artifacts
The selected `--output` directory is treated as one run folder. New staged-pipeline
outputs use a unified layout:

- `manifests/run_manifest.json`
- `manifests/case_manifest.csv`
- `events/normalized/<case_id>_normalized_events.csv`
- `events/enriched/<case_id>_enriched_events.csv`
- `events/state_labeled/<case_id>_state_labeled_events.csv`
- `intervals/state/<case_id>_state_intervals.csv`
- `plots/timelines/normalized_timeline.png`
- `plots/timelines/original_hour_timeline.png`
- `tables/per_case_state_durations.csv`
- `tables/per_case_summary.csv`
- `reports/diagnostics_summary.md`
- `reports/workflow_summary/*.csv`
- `reports/workflow_summary/*.png`
- `scratch/db_extract/` for temporary copied/extracted databases

Readers for plot tables and workflow summaries still tolerate historical run
folders that used root-level `case_manifest.csv`, `state_intervals/`, and
`summary/` conventions.

## Legacy Reference
- Legacy R reference: `Legacy/r_reference/ReadAuditLogs.R`
- Parity checklist notes: `Legacy/PARITY_CHECKLIST.md`

## First Real-Data Trial: What To Check
For the first production-like run, verify:

1. `run_manifest.json` has expected case counts (`discovered`, `processed`, `failed`).
2. Failed cases are explained and actionable (missing DB, malformed timing logs, schema issues).
3. Warning fields are reviewed per case (`enrichment_warnings`, `state_warnings`, `timing_warnings`, `plot_warnings`).
4. `state_intervals` look plausible (no unexplained negative starts/durations).
5. Both plot artifacts are produced and visually consistent with expected treatment chronology.
6. At least one known legacy case is compared manually against prior R output for sanity.
