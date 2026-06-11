# Yale vs Stanford Efficiency Comparison (State Intervals)

## Data Sources
- Yale_065: `C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis\run_outputs_yale_065_20260312\state_intervals`
- Stanford: `C:\Users\NicholasSisco\Documents\GitHub\Site_timing_analysis\run_outputs_broader_next\state_intervals`

## Dataset Coverage

| site | interval_files | interval_rows |
| --- | --- | --- |
| Yale_065 | 63 | 11039 |
| Stanford | 140 | 42776 |

## Case-Level Total Workflow Time (valid states only)

| site | cases | median_min | mean_min | std_min | min_min | max_min |
| --- | --- | --- | --- | --- | --- | --- |
| Stanford | 140 | 460.56 | 475.54 | 112.85 | 294.81 | 824.22 |
| Yale_065 | 63 | 286.19 | 302.06 | 72.35 | 180.62 | 507.48 |

## Per-State Median Duration Comparison (states with >=10 cases at both sites)

| state | yale_cases | stanford_cases | yale_median_min | stanford_median_min | delta_min_yale_minus_stanford | faster_site_by_median |
| --- | --- | --- | --- | --- | --- | --- |
| Post-treatment scans & Device removal | 62 | 137 | 19.80 | 46.22 | -26.43 | Yale |
| Detailed | 63 | 140 | 32.43 | 56.01 | -23.58 | Yale |
| Coarse | 63 | 140 | 14.59 | 35.33 | -20.74 | Yale |
| Room ready | 63 | 140 | 43.91 | 61.88 | -17.97 | Yale |
| Patient positioning & induction | 56 | 129 | 26.00 | 42.00 | -16.00 | Yale |
| Device insertion | 55 | 128 | 19.60 | 32.17 | -12.57 | Yale |
| Paused | 63 | 140 | 8.89 | 20.16 | -11.26 | Yale |
| TULSA QA | 63 | 140 | 20.52 | 26.28 | -5.77 | Yale |
| Planning start angle | 63 | 140 | 3.34 | 6.15 | -2.81 | Yale |
| Alignment | 63 | 140 | 3.50 | 5.88 | -2.38 | Yale |
| Patient recovery & transfer | 42 | 121 | 0.00 | 2.33 | -2.33 | Yale |
| Initialization | 63 | 140 | 4.24 | 5.14 | -0.90 | Yale |
| Treating | 63 | 140 | 74.44 | 73.71 | 0.72 | Stanford |

## Top Yale-Faster States

| state | yale_median_min | stanford_median_min | delta_min_yale_minus_stanford |
| --- | --- | --- | --- |
| Post-treatment scans & Device removal | 19.80 | 46.22 | -26.43 |
| Detailed | 32.43 | 56.01 | -23.58 |
| Coarse | 14.59 | 35.33 | -20.74 |
| Room ready | 43.91 | 61.88 | -17.97 |
| Patient positioning & induction | 26.00 | 42.00 | -16.00 |
| Device insertion | 19.60 | 32.17 | -12.57 |
| Paused | 8.89 | 20.16 | -11.26 |
| TULSA QA | 20.52 | 26.28 | -5.77 |

## Top Stanford-Faster States

| state | yale_median_min | stanford_median_min | delta_min_yale_minus_stanford |
| --- | --- | --- | --- |
| Treating | 74.44 | 73.71 | 0.72 |

## Notes

- Durations are from `state_intervals.duration_sec`, aggregated to per-case totals per state, then summarized by site.
- Empty/`<NA>` state rows are excluded from efficiency metrics.
- This is descriptive comparison only; no case-mix adjustment is applied.
