# ARCHITECTURE.md

## Purpose

This file defines system structure and module boundaries for the Python migration pipeline.

It is not a task log and not the session checkpoint.

## Control-Flow Position

Read this file after `AGENTS.md` and `SOP.md`, and before `SESSION.md`.

## Current Implemented Slice (v1 foundation)

Package: `src/site_timing_analysis/`

- `models.py`: typed contracts for run config, discovery, DB source, raw/normalized events, run manifest
- `errors.py`: typed exception hierarchy for config/discovery/ingestion/normalization/manifest failures
- `config.py`: CLI/mapping config loading and year-selection normalization
- `discovery.py`: deterministic case enumeration and DB/zip candidate collection
- `db_source.py`: precedence-based DB source resolution with explicit ambiguity handling
- `ingestion.py`: read-only SQLite ingestion of `AuditLogRecords` and optional `Sessions`
- `normalization.py`: canonical event normalization and `SignalRecord` drop handling
- `manifest.py`: export of `run_manifest.json`, `case_manifest.csv`, and per-case normalized events
- `first_slice_cli.py`: orchestration of the first slice only

## Not Yet Implemented (planned follow-on slices)

- enrichment from Sessions/timing-sheet synthetic events
- workflow state reconstruction
- timing/rebasing interval engine
- case/site summaries
- plotting outputs
- full parity comparison engine

## Boundary Rules

- Foundation modules above are data-prep only.
- No enrichment/state/timing/summary/plot logic should be added into first-slice modules.
- Future slices should compose from normalized events forward rather than bypassing first-slice contracts.
