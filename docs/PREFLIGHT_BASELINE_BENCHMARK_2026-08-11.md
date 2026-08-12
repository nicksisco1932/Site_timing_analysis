<!--
Project: Site Timing Analysis
File: docs/PREFLIGHT_BASELINE_BENCHMARK_2026-08-11.md
Primary author: Nicholas J. Sisco, Ph.D.
Organization: Profound Medical, LLC
Created: 2026-08-11
Purpose: Records acceptance and performance evidence for verified preflight reuse.

Provenance: Original implementation or material contribution by
Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.

Rights status: Proprietary / internal use unless otherwise specified
by Profound Medical, LLC.
-->

# Verified Preflight Baseline Benchmark

## Scope

Six profiled cache-disabled runs used the fixed UCLA manifest
`008_01-201`, `008_01-202`, `008_01-206`, and `008_01-207`. The first three
used the default live preflight. The next three reused one externally stored
snapshot after exact validation of its Git commit and dirty-content
fingerprint, interpreter path/version/binary hash, dependency fingerprint,
test-command contract, successful gate results, and 24-hour freshness window.

The final snapshot capture passed the full repository suite (`230 passed`),
`pip check`, `git diff --check`, and the required CLI help checks. Benchmark
runs and snapshot evidence were written under the Windows temporary directory
and were not added to Git.

## Results

| Condition | Repetition 1 | Repetition 2 | Repetition 3 | Median | Change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Live preflight | 26.595s | 20.970s | 20.639s | 20.970s | baseline |
| Verified reuse | 4.152s | 4.236s | 4.188s | 4.188s | -80.03% |

| Median attribution | Live | Reuse | Change |
| --- | ---: | ---: | ---: |
| Preflight inclusive wall | 17.458s | 1.428s | -91.82% |
| Process CPU | 3.063s | 2.531s | -17.35% |
| Non-CPU wall proxy | 17.908s | 1.641s | -90.84% |

Every run published four cases. Timing coverage ranged from `99.9861%` to
`99.9982%`, reconciliation status was `PASS`, and unaccounted time remained at
or below `0.000591s`.

## Output parity

All six runs produced identical SHA-256 values for 20 required artifacts:

- the public 20-column CSV;
- 12 normalized, enriched, and state-labeled event CSVs;
- four detailed interval CSVs;
- both timeline PNGs; and
- the phase-reconciliation CSV.

The per-run `pre_execution_baseline.json` intentionally differs because it
records whether evidence was captured live or reused, the external snapshot
path and SHA-256, validation time, age, and completed identity checks.

## Interpretation

The optimization removed repeated test-subprocess and filesystem wait time,
not clinical parsing work. Median process CPU changed `-17.35%`, while the
non-CPU wall proxy changed `-90.84%`. After reuse, the largest measured stage
was preflight identity validation (`1.419s`, `33.88%` in representative reuse
run 3), followed by plot generation (`0.905s`, `21.62%`), process startup and
CLI parsing (`0.836s`, `19.97%`), and database candidate resolution (`0.360s`,
`8.60%`). Plot suppression remains diagnostic-only
because plots are part of the current artifact contract. No additional
optimization is selected without a new TODO and explicit parity criteria.
