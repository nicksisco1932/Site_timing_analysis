@echo off
setlocal

REM Project: Site Timing Analysis
REM File: testing/run_site_analysis.bat
REM Primary author: Nicholas J. Sisco, Ph.D.
REM Organization: Profound Medical, LLC
REM Created: 2026-03-03
REM Purpose: Runs the run site analysis timing-analysis workflow from Windows batch.
REM
REM Provenance: Original implementation or material contribution by
REM Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
REM
REM Rights status: Proprietary / internal use unless otherwise specified
REM by Profound Medical, LLC.
REM --- CONFIGURE THESE THREE LINES PER RUN ---
set SITE=Stanford_064
set YEARS=All
set OUTDIR=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis\20251118_Stanford

set REPO_ROOT=%~dp0..\
set PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe

echo.
echo ==== STEP 1: Collect raw AuditLogRecords ====
"%PYTHON%" "%REPO_ROOT%tulsa_collect_auditlogs.py" ^
    --site %SITE% ^
    --years %YEARS% ^
    --outdir "%OUTDIR%"

echo.
echo ==== STEP 2: Add workflow states and durations ====
"%PYTHON%" "%REPO_ROOT%tulsa_state_machine.py" ^
    --infile "%OUTDIR%\auditlogs_%SITE%.csv" ^
    --outdir "%OUTDIR%"

echo.
echo ==== STEP 3: Build timing summary ====
"%PYTHON%" "%~dp0tulsa_case_summary.py" ^
    --infile "%OUTDIR%\auditlogs_%SITE%_states.csv" ^
    --outdir "%OUTDIR%"

echo.
echo Done.
endlocal
