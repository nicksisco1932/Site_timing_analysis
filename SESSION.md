# SESSION.md

## Project

Site Timing Analysis (legacy R -> staged Python pipeline)

## Current Objective

Harden parity and warning behavior after broad real-data trial on the full site profile.

## Governing Files

1. `AGENTS.md`
2. `SOP.md`
3. `ARCHITECTURE.md`
4. `SESSION.md`

## Implemented Work

- First foundation slice is implemented under `src/site_timing_analysis/`:
- `config.py`, `discovery.py`, `db_source.py`, `ingestion.py`, `normalization.py`, `manifest.py`
- typed models/errors and `first_slice_cli.py` orchestration
- exports: `run_manifest.json`, `case_manifest.csv`, per-case normalized events CSV
- focused tests for first slice added and passing
- Enrichment slice is implemented:
- `timing_log.py` (optional timing-log discovery/parsing, CSV-only)
- `enrichment.py` (session-derived + timing-log-derived synthetic events, deterministic merge)
- per-case enriched export: `enriched_events/<case_id>_enriched_events.csv`
- per-case enrichment warnings captured in case results and run manifest warnings
- State reconstruction slice is implemented:
- `state_machine.py` deterministic event-to-state assignment on enriched streams
- explicit cleanup rules with per-row attribution in `cleanup_rule_applied`
- per-case state-labeled export: `state_labeled_events/<case_id>_state_labeled_events.csv`
- state-assignment anomalies captured per case and aggregated to run warnings
- Timing/rebasing slice is implemented:
- `timing.py` deterministic interval computation from state-labeled events
- explicit rebase-anchor selection (`InitialImaging`, `LastUAHoming`, `Alignment`, explicit fallback)
- per-case interval export: `state_intervals/<case_id>_state_intervals.csv`
- interval/rebase anomalies captured via `quality_flags`, per-case timing warnings, and run-level warnings
- Plotting slice is implemented:
- `plotting.py` generates legacy-style timeline artifacts from `state_intervals` only
- canonical state display order + canonical color map are centralized and shared by both plots
- exports: `plots/normalized_timeline.png`, `plots/original_hour_timeline.png`
- plotting warnings (unknown states, exclusions, midnight crossing, quality-flag presence) captured per case and run-level
- repository control-flow docs aligned to consistent read order
- Broader controlled real-data trial executed on 2026-03-11 across full site discovery (141 discovered / 140 processed / 1 skipped no DB) with full artifact generation under `run_outputs_broader_20260311/`.
- Interval hardening slice implemented (2026-03-11):
- explicit `case_end_inferred` / `case_end_ambiguous` handling in `timing.py`
- large-gap hardening threshold set to `7200` seconds
- terminal-sensitive and `<NA>` interval truncation flags added
- hardened full-site rerun outputs generated under `run_outputs_broader_20260311_hardened/`
- outlier reduction observed: `>7200 sec` from `54 -> 9`, `>14400 sec` from `42 -> 2`, affected cases `37 -> 8`
- Residual outlier cleanup slice implemented (2026-03-11):
- targeted early-state long-gap hardening for `Room ready`, `TULSA QA`, `Patient positioning & induction`
- explicit flag/warning added: `interval_early_state_truncated`
- negative rebased-start warning triage added for expected pre-anchor negatives
- residual full-site rerun outputs generated under `run_outputs_broader_20260311_residual/`
- additional reduction observed: `>7200 sec` from `9 -> 0`, `>14400 sec` from `2 -> 0`, negative-rebased warnings from `5497 -> 8`
- Diagnostics CLI slice implemented (2026-03-11):
- new CLI options: `--diagnostics` and optional `--diagnostics-file`
- operator-facing markdown summary emitted after run (`diagnostics_summary.md` by default)
- diagnostics includes run totals, interval-threshold counts, required quality-flag counts, warning summary, and artifact presence
- full test suite remains green after diagnostics wiring
- Normalized plot axis-windowing hardening implemented (2026-03-11):
- normalized timeline x-axis now uses deterministic 1st/99th percentile bounds of interval start/end values with a 300-second margin
- applied only to normalized timeline rendering; interval data is unchanged

## Not Yet Implemented

- summary generation
- parity diff engine beyond basic manifest/count checks

## Current Blocker

No hard runtime blocker in interval construction. Remaining blocker is parity-hardening and warning-tiering decisions before broader operational rollout.

## Recent Decisions

- Keep migration staged: state reconstruction implemented without duration/rebasing logic.
- Keep migration staged: timing/rebasing implemented without summary or plotting logic.
- Keep migration staged: plotting implemented without summary/statistical logic.
- Governance update: all Python execution must use explicit repo-local `.venv` paths; no bare `python`/`pip`/`pytest` commands.
- Handoff docs refreshed: README now reflects current staged pipeline, outputs, and first real-data trial checks.
- Controlled real-data validation pass executed on 5-case subset (2026-03-11) with full artifact-stage inspection.
- Sentinel-session fix implemented: `0001-01-01 00:00:00`-style session defaults are ignored for synthetic event creation with explicit warnings.
- Controlled rerun on the same 5-case subset (2026-03-11) confirms sentinel-driven extreme interval/rebasing artifacts are materially resolved.
- Broader full-site trial (2026-03-11) confirmed end-to-end artifact production is stable with no hard failures, but warning volume is high and requires targeted hardening before wider operational use.
- Interval hardening policy adopted in timing slice:
- infer case-end from last meaningful state-bearing event
- truncate large gaps (`>7200s`) for terminal/unassigned/tail-spill intervals
- emit explicit hardening provenance flags (`interval_truncated_large_gap`, `interval_terminal_state_clamped`, `interval_unassigned_state_truncated`)
- Residual cleanup policy adopted in timing slice:
- truncate sparse early-state long gaps for `Room ready`, `TULSA QA`, `Patient positioning & induction` with explicit provenance (`interval_early_state_truncated`)
- preserve negative rebased starts as a quality flag but emit warnings only for unexpected/extreme cases
- Add operator diagnostics surface in CLI so full-run validation can emit reproducible run-health summaries without custom post-processing scripts.
- Use typed exceptions for ambiguous DB resolution and missing required tables.
- Present malformed timing-log files fail loudly with `TimingLogParseError`; absent timing-log files are non-fatal.
- Default timing-log location is `<resolved_site_root>/TimingLogs/<case_id>.csv`.
- Raw normalized/enriched inputs are treated as immutable; derived rows are emitted as new artifacts.
- Keep `SESSION.md` as the canonical checkpoint file for cross-session continuity.

## Known Issues

- Existing legacy and prototype scripts remain in repo and are intentionally not part of first-slice control flow.
- `local2.db` append behavior is not included in the first slice.
- Timing-log support is CSV-only in current enrichment slice (`.xlsx` deferred).
- Review-tail truncation/`NA` behavior from legacy R is not yet ported; this is deferred to summary/parity hardening.
- Real-data timing-log enrichment path remains unvalidated where no site `TimingLogs/<case>.csv` source is available (0 timing-log files detected in broad trial).
- Broad trial produced high warning counts (14,678 total), dominated by negative rebased starts and plot exclusion/quality warnings; warning policy needs tuning for actionable triage.
- Residual cleanup rerun removed remaining >2h interval outliers, but parity intent for capped early-state durations should be explicitly reviewed/approved against legacy expectations.

## Next Recommended Step

Implement parity/operations hardening:
1. review and approve early-state truncation policy against legacy workflow expectations;
2. define warning tiers (expected vs actionable) and reduce remaining plot-warning noise;
3. begin summary/parity slice with explicit acceptance thresholds.

## Resume Instructions

1. Read `AGENTS.md`.
2. Read `SOP.md`.
3. Read `ARCHITECTURE.md`.
4. Read `SESSION.md`.
5. Continue with parity/warning-tiering using `run_outputs_broader_20260311_residual`.

## Post-Full Dataset Validation Tasks

The following items are intentionally deferred until after the full dataset has been processed successfully using the current pipeline.

### Visualization Improvements

1. **Legend layout improvement (workflow-style legend)**  
   Improve the timeline plot legend layout to resemble publication-quality workflow diagrams.

   Proposed changes:
   - Move legend outside the plotting area (below the plot)
   - Center legend horizontally
   - Organize legend entries into multiple columns
   - Remove legend frame
   - Optimize spacing for readability

   Goal:
   Produce figures suitable for presentations and manuscripts rather than development/debug plots.

### Future Analytical Enhancements

2. **Site-level summary visualizations**

   Add higher-level visualizations derived from `state_intervals` outputs.

   Potential plots:
   - Median timeline per workflow stage across cases
   - Distribution of treatment durations
   - Stage duration boxplots
   - Site workflow comparison plots

   Purpose:
   Transform the pipeline from a reconstruction/visualization tool into a workflow analysis tool.

### Implementation Timing

These tasks should only begin **after the full dataset run confirms:**

- event reconstruction stability
- interval plausibility
- no sentinel or timestamp corruption
- plots visually match legacy R pipeline behavior

### Expanded TODO Backlog (User-Supplied)

## TODO (Post-Full Dataset Validation)

### 1. Brainstorm advancing, polishing, and finalizing

Before adding major new features, step back and define:

- what "production-ready" means for this pipeline
- what belongs in the core pipeline vs downstream analysis
- what should be hardened first, e.g., logging, sanitization, multi-site ingestion, parity reports, summary outputs
- what should remain optional modules

### 2. Multi-site ingestion and analysis expansion

Expand the pipeline so it can ingest and preserve separation across multiple sites rather than assuming a single-site run.

Goals:

- support multiple site roots in one run
- preserve `site_code` as a first-class field through all pipeline stages
- keep case-level and site-level outputs separate and attributable
- enable downstream comparative analysis across sites

Planned downstream analyses:

- box-jitter plots for state durations
- histograms of state durations stratified by quartile
- per-state comparisons across multiple sites

Requirements:

- curate multiple `local.db` sources cleanly
- maintain data hygiene and provenance across sites
- prevent cross-site mixing during ingestion, enrichment, state reconstruction, interval generation, and plotting

Implementation idea:

- introduce a manifest-driven ingestion layer with records like:
  - `site_code`
  - `case_id`
  - `source_db_path`
  - `sanitized_db_path`
  - `ingest_batch_id`
  - `data_status`
- make `site_code` mandatory in every major contract:
  - normalized events
  - enriched events
  - state-labeled events
  - state intervals
  - summaries
- support both:
  - single-site validation mode
  - multi-site batch mode

### 3. Data sanitization and curated database staging

Add a dedicated preprocessing/staging workflow so the pipeline can be pointed at raw data, sanitize it, and build a stable curated working set before analysis.

Desired behavior:

- accept one or more source roots
- copy databases into a controlled curated store
- rename each DB deterministically as:
  - `<case_id>_local.db`
- optionally hash files to detect duplicates and support auditability
- keep source path and curated path linked in a manifest
- avoid mutating original source data

Ideas for curated storage:

- preferred first step: filesystem-based curated store + manifest table
- optional later step: SQLite metadata catalog for run tracking and provenance
- possible structure:
  - `curated_store/<site_code>/<case_id>/<case_id>_local.db`
  - `curated_store/manifests/*.json`
  - `curated_store/catalog.sqlite`

Recommended approach:

- keep raw `local.db` files as copied artifacts
- use a separate metadata/catalog database rather than merging case DBs
- store provenance, hashes, run status, warnings, and output paths in the catalog
- do not collapse all source `local.db` data into one monolithic operational DB unless there is a strong reason

### 4. Logging and state-status command-line output

Add explicit logging and operator-facing status output.

Goals:

- make pipeline progress visible while running
- make failures and warnings attributable by site and case
- support long multi-site runs without ambiguity

Desired features:

- structured logging to file
- concise CLI progress/status output
- per-case start/success/warning/failure messages
- run summary at completion
- log levels, e.g. `INFO` / `WARNING` / `ERROR` / `DEBUG`
- optional quiet vs verbose modes

### 5. Multi-site comparative reporting

After multi-site ingestion and sanitization are stable, add comparative outputs such as:

- per-site state duration summaries
- cross-site box-jitter plots
- quartile-stratified histograms by state
- site-vs-site workflow comparisons
- anomaly/outlier detection by state and site

### 6. Suggested implementation order

1. Brainstorm and define final target state
2. Add logging and CLI status output
3. Add sanitization + curated-store workflow
4. Add manifest/catalog support
5. Add multi-site ingestion support
6. Validate full pipeline on curated multi-site data
7. Add comparative state-duration analysis and plots

Design recommendations:

- For curated storage, do not merge all case databases into one giant SQL database. Keep each `local.db` as its own copied artifact and maintain a separate catalog SQLite DB for metadata, hashes, paths, warnings, run IDs, and outputs.
- For multi-site work, make `site_code` a required field in every major dataclass before the codebase grows further.
- For logging, use both structured file logs per run and concise console progress (e.g., `[site=064 case=064_01-023] state intervals exported`).
- For comparative analysis, build from `state_intervals` and later `case_summaries`, not from raw events.
- For work data, avoid uploading raw `local.db` files or anything containing PHI/PII or proprietary contents here. Use sanitized copies, metadata, schemas, and small abstracted examples instead.

### Multi-site ingestion and comparative analysis

TODO: add box-jitter plot analysis and histogram plots for stratified state lengths.

Planned analyses:

- Box-jitter plots of state duration distributions
- Histogram plots of state durations stratified by quartile
- Per-state comparisons across multiple sites

Requirements:

- Pipeline must ingest multiple site datasets simultaneously
- Preserve `site_code` through all pipeline stages
- Maintain strict site separation during processing
- Ensure strong data hygiene and provenance tracking

Proposed approach:

- Introduce a manifest-driven ingestion layer
- Required manifest fields:
  - `site_code`
  - `case_id`
  - `source_db_path`
  - `sanitized_db_path`
  - `ingest_batch_id`
  - `data_status`
- Preserve `site_code` in all downstream tables:
  - normalized events
  - enriched events
  - state labeled events
  - state intervals
  - summary outputs

Goal:
Enable robust cross-site workflow comparison while preserving full traceability.

### Data sanitization and curated database staging

TODO: enforce pipeline ability to sanitize and curate incoming datasets.

Desired behavior:

- Accept one or more source root directories
- Copy databases into a controlled curated store
- Deterministically rename databases as `<case_id>_local.db`
- Optionally compute file hashes for provenance and duplicate detection
- Maintain a manifest linking original path, curated path, and ingestion metadata

Recommended structure:

- `curated_store/<site_code>/<case_id>/<case_id>_local.db`
- `curated_store/manifests/`
- `curated_store/catalog.sqlite`

Recommended architecture:

- Keep raw case databases as individual files
- Maintain separate metadata catalog database
- Do not merge all case databases into one operational DB

Catalog database stores:

- provenance metadata
- run IDs
- warning summaries
- case status
- output artifact locations

### Logging and pipeline state visibility

TODO: enforce structured logging and command-line state output.

Goals:

- Make pipeline progress visible during long runs
- Provide traceable diagnostics for warnings and failures
- Support multi-site batch execution

Desired features:

- Structured log files per run
- Console progress output
- Per-case status messages
- Run summary report

Example CLI output:

```text
[INFO] site=Stanford_064 case=064_01-023 ingestion complete
[INFO] state reconstruction complete
[WARNING] ignored_session_sentinel_timestamp:SessionStart
[INFO] interval export written
```

Logging capabilities:

- log levels (`INFO`, `WARNING`, `ERROR`, `DEBUG`)
- optional `--verbose` and `--quiet` flags

### Visualization improvements (already identified)

TODO: improve timeline plot legend layout to resemble publication-quality workflow diagrams.

Planned changes:

- Move legend outside the plotting area
- Center legend horizontally
- Use multi-column layout
- Remove legend frame
- Improve spacing for readability

Goal:
Produce presentation-quality and manuscript-quality figures rather than development plots.

### Development roadmap

Recommended implementation order:

1. Run full dataset validation with current pipeline
2. Implement structured logging and CLI status output
3. Build curated data store + sanitization layer
4. Introduce metadata catalog database
5. Add multi-site ingestion capability
6. Validate pipeline on curated multi-site data
7. Implement cross-site statistical visualizations

### Add catalog.sqlite design support planning

Design and document a metadata catalog database named `catalog.sqlite` for the future curated-store and multi-site workflow.

Use the catalog as a provenance/metadata database, not as a merged operational database of all `local.db` contents.

The catalog design should include at minimum these tables:

- `sites`
- `cases`
- `source_files`
- `curated_files`
- `ingest_batches`
- `case_ingest_batch_map`
- `pipeline_runs`
- `case_runs`
- `artifacts`
- `warnings`
- `errors`

Design goals:

- support multiple site roots
- preserve `site_code` and `case_id` through all stages
- track original vs curated file locations
- support deterministic renamed curated DB files like `<case_id>_local.db`
- track hashes, run IDs, statuses, warnings, errors, and artifact paths
- support future comparative analysis across sites
- avoid merging all source `local.db` contents into one monolithic DB

For this task, do not implement the full catalog unless explicitly needed.
Instead:

1. incorporate this catalog design into the planning/docs/TODO structure
2. recommend how the future multi-site ingestion layer should use it
3. keep the design aligned with a filesystem curated store plus SQLite metadata catalog

### TODO: TFF spreadsheet ingestion and audit

Ingest `Treatment Feedback Forms Output.xlsx` as a secondary metadata source for timeline analysis.

Planned work:

- audit workbook structure and sheet contents
- identify candidate columns for case ID, site, timing variables, and other potentially useful metadata
- build a normalized site lookup so spreadsheet site labels can be mapped to analysis site IDs
- implement case ID alignment against pipeline case IDs with soft-fail behavior for discontinuities, unmatched cases, and ambiguous mappings
- export audit artifacts, including column inventory, completeness, unique values, duplicate case IDs, site value counts, and candidate timing columns
- parse non-timing metadata that may be useful later, even if not immediately used in timing analysis

Known anticipated issue:

- some afternoon times may be entered as `1:00` instead of `13:00`
- TFF time parsing should enforce expected event order and repair likely AM/PM ambiguity using deterministic monotonic sequence logic
- prefer the smallest forward correction that restores plausible order, prioritizing `+12h`, with `+24h` only when justified
- all corrections and unresolved ambiguities must be surfaced in audit outputs
- unresolved ambiguities must soft-fail and not terminate ingestion
