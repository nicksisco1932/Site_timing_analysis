## TULSA Timing Analysis Pipeline

Unified Python Pipeline for AuditLog Processing, Workflow State Mapping, and Timing Visualization

Overview

This repository contains the production-grade pipeline for extracting, reconstructing, and analyzing TULSA workflow timing from system AuditLogRecords.
The design emphasizes clarity, reproducibility, and modularity. All development and exploratory scripts are isolated under /testing for cleanliness.

The canonical workflow:

Collect audit logs
tulsa_collect_auditlogs.py builds a single auditlogs_<site>.csv from local.db records.

Map workflow states
tulsa_state_machine.py converts raw logs into state-segmented rows with durations.

Build timing summary
tulsa_build_timing_summary.py constructs unified patient-level timing tables, including intra-MRI totals and ProcedureTotal.

Visualization and QA

tulsa_plot_timing.py for stacked bar charts, distributions, and Gantt collection

tulsa_box_jitter.py for per-phase box-jitter plots

tulsa_trend_analysis.py for trends, variability, outliers, and JSON summaries

tulsa_gantt_plots.py for specialized Gantt layouts

Unified driver
tulsa_site_pipeline.py orchestrates the full pipeline end-to-end for a single site.

Directory Structure
/
├── tulsa_collect_auditlogs.py
├── tulsa_state_machine.py
├── tulsa_build_timing_summary.py
├── tulsa_plot_timing.py
├── tulsa_box_jitter.py
├── tulsa_trend_analysis.py
├── tulsa_gantt_plots.py
├── tulsa_site_pipeline.py
│
├── testing/
│   ├── tulsa_case_summary.py
│   ├── tulsa_timing.py
│   ├── tulsa_probe_localdb.py
│   ├── sanity.py
│   ├── sanity_states_by_pt.py
│   ├── run_me.bat
│   ├── run_site_analysis.bat
│   └── run_Stanford_064.bat
│
└── README.md

Standard Output Structure

Each run produces:

<AnalysisRoot>/<DATE>_<SITE_LABEL>/
    auditlogs_<site>.csv
    auditlogs_<site>_states.csv
    timing_summary_<site>.csv
    /plots/
        gantt_*.png
        stacked_*.png
        distributions_*.png
        jitter_*.png
    /stats/
        metrics.json
        outliers.csv
        trends.csv

Running the Unified Pipeline

Inside your virtual environment:

python tulsa_site_pipeline.py \
    --site Stanford_064 \
    --site-label Stanford \
    --years All \
    --date 20251119 \
    --trend-with-gantt


Key optional flags:

--skip-collect

--skip-states

--skip-summary

--skip-plots

--no-filter-outliers

--root <dir> to override Profound Medical root

--analysis-root <dir> to redirect all analysis output

Purpose of /testing

The /testing directory contains:

Legacy scripts

Prototypes

Diagnostics

Site-specific batch files

Temporary comparisons and sanity checks

Nothing in /testing is required for pipeline operation; they remain as references and tools for debugging or exploratory work.