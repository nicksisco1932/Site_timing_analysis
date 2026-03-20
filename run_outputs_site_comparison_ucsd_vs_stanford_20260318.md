# UCSD vs Stanford Efficiency Comparison (State Intervals)

## Data Sources
- UCSD_109: `C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis\run_outputs_ucsd_109_20260318_staged_trimmed\state_intervals`
- Stanford: `C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis\run_outputs_broader_next\state_intervals`

## Figure Label Mapping
- `Site A` = UCSD_109
- `Site B` = Stanford

## Dataset Coverage

| site | interval_files | interval_rows |
| --- | --- | --- |
| UCSD_109 | 27 | 4794 |
| Stanford | 140 | 42776 |

## Case-Level Total Workflow Time (valid states only)

| site | cases | median_min | mean_min | std_min | min_min | max_min |
| --- | --- | --- | --- | --- | --- | --- |
| UCSD_109 | 27 | 248.80 | 282.12 | 115.87 | 144.52 | 656.20 |
| Stanford | 140 | 460.56 | 475.54 | 112.85 | 294.81 | 824.22 |

## Per-State Median Duration Comparison (states with >=10 cases at both sites)

| state | ucsd_cases | stanford_cases | ucsd_median_min | stanford_median_min | delta_min_ucsd_minus_stanford | faster_site_by_median |
| --- | --- | --- | --- | --- | --- | --- |
| Room ready | 27 | 140 | 23.99 | 61.88 | -37.89 | UCSD_109 |
| Detailed | 27 | 140 | 18.60 | 56.01 | -37.40 | UCSD_109 |
| Coarse | 27 | 140 | 11.23 | 35.33 | -24.09 | UCSD_109 |
| Treating | 27 | 140 | 49.99 | 73.71 | -23.72 | UCSD_109 |
| Post-treatment scans & Device removal | 27 | 137 | 23.40 | 46.22 | -22.82 | UCSD_109 |
| Patient positioning & induction | 26 | 129 | 23.50 | 42.00 | -18.50 | UCSD_109 |
| Paused | 27 | 140 | 7.43 | 20.16 | -12.73 | UCSD_109 |
| Device insertion | 26 | 128 | 27.90 | 32.17 | -4.27 | UCSD_109 |
| Planning start angle | 27 | 140 | 2.22 | 6.15 | -3.94 | UCSD_109 |
| Alignment | 27 | 140 | 4.33 | 5.88 | -1.55 | UCSD_109 |
| Patient recovery & transfer | 23 | 121 | 1.25 | 2.33 | -1.08 | UCSD_109 |
| Initialization | 27 | 140 | 4.61 | 5.14 | -0.53 | UCSD_109 |
| TULSA QA | 27 | 140 | 42.27 | 26.28 | 15.99 | Stanford |

## Top UCSD-Faster States

| state | ucsd_median_min | stanford_median_min | delta_min_ucsd_minus_stanford |
| --- | --- | --- | --- |
| Room ready | 23.99 | 61.88 | -37.89 |
| Detailed | 18.60 | 56.01 | -37.40 |
| Coarse | 11.23 | 35.33 | -24.09 |
| Treating | 49.99 | 73.71 | -23.72 |
| Post-treatment scans & Device removal | 23.40 | 46.22 | -22.82 |
| Patient positioning & induction | 23.50 | 42.00 | -18.50 |
| Paused | 7.43 | 20.16 | -12.73 |
| Device insertion | 27.90 | 32.17 | -4.27 |

## Top Stanford-Faster States

| state | ucsd_median_min | stanford_median_min | delta_min_ucsd_minus_stanford |
| --- | --- | --- | --- |
| TULSA QA | 42.27 | 26.28 | 15.99 |

## Notes

- Durations are from `state_intervals.duration_sec`, aggregated to per-case totals per state, then summarized by site.
- Empty/`<NA>` state rows are excluded from efficiency metrics.
- The plotted comparison uses anonymized labels (`Site A`/`Site B`), but the mapping is listed above for internal interpretation.
- This is descriptive comparison only; no case-mix adjustment is applied.
