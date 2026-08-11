# TODO

## Current checkpoint

- Cache/reporting work is on `codex/timeline-cache-reuse`, based on the reviewed
  documentation checkpoint `36b4067` (2026-08-11).
- The sole operational analytical store is the locally pinned
  `C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite`.
- Detailed evidence for completed TODOs #1 through #6 is archived in
  [`docs/TODO_HISTORY.md`](docs/TODO_HISTORY.md).
- Clinical databases, analytical stores, acquired data, generated outputs, and
  profiling artifacts remain outside Git.

## Completed work

| Item | Status | Outcome |
| --- | --- | --- |
| #1 GitHub housekeeping | Completed 2026-08-10 | Repository scope, data hygiene, tests, documentation, and reviewer summary completed. |
| #2 Single-case acquisition | Completed 2026-08-11 | One explicit Sync.com case acquired and independently validated read-only. |
| #3 Five-case acquisition | Completed 2026-08-11 | Five explicit cases acquired with no unresolved ambiguity or validation failure. |
| #4 Bulk acquisition | Completed 2026-08-11 | Resumable explicit-selection acquisition with separate backend and safe existing-file handling. |
| #5 Site availability and parity | Completed 2026-08-11 | Read-only remote/local inventory and case-parity CLI delivered and validated. |
| #6 Durable analytical database | Completed 2026-08-11 | Schema-v2 exact read-only cache reuse and SQL-native reporting passed ASUI/UCLA live parity. |

## 7. Profile and optimize the pipeline

**Rationale:** Profiling now reconciles total wall time, but optimization should
follow cache integration so measurements reflect the intended architecture.

Current evidence:

- Three repetitions per condition on the fixed UCLA manifest `008_01-201`,
  `008_01-202`, `008_01-206`, and `008_01-207` reconciled at least `99.9989%`
  of total wall time and produced the same public CSV hash.
- Median total wall time was `65.601s` with cache disabled, `83.110s` with two
  hits/two misses (`+26.69%`), and `126.644s` with four hits (`+93.05%`).
- The mandatory repository-test preflight dominated and varied substantially:
  median `60.220s`, `76.204s`, and `117.256s`, respectively. On this small,
  local dataset, all-hit source hashing/store lookup (`0.336s`) also exceeded
  the disabled ingestion/transformation proxy (`0.203s`). Cache reuse is exact
  and useful for deterministic reconstruction, but is not yet a speedup here.
- A prior plot-disabled diagnostic reduced runtime by `10.81%`, but plots and
  intermediate CSVs remain part of the artifact contract.
- Intermediate diagnostic CSV suppression remains unsupported because those
  artifacts are part of the current staged contract.

Selected optimization:

- Design an explicit, reusable pre-execution baseline snapshot so repeated
  operational runs do not rerun the full repository test suite when the Git
  commit/dirty fingerprint, interpreter, dependency state, test command, exit
  status, and freshness window still match.
- Keep live baseline execution as the default until snapshot validation is
  proven. Reject or refresh stale/mismatched snapshots; never silently skip a
  required gate.
- Rebenchmark the same fixed manifest after the preflight change. Treat source
  hashing or plot optimization as later work unless post-preflight measurements
  identify either as the next bottleneck.

Completion criteria:

- Every benchmark reconciles nested timing to total wall time within tolerance.
- A verified snapshot is accepted only for an identical repository,
  interpreter, dependency, and test-command fingerprint and retains the full
  baseline evidence in `Backend/reports`.
- Three repeated before/after runs show a repeatable total-wall reduction with
  byte-identical public CSV, event, interval, plot, and reconciliation outputs.
- Generated profiling outputs remain outside Git and the recommendation clearly
  distinguishes CPU, database, and filesystem constraints.
