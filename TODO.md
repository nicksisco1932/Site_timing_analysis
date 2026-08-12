# TODO

## Current checkpoint

- Active implementation is on `codex/timeline-cache-reuse`, based on commit
  `06ac167` (2026-08-11).
- The sole operational analytical store remains the locally pinned
  `C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\10_Databases\timeline_analysis.sqlite`.
- Detailed evidence for all completed work is archived in
  [`docs/TODO_HISTORY.md`](docs/TODO_HISTORY.md), with the final requirement
  matrix in
  [`docs/TODO_COMPLETION_AUDIT_2026-08-11.md`](docs/TODO_COMPLETION_AUDIT_2026-08-11.md).
- Clinical databases, analytical stores, acquired data, generated outputs,
  onboarding profiles/runners, preflight snapshots, and profiling artifacts
  remain outside Git.

## Completed work

| Item | Status | Outcome |
| --- | --- | --- |
| #1 GitHub housekeeping | Completed 2026-08-10 | Repository scope, data hygiene, tests, documentation, and reviewer summary completed. |
| #2 Single-case acquisition | Completed 2026-08-11 | One explicit Sync.com case acquired and independently validated read-only. |
| #3 Five-case acquisition | Completed 2026-08-11 | Five explicit cases acquired with no unresolved ambiguity or validation failure. |
| #4 Bulk acquisition | Completed 2026-08-11 | Resumable explicit-selection acquisition with separate backend and safe existing-file handling. |
| #5 Site availability and parity | Completed 2026-08-11 | Read-only remote/local inventory and case-parity CLI delivered and validated. |
| #6 Durable analytical database | Completed 2026-08-11 | Schema-v2 exact read-only cache reuse and SQL-native reporting passed ASUI/UCLA live parity. |
| #7 Guided handoff initialization | Completed 2026-08-11 | Windows bootstrap, secret-free per-user profiles, and collision-safe validated runners delivered. |
| #8 Pipeline profiling and optimization | Completed 2026-08-11 | Exact reusable preflight reduced median four-case wall time by 80.03% with byte-identical outputs. |

## Active work

No active TODO items remain. Add future work only with an explicit rationale,
bounded interface, and measurable completion criteria.
