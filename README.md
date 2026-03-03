# Site Timing Analysis

Python pipeline for reconstructing TULSA workflow timelines from `local.db`
audit logs and producing legacy-style timing summaries and Gantt plots.

The target is the legacy end product, not the legacy implementation:
the source of truth should be the Python pipeline under `src/`.

## Layout

```text
.
|-- src/
|   `-- site_timing_analysis/
|       |-- tulsa_collect_auditlogs.py
|       |-- tulsa_state_machine.py
|       |-- tulsa_build_timing_summary.py
|       |-- tulsa_plot_timing.py
|       |-- tulsa_gantt_plots.py
|       |-- tulsa_trend_analysis.py
|       |-- tulsa_time_sanity.py
|       |-- tulsa_time_cutoff.py
|       |-- tulsa_day_simulation.py
|       |-- tulsa_timebase.py
|       `-- tulsa_workflow.py
|-- Legacy/
|   `-- ReadAuditLogs.R
|-- testing/
|   |-- smoke_test_test_data.py
|   |-- sanity.py
|   |-- sanity_states_by_pt.py
|   `-- legacy prototype scripts
|-- test_data/
|   `-- local.db
|-- requirements.txt
|-- pyproject.toml
|-- tulsa_*.py
`-- *.bat
```

## What Lives Where

- `src/site_timing_analysis/`
  Actual implementation code.

- `tulsa_*.py` in the repo root
  Thin compatibility entrypoints. Existing commands and batch files still work,
  but the real code lives under `src/`.

- `Legacy/`
  Reference-only R code. Keep for comparison and historical behavior checks.

- `testing/`
  Smoke checks, diagnostics, and older prototype utilities.

- `test_data/`
  Local test fixtures. `test_data/local.db` is the current real-case smoke-test
  database.

## Install

Use the repository virtual environment or install into your own environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Optional editable install for the `src/` package:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

## Main Workflow

Run the full site pipeline:

```powershell
.\.venv\Scripts\python.exe tulsa_site_pipeline.py `
  --site Stanford_064 `
  --site-label Stanford `
  --years All `
  --date 20260303
```

Run the real-case smoke test against `test_data/local.db`:

```powershell
.\.venv\Scripts\python.exe testing\smoke_test_test_data.py
```

That smoke test currently validates:

- direct `local.db` ingestion
- state reconstruction
- timing summary generation
- time sanity output
- Gantt plot generation

## Current Pipeline Stages

1. `tulsa_collect_auditlogs.py`
   Collects `AuditLogRecords` into `auditlogs_<site>.csv`.

2. `tulsa_state_machine.py`
   Reconstructs persistent workflow states and computes relative timing columns.

3. `tulsa_build_timing_summary.py`
   Aggregates patient-level timing tables.

4. `tulsa_plot_timing.py`
   Produces stacked plots, histograms, and a Gantt driven from state rows.

5. `tulsa_gantt_plots.py`
   Produces summary-based Gantt plots from timing-summary columns.

6. `tulsa_trend_analysis.py`
   Produces trend and variability outputs.

## Notes

- The Python pipeline is organized around Gantt-ready workflow reconstruction.
- Some legacy sites may still require extra enrichment beyond `AuditLogRecords`
  and `Sessions`, such as timing-sheet-derived boundaries.
- `test_output/` is ignored and intended for generated smoke-test artifacts.
