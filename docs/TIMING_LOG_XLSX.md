# Supplemental Timing-Log XLSX Contract

## Purpose

This document records the read-only matching and parsing contract for the
supplemental treatment timing workbooks stored outside the repository. These
workbooks enrich the event stream when an exact case match exists; they are not
required for a case to be processed.

## Source audit (2026-08-17)

The audited source directory was:

```text
C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - Timing Data\TimingLogs
```

The directory contained 1,138 `.xlsx` files. Of those, 1,119 had a canonical
case-like filename and 19 did not match the canonical filename pattern. The
noncanonical set includes templates, summaries, and several separator variants;
these are intentionally not matched by fuzzy normalization.

The reference UCLA run
`outputs\timing_gantt\2026.08.11_UCLA_008_timing_Gantt` contained 74 cases with
state intervals. Exact filename comparison found:

- 7 cases with a matching `<case_id>.xlsx` workbook;
- 67 run cases without a matching workbook; and
- 1 UCLA workbook without a corresponding case in that run.

The source is therefore not one-to-one with the other case data. Missing
workbooks must remain recoverable and visible rather than becoming a run-stopping
condition.

## Matching rules

1. The pipeline looks only for exact `<case_id>.csv` and `<case_id>.xlsx`
   filenames in the selected timing-log directory.
2. No separator repair, prefix inference, or other fuzzy filename matching is
   performed.
3. No match produces a `timing_log_missing` case warning and processing
   continues.
4. Both an exact CSV and exact XLSX for one case are ambiguous and fail that
   case explicitly instead of selecting one silently.
5. A present but malformed workbook fails explicitly at the timing-log parser
   boundary. Source files are opened for reading and are never saved or changed.

## Workbook schema

The parser locates exactly one worksheet containing one header row with the
case-insensitive column names `EVENT`, `START`, and `END`. The columns may be
positioned anywhere within the bounded header scan; the representative files
use the `TimingLog` worksheet and columns D through F.

Rows below the header become the existing `TimingLogEntry` contract:

- `EVENT` becomes the source label;
- `START` becomes the optional start timestamp; and
- `END` becomes the optional end timestamp.

Excel time-only values are combined with the treatment date from the earliest
normalized database event for that case. A clock regression greater than 12
hours is treated as an overnight rollover and is reported. A time-only workbook
cannot be used without a treatment-date anchor.

## Representative validation

`008_01-208.xlsx` contains 23 timing rows in its `TimingLog` event table. Five
currently mapped labels provide usable timestamps and produce seven synthetic
events:

- `AnesthesiaStart`
- `Ready4Urology`
- `DeviceInsertionBegins`
- `DeviceInsertionEnds`
- `InitialImaging`
- `PatientTransferBegins`
- `PatientTransferEnds`

Unmapped labels remain visible as enrichment warnings. This preserves the
current explicit mapping boundary and avoids assigning unsupported clinical
meaning to workbook labels.

## Operator use

Pass the shared directory explicitly to either pipeline entry point:

```powershell
.\.venv\Scripts\python.exe scripts\run_timeline_analysis.py `
  --site "UCLA_008" `
  --site-root "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - UCLA_008" `
  --canonical-prefix "008_" `
  --timing-log-dir "C:\Users\NicholasSisco\Profound Medical\Clinical Science Team - Timing Data\TimingLogs" `
  --run-dir ".\outputs\timing_gantt\<fresh-run-directory>"
```

The run manifest records the selected timing-log path, parsed entry count,
synthetic event count, and enrichment warnings for each case.
