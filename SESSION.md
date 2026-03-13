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

## TFF Audit First Pass (2026-03-13)

Input workbook audited:

- `C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - WIP new TFF process\Treatment Feedback Forms Output.xlsx`

Audit artifacts generated:

- `run_outputs/tff_audit/sheet_inventory.csv`
- `run_outputs/tff_audit/column_inventory.csv`
- `run_outputs/tff_audit/completeness_summary.csv`
- `run_outputs/tff_audit/site_value_summary.csv`
- `run_outputs/tff_audit/case_id_quality_summary.csv`
- `run_outputs/tff_audit/case_id_suspicious_examples.csv`
- `run_outputs/tff_audit/candidate_timing_columns.csv`
- `run_outputs/tff_audit/timing_ambiguity_probe.csv`
- `run_outputs/tff_audit/tff_audit_summary.md`

Key findings:

- Workbook contains 11 sheets; one sheet (`Sheet1`) is extremely wide (16,373 columns) and likely contains noisy/merged export structure that needs controlled schema handling.
- Heuristic field discovery found site-like columns, case-ID-like columns, and timing-like columns, but also false positives; role-specific column selection must be constrained in implementation.
- `Sheet2::PatientID` is the strongest case-ID candidate (`97.16%` canonical pattern match), with non-canonical variants that require normalization rules.
- Site labels are text-heavy institution names and require deterministic normalization/mapping to analysis site IDs.
- AM/PM ambiguity is material: 15,845 ambiguous clock-only values (`1:00`-style), versus 1 explicit AM/PM value.
- Sequence probe found 189 naive non-monotonic rows; 186 were repairable with `+12h`, 4 required `+24h`, and 0 were unresolved in the probe set.

Recommended next implementation slice:

1. Build a dedicated TFF ingestion-audit module (no integration into timing pipeline yet).
2. Implement deterministic site-label normalization and mapping reports.
3. Implement case-ID canonicalization/alignment with soft-fail outputs for unmatched or ambiguous cases.
4. Implement ordered event-time correction using smallest-forward logic (`+12h` preferred, `+24h` fallback) with per-cell correction audit columns.
5. Export corrected and unresolved timing audit artifacts as the gating output before any timeline integration.

## TFF Bounded Re-Audit Correction (2026-03-13)

Course correction applied:

- Treat `Sheet1!A:BK` as the authoritative bounded source for near-term TFF ingestion planning.
- Treat columns beyond `BK` as spreadsheet/export noise; exclude them from schema planning.

Bounded re-audit outputs added:

- `run_outputs/tff_audit/sheet1_a_bk_header_inventory.csv`
- `run_outputs/tff_audit/sheet1_a_bk_populated_columns.csv`
- `run_outputs/tff_audit/sheet1_a_bk_candidate_columns.csv`
- `run_outputs/tff_audit/sheet1_a_bk_case_id_quality.csv`
- `run_outputs/tff_audit/sheet1_a_bk_generated_treatment_id_summary.csv`
- `run_outputs/tff_audit/sheet1_a_bk_generated_treatment_id_noncanonical_examples.csv`
- `run_outputs/tff_audit/sheet1_a_bk_bounded_audit_summary.md`

Bounded findings:

- `Sheet1!A:BK` contains 63 populated columns across 3,415 rows and covers the operationally meaningful TFF fields.
- Best bounded primary case-ID field is `Generated Treatment ID` with high canonical coverage (`94.01%`, 3,140/3,340 canonical).
- `Sheet1!A:BK` is sufficient as primary identifier source for the next slice, with soft-fail normalization required for non-canonical residuals.
- `Sheet2::PatientID` remains useful as a secondary fallback/reference field for unresolved ID normalization edge cases.

## TFF Bounded Normalization/Export Slice Implemented (2026-03-13)

Implemented module:

- `src/site_timing_analysis/tff_bounded.py`
  - loads only `Sheet1!A:BK` (with bounded fallback for short test workbooks)
  - uses `Generated Treatment ID` as primary case ID
  - uses `Sheet2::PatientID` as secondary fallback/reference for alignment checks
  - canonicalizes case IDs with deterministic soft-fail statuses
  - builds deterministic site-label normalization outputs
  - identifies timing columns in bounded scope
  - applies sequence-aware monotonic repair (`+12h` preferred, `+24h` fallback)
  - exports bounded normalization and audit artifacts without integrating into state-interval pipeline
  - includes standalone CLI entry via `python -m site_timing_analysis.tff_bounded`

Validation:

- Added tests: `tests/test_tff_bounded_slice.py`
- Full suite pass: `72 passed`

Generated artifacts (bounded normalization layer):

- `run_outputs/tff_audit/tff_normalized_case_table.csv`
- `run_outputs/tff_audit/tff_case_id_alignment_report.csv`
- `run_outputs/tff_audit/tff_site_mapping_report.csv`
- `run_outputs/tff_audit/tff_time_correction_audit_report.csv`
- `run_outputs/tff_audit/tff_unresolved_soft_fail_report.csv`
- `run_outputs/tff_audit/tff_timing_column_report.csv`
- `run_outputs/tff_audit/tff_bounded_normalization_summary.md`

Current bounded-run signals:

- normalized case rows: `3415`
- case-ID soft-fail rows: `273`
- `+12h` timing corrections: `7784`
- `+24h` timing corrections: `99`
- unresolved timing corrections: `3`

Assumptions used in this slice:

- Sequence corrections are applied in workflow order, not as independent timestamps.
- Smallest-forward correction is deterministic: try `+12h`, then `+24h`, otherwise unresolved soft-fail.
- No integration into the existing timing/state pipeline yet; this is a pre-integration normalization layer only.

Recommended next step:

1. review/approve unresolved soft-fail policy (`273` ID soft-fail rows, `3` unresolved timing rows);
2. finalize site-label mapping table to analysis site IDs;
3. add optional secondary-ID-assisted recovery path for unresolved `Generated Treatment ID` rows;
4. only then wire bounded TFF outputs into downstream timeline enrichment.

## TFF Post-Implementation Validation Review (2026-03-13)

Reviewed artifacts:

- `run_outputs/tff_audit/tff_normalized_case_table.csv`
- `run_outputs/tff_audit/tff_case_id_alignment_report.csv`
- `run_outputs/tff_audit/tff_site_mapping_report.csv`
- `run_outputs/tff_audit/tff_time_correction_audit_report.csv`
- `run_outputs/tff_audit/tff_unresolved_soft_fail_report.csv`
- `run_outputs/tff_audit/tff_timing_column_report.csv`
- `run_outputs/tff_audit/tff_bounded_normalization_summary.md`
- `run_outputs/tff_audit/tff_post_impl_validation_review.md`

Quantitative validation:

- usable case coverage (non-soft-fail IDs): `3142/3415` (`92.01%`)
- unresolved ID rate: `273/3415` (`7.99%`)
- unmapped site rate (row-weighted by current guessed site code): `3415/3415` (`100%`)
- corrected timing rate (event-level parseable points): `7883/17847` (`44.17%`)
- unresolved timing rate (event-level parseable points): `3/17847` (`0.0168%`)

Timing fields strong enough for minimal integration now (workflow events):

- `Timing  Patient enters MRI room `
- `Timing  Anesthesia starts to prepare the patient `
- `Timing  Patient is sedated`
- `Timing  Device Insertion Begins`
- `Timing  Device Insertion Complete`
- `Timing  Patient leaves MRI room`
- `Timing  Patient Transfer to Recovery room`

Minimal safe integration slice recommendation (not implemented yet):

1. add a read-only TFF adapter that joins by canonical `case_id` and ingests only the seven workflow event-time columns above;
2. keep integration behind a feature flag default-off;
3. exclude `case_id_soft_fail` and unresolved timing rows from downstream timing replacement, while preserving them in audit outputs;
4. propagate correction provenance fields (`tff_source_row`, `tff_correction_type`, `tff_time_corrected`) into downstream artifacts;
5. defer derived timing fields (`Calculated MRI Time`, `Ablation Time`, `Planning Time`, `MRI Time`) until primary event-time integration is stable.

## TFF Deterministic Site Normalization Implemented (2026-03-13)

Implementation scope:

- bounded TFF layer only (`src/site_timing_analysis/tff_bounded.py`)
- no integration into main state-interval pipeline

Deterministic mapping logic:

- normalize site labels (`site_label_raw` -> `site_label_normalized` / `site_key`)
- derive candidate site code from canonical `case_id` prefix (`AAA999_..` -> `999`)
- build explicit label-level normalization table with required status classes:
  - `mapped`: exactly one case-ID-derived site code for the label
  - `unmapped`: no usable case-ID-derived site code evidence (or blank label)
  - `ambiguous`: multiple competing case-ID-derived site codes
- propagate mapping status/code back into normalized case rows

New/updated bounded artifacts:

- `run_outputs/tff_audit/tff_site_mapping_report.csv`
- `run_outputs/tff_audit/tff_site_normalization_table.csv`
- `run_outputs/tff_audit/tff_site_normalization_summary.md`
- `run_outputs/tff_audit/tff_normalized_case_table.csv` (now includes `mapping_status`, `normalized_site_code`, `mapping_reason`, `candidate_site_codes`)
- `run_outputs/tff_audit/tff_unresolved_soft_fail_report.csv` (now includes `site_unmapped`/`site_ambiguous` issues)

Coverage after deterministic site normalization:

- label-level: `58 mapped`, `2 unmapped`, `0 ambiguous`
- row-level: `3397 mapped` / `3415 total` (`99.47%` mapped)
- remaining unmapped rows: `18` (`0.53%`)

Remaining unmapped labels:

1. `London Health Sciences Centre (UWO)` (16 rows; no case-ID site-code evidence)
2. blank site label (2 rows)

Validation status:

- focused tests: `tests/test_tff_bounded_slice.py` includes mapped + ambiguous-site cases
- full suite: `73 passed`

Next recommended step:

1. approve handling for the two unmapped site labels (manual mapping vs keep unmapped);
2. proceed to the read-only TFF adapter slice using mapped rows only, with provenance fields preserved;
3. keep unmapped/soft-fail rows in audit outputs and excluded from downstream timing replacement.

## TFF Read-Only Adapter Slice Implemented (2026-03-13)

Implementation scope:

- new module: `src/site_timing_analysis/tff_adapter.py`
- read-only join of bounded TFF normalized metadata onto pipeline case-level results by canonical `case_id`
- join kept behind feature flag (`--enable-tff-adapter`) and default-off
- optional explicit table input via `--tff-normalized-case-table`

Integrated TFF workflow timing fields:

- `Patient enters MRI room`
- `Anesthesia starts to prepare the patient`
- `Patient is sedated`
- `Device Insertion Begins`
- `Device Insertion Complete`
- `Patient leaves MRI room`
- `Patient Transfer to Recovery room`

Provenance fields preserved in joined case-level outputs:

- `tff_source_row`
- `tff_time_corrected`
- `tff_correction_type`
- `tff_parse_status`

Artifacts added when adapter is enabled:

- `tff_adapter/tff_case_join.csv`
- `tff_adapter/tff_integration_summary.md`

Behavior and constraints:

- adapter is read-only and does not replace pipeline timing/state/interval values
- existing pipeline exports remain unchanged
- case-ID alignment failures soft-fail with explicit warnings:
  - `tff_adapter:pipeline_cases_without_tff:<count>`
  - `tff_adapter:tff_cases_without_pipeline_match:<count>`
  - duplicate canonical IDs in TFF table are resolved deterministically (earliest `sheet1_row_number`) with warning

Validation:

- new tests: `tests/test_tff_adapter_slice.py`
- focused + full suite pass: `76 passed`

Next recommended step:

1. run one controlled real-data pass with `--enable-tff-adapter` and inspect `tff_case_join.csv` coverage;
2. decide policy for downstream use of `tff_parse_status=partial|unresolved` rows;
3. keep adapter read-only until parity acceptance for any timing-field usage is approved.

## TFF Adapter Real-Data Validation Pass (2026-03-13)

Validation run executed on:

- site path: `C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - Stanford_064`
- output: `run_outputs_tff_adapter_validation_20260313_stanford`
- adapter input: `run_outputs/tff_audit/tff_normalized_case_table.csv`

Primary command used:

- `.\.venv\Scripts\python.exe -m site_timing_analysis.first_slice_cli --site Stanford_064 --years All --root "C:\Users\NicholasSisco\Profound Medical" --site-path "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - Stanford_064" --output "C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis\run_outputs_tff_adapter_validation_20260313_stanford" --diagnostics --enable-tff-adapter --tff-normalized-case-table "C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis\run_outputs\tff_audit\tff_normalized_case_table.csv"`

Run outcome:

- discovered: `141`
- processed: `140`
- failed: `0`

Adapter join quality (processed cases):

- matched: `135/140` (`96.43%`)
- no TFF match: `5` (`STA_01-003`, `STA_01-004`, `STA_01-005`, `STA_01-006`, `STA_01-008`)
- source-table unresolved/soft-fail ID rows: `273` (missing/non-canonical canonical ID rows in bounded TFF table)

Timing provenance signals on matched rows:

- corrected-time prevalence: `105/135` (`77.78%`)
- unresolved timing prevalence: `0/135` (`0.00%`)
- parse-status distribution: `ok=84`, `partial=39`, `blank=12`, `unresolved=0`

Chronology sanity (7 validated workflow fields):

- monotonic-order violations after correction: `0` on matched rows with available minute values

High-level comparison against pipeline timing spans (heuristic):

- comparable matched cases: `123`
- `confirmatory`: `28`
- `additive`: `81`
- `conflicting`: `14`

Interpretation:

- TFF layer is primarily additive/confirmatory in this pass.
- conflicting span cases are concentrated where pipeline timestamp ranges are known to be inflated by sparse trailing events/day-jump effects; treat as review-required rather than immediate replacement candidates.
- adapter remains suitable as read-only provenance enrichment.

Artifacts reviewed:

- `run_outputs_tff_adapter_validation_20260313_stanford/tff_adapter/tff_case_join.csv`
- `run_outputs_tff_adapter_validation_20260313_stanford/tff_adapter/tff_integration_summary.md`
- `run_outputs_tff_adapter_validation_20260313_stanford/tff_adapter_validation_review.md`

Recommended next slice:

1. keep adapter read-only;
2. add a narrow comparison/audit report layer that highlights only `conflicting` TFF-vs-pipeline cases for manual review;
3. defer any timing-value substitution until case-level parity acceptance criteria are defined.

## TFF Known-Exclusion Filtering Added (2026-03-13)

Objective addressed:

- treat known Stanford RCT case IDs (`STA_01-003` through `STA_01-008`) as optional exclusion candidates in the TFF adapter validation/join path, rather than ordinary unmatched cases.

Implementation scope:

- adapter remains read-only
- no timing/state/interval logic changes
- optional CLI/config flag added: `--tff-filter-known-exclusions` (default: off)

Behavior when enabled:

- known exclusion matches are marked with:
  - `tff_join_status=filtered_known_exclusion`
  - `tff_exclusion_class=rct_stanford_sta`
  - `tff_exclusion_rule=known_stanford_rct_case_pattern:^STA_01-00[3-8]$`
  - `tff_exclusion_reason=known_exclusion_case_class`
- filtered rows are excluded from join-quality unmatched metrics
- explicit filtered-case audit export is written:
  - `tff_adapter/tff_filtered_known_exclusions.csv`
- integration summary now distinguishes:
  - matched
  - filtered known exclusions
  - true unmatched pipeline cases

Validation:

- focused adapter tests updated for optional filtering + audit outputs
- full suite pass: `78 passed`

Next recommended step:

1. run one adapter-enabled validation pass with `--tff-filter-known-exclusions` on target sites where RCT-style IDs may appear;
2. review `tff_filtered_known_exclusions.csv` as a manual QA checkpoint;
3. keep this rule table explicit and extend only with reviewed known-exclusion classes.

## Hardware Lookup Foundation Implemented (2026-03-13)

Objective addressed:

- built a prioritized hardware-query lookup layer for `local.db` ingestion to support case-level hardware questions without manual SQL.

Implementation:

- new module: `src/site_timing_analysis/hardware_lookup.py`
- typed error added: `HardwareLookupError` in `src/site_timing_analysis/errors.py`
- new tests: `tests/test_hardware_lookup.py`

Normalized lookup schema (SQLite):

- `ingest_batches`
- `ingested_cases`
- `source_table_inventory`
- `case_treatment_context`
- `hardware_identifiers`
- `case_device_metrics`
- `case_hardware_summary`

Core capabilities:

- ingest one or more `local.db` files (explicit `--case-db` and/or recursive `--site-root`)
- preserve case/session/treatment linkage and source provenance (`source_table`, `source_field`, `source_row_id`)
- materialize case-level hardware summary answer with direct vs inferred status
- soft-fail behavior for missing answers
- query interface for first required question:
  - “What was the serial number of the PS cable used for this case?”
  - direct field priority: PS cable serial fields when present
  - inferred fallback: `PSSerialNumber` / `PSSerial`

CLI entrypoints:

- ingest:
  - `python -m site_timing_analysis.hardware_lookup ingest ...`
- query:
  - `python -m site_timing_analysis.hardware_lookup query --question ps-cable-serial ...`

Validation:

- new tests passed; full suite: `81 passed`
- sample ingest/query executed on `test_data/local.db`:
  - batch id: `testdata_20260313`
  - generated artifacts under `run_outputs/hardware_lookup_testdata_20260313/`
  - inferred PS-cable answer for case `064_01-137`: `MH9581` (from `Treatments.PSSerialNumber`, with provenance candidates)

Next recommended step:

1. define additional structured question keys (PS serial by treatment, UA test result linkage, pressure/amplifier summaries);
2. run multi-case ingestion on one site root and review duplicate/consistency handling;
3. decide whether this lookup DB remains SQLite-only or gets mirrored to catalog-backed multi-site metadata in later roadmap.
