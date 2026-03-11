# Python Parity Checklist

Reference source:
- `Legacy/r_reference/ReadAuditLogs.R`

Target:
- Python is the implementation of record.
- Legacy R is used only to define expected workflow semantics and output shape.

## End Product

- [x] Reconstruct workflow states from `local.db` into a state-enriched CSV
- [x] Build patient-level timing summary tables
- [x] Produce Gantt-style workflow plots from Python
- [x] Produce stacked timing plots and summary histograms from Python
- [x] Provide a repeatable smoke test using `test_data/local.db`

## Workflow States

- [x] `TULSA QA`
- [x] `Room ready`
- [x] `Patient positioning & induction`
- [x] `Device insertion`
- [x] `Device repositioning`
- [x] `Alignment`
- [x] `Coarse`
- [x] `Detailed`
- [x] `Planning start angle`
- [x] `Initialization`
- [x] `Treating`
- [x] `Paused`
- [ ] `Review`
- [x] `Post-treatment scans & Device removal`
- [x] `Patient recovery & transfer`

## Supporting Behavior

- [x] Direct single-DB ingestion for local smoke testing
- [x] Session-derived synthetic boundary events from `Sessions`
- [x] Persistent workflow-state carry-forward across intermediate audit rows
- [x] Shared workflow order/colors across plots and summaries
- [x] Root script wrappers preserved after `src/` reorganization
- [x] No `local2.db` support required in the modern Python collector
- [ ] External timing-sheet enrichment when required by older site data
- [ ] Formal comparison against one or more historical R-generated outputs

## Current Notes

- The real-case smoke test in `test_data/local.db` currently produces no
  unmapped state rows in the Python state machine.
- The `Review` state exists in the model but is not currently represented in the
  provided `test_data/local.db` output; this needs confirmation against more
  real cases.
- `local2.db` is intentionally out of scope for the Python pipeline. The
  supported input model is `local.db` plus `Sessions` data when present.
