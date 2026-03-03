@echo off
setlocal

REM --- CONFIGURE THESE THREE LINES PER RUN ---
set SITE=Stanford_064
set YEARS=All
set OUTDIR=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis\20251118_Stanford

REM --- Activate venv if needed ---
call .\.venv\Scripts\activate

echo.
echo ==== STEP 1: Collect raw AuditLogRecords ====
python tulsa_collect_auditlogs.py ^
    --site %SITE% ^
    --years %YEARS% ^
    --outdir "%OUTDIR%"

echo.
echo ==== STEP 2: Add workflow states and durations ====
python tulsa_state_machine.py ^
    --infile "%OUTDIR%\auditlogs_%SITE%.csv" ^
    --outdir "%OUTDIR%"

echo.
echo ==== STEP 3: Build timing summary ====
python tulsa_case_summary.py ^
    --infile "%OUTDIR%\auditlogs_%SITE%_states.csv" ^
    --outdir "%OUTDIR%"

echo.
echo Done.
endlocal
