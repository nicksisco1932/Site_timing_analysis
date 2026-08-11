# Timeline Cache Benchmark — 2026-08-11

## Scope

Three serialized repetitions per condition used the same UCLA manifest:
`008_01-201`, `008_01-202`, `008_01-206`, and `008_01-207`. Profiling remained
observational; case selection, source validation, plots, intermediate artifacts,
publication gates, and the public 20-column CSV contract were unchanged.

## Results

| Condition | Cache composition | Median wall | Change vs disabled | Median process CPU | Median non-CPU wall |
| --- | --- | ---: | ---: | ---: | ---: |
| Disabled | 0 hits / 4 parsed | 65.601s | baseline | 4.828s | 60.585s |
| Mixed | 2 hits / 2 parsed | 83.110s | +26.69% | 6.125s | 76.985s |
| All hit | 4 hits / 0 parsed | 126.644s | +93.05% | 7.484s | 119.159s |

Every repetition reconciled at least 99.9989% of wall time. All conditions
produced the same public CSV SHA-256
`09A86D1F98707C67345627CE8299D3BAF0E0AF8A2ECE62B1E292DB8392686D2D`.
Event, interval, and plot artifacts were byte-identical across conditions.

## Attribution

The mandatory pre-execution repository test snapshot dominated wall time. Its
median duration was 60.220s disabled, 76.204s mixed, and 117.256s all-hit,
approximately 92% of each median total. `time.process_time()` does not include
child-process CPU, so pytest subprocess work appears in the non-CPU/I/O-wait
proxy; that proxy is not a direct disk-I/O measurement.

For the case-processing stages themselves:

- Disabled database ingestion plus normalization, enrichment, labeling, and
  interval construction had a 0.203s median combined duration.
- Mixed cache lookup, hashing, and analytical-store reads took 0.229s, in
  addition to 0.154s for the two misses' parse stages.
- All-hit cache lookup, hashing, and analytical-store reads took 0.336s and
  eliminated clinical database ingestion and transformation stages.
- Plot generation remained CPU-heavy and varied from a 1.970s disabled median
  to 4.630s all-hit; it is unaffected by cache semantics and remains part of
  the artifact contract.

The conditions were serialized rather than randomized, and repository-test
runtime increased during the all-hit series. Total-wall percentages therefore
describe observed operational runs, not a causal cache penalty. The stage data
does show that exact source hashing and store lookup are slightly slower than
direct parsing for these four small, locally available databases.

## Decision

The cache is accepted for exact, deterministic reconstruction and historical
reuse, not as a demonstrated speed optimization for this dataset. No pipeline
optimization was implemented from these measurements.

The next optimization target is a verified reusable pre-execution baseline
snapshot. It must bind the Git commit and dirty fingerprint, interpreter,
dependencies, test command, result, and freshness window; mismatches must force
a live baseline. Default live validation remains unchanged until that mechanism
has repeatable before/after evidence and byte-identical outputs.

Generated benchmark runs and clinical-derived artifacts remain outside Git.
