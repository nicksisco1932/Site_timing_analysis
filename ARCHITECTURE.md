# ARCHITECTURE.md

## Purpose

This file defines the current system structure and module boundaries for the
staged Python timing-analysis pipeline. It is not a task log or session diary.

## Control-Flow Position

Read this file after `AGENTS.md` and `SOP.md`, and before `SESSION.md`.

## Supported Pipeline Flow

```text
site root
  -> discovery.py
  -> db_source.py
  -> ingestion.py
  -> normalization.py
  -> enrichment.py / timing_log.py
  -> state_machine.py
  -> timing.py
  -> manifest.py / plotting.py
  -> plot_tables.py / workflow_summary.py / site_comparison.py
  -> timing_gantt_deliverables.py
```

An optional, pre-pipeline acquisition test is isolated from that core flow:

```text
explicit commercial site + case selection
  -> single_case_acquisition.py
  -> exact <case-id> TDC Sessions folder
  -> one timestamped session folder with direct local.db
  -> validated <destination>/<case_id>/local.db
  -> ordinary site-root discovery when explicitly selected for analysis
```

The dependency-gated representative validation composes that contract without
changing the core timing pipeline:

```text
explicit site + at least five unique case IDs
  -> multi_case_acquisition.py
  -> sequential single-case acquisition through one read-only connection
  -> required internal case-identity verification
  -> case-level JSON + aggregate JSON/Markdown summaries
```

The production-oriented acquisition layer remains explicit and composes the
same case gate:

```text
explicit site + repeated case IDs or text manifest
  -> bulk_acquisition.py
  -> separate backend lock + durable case inventory
  -> single-case acquisition, reported existing-file skip, or verified reuse
  -> <destination>/<case_id>/local.db
  -> <backend>/{_acquisition,_staging,_quarantine}
```

`first_slice_cli.py` is the staged-pipeline orchestrator. It coordinates the
flow above and records run-level, case-level, and artifact-level status without
embedding the implementation of each stage.

## Module Boundaries

- `models.py` contains typed contracts for run configuration, discovered cases,
  raw/normalized/enriched events, state-labeled events, intervals, and manifests.
- `errors.py` contains the typed exception hierarchy used at stage boundaries.
- `config.py` validates CLI/mapping configuration and year selection.
- `discovery.py` enumerates cases and candidate database sources deterministically.
  Canonical site-prefix filtering is the default; extra prefixes are explicit
  opt-in compatibility behavior.
- `db_source.py` resolves database candidates using deterministic precedence and
  explicit ambiguity handling.
- `ingestion.py` reads `AuditLogRecords` and optional `Sessions` data read-only.
- `normalization.py`, `enrichment.py`, and `timing_log.py` produce immutable
  derived event streams from raw inputs.
- `state_machine.py` assigns workflow states and records cleanup attribution.
- `timing.py` computes state intervals, rebasing, truncation, and quality flags.
- `manifest.py` writes the canonical run, event, and interval artifacts.
- `plotting.py` produces timeline figures from interval contracts only.
- `plot_tables.py`, `workflow_summary.py`, and `site_comparison.py` are
  downstream analytical/reporting consumers of derived timing artifacts.
- `timing_gantt_deliverables.py` builds human-facing final deliverables from
  completed timing-Gantt run folders without changing raw reconstruction data.
- `tff_adapter.py`, `tff_bounded.py`, and `hardware_lookup.py` are optional,
  provenance-oriented integration surfaces and are not required for the core
  timing pipeline.
- `single_case_acquisition.py` is an optional, read-only validation surface for
  acquiring one explicitly selected commercial `local.db`. It matches the exact
  case folder, ignores `applog`, inspects timestamped session children, rejects
  ambiguity, and supports opt-in session-export ZIP fallback only when no direct
  database exists. It reuses the ProfoundTools Sync transport snapshot under
  `tools/profoundtools` without changing its `applog` planner.
- `multi_case_acquisition.py` is the dependency-gated five-or-more-case
  validation surface. It requires unique explicit same-site IDs, isolates case
  failures, requires internal case identity, and produces machine- and
  human-readable summaries.
- `bulk_acquisition.py` is the scalable explicit-selection layer. It checkpoints
  a case-level JSON/CSV inventory after every case, requires a technical backend
  outside the clean destination, isolates failures, and recovers interrupted
  staging files. It reports and skips valid pre-existing databases, supports
  opt-in exact remote-hash adoption, and reuses verified files only when local
  validation, prior inventory, and current remote metadata agree. Required
  identity uses `PatientId` when available; otherwise a downloaded artifact must
  have one `Sessions.Start` matching the exact selected session-folder timestamp
  within two seconds. It does not discover cases implicitly or call source-share
  mutation APIs.

## Legacy Compatibility Surface

Root-level `tulsa_*.py` files are compatibility wrappers into matching modules
under `src/site_timing_analysis/`. Legacy batch files and the R reference under
`Legacy/` remain available for comparison and historical workflow support.

New pipeline work should compose from normalized events and downstream contracts;
it should not bypass the staged interfaces or add summary/plot logic to ingestion
or normalization modules.

## Data and Output Rules

- Source databases are treated as read-only.
- Raw databases, analysis workbooks, generated outputs, and caches stay outside
  source control unless explicitly approved.
- Derived artifacts are written beneath the selected run directory using the
  canonical layout in `output_layout.py`.
- Case/site identifiers and provenance fields must remain attributable through
  every downstream export.

## Deferred Work

- Formal parity diffing against historical R outputs.
- Broader multi-site curated storage and catalog support.
- Splitting large compatibility/reporting modules after interface behavior is
  stabilized and covered by the test suite.
