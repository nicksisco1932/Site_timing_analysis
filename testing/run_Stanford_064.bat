@echo off
setlocal enabledelayedexpansion

REM ------------------------------------------------------------------
REM Site timing pipeline for Stanford_064
REM 1) Collect AuditLogRecords from local.db
REM 2) Map to workflow states + durations
REM 3) Build per-patient timing summary (with outlier filter)
REM 4) Generate plots (per-patient, distributions, Gantt) into /plots
REM ------------------------------------------------------------------

REM --- Configurable bits ---
set SITE=Stanford_064
set SITE_LABEL=Stanford
set DATE=20251118

REM Repo root (folder where this .bat lives)
set REPO_ROOT=%~dp0

REM Python in your venv
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

REM Where analysis outputs go
set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis
set OUTDIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%

REM --- Create output folder ---
if not exist "%OUTDIR%" (
    echo Creating output folder: "%OUTDIR%"
    mkdir "%OUTDIR%"
)

echo.
echo ================================================================
echo   TULSA SITE TIMING PIPELINE
echo   Site:       %SITE%
echo   Output dir: %OUTDIR%
echo ================================================================
echo.

REM ===================== STEP 1: COLLECT AUDITLOGS ==================
echo [STEP 1] Collecting AuditLogRecords from local.db...
"%PYTHON%" "%REPO_ROOT%tulsa_collect_auditlogs.py" ^
    --site %SITE% ^
    --outdir "%OUTDIR%"
if errorlevel 1 goto :error

REM Expected output: auditlogs_Stanford_064.csv
set INFILE=%OUTDIR%\auditlogs_%SITE%.csv
echo [STEP 1] Done. Combined CSV:
echo          %INFILE%
echo.

REM ===================== STEP 2: STATE MACHINE ======================
echo [STEP 2] Mapping workflow states and durations...
"%PYTHON%" "%REPO_ROOT%tulsa_state_machine.py" ^
    --infile "%INFILE%" ^
    --outdir "%OUTDIR%"
if errorlevel 1 goto :error

REM Expected output: auditlogs_Stanford_064_states.csv
set STATES_CSV=%OUTDIR%\auditlogs_%SITE%_states.csv
echo [STEP 2] Done. State-enriched CSV:
echo          %STATES_CSV%
echo.

REM ===================== STEP 3: TIMING SUMMARY =====================
echo [STEP 3] Building per-patient timing summary (with outlier filter)...
"%PYTHON%" "%REPO_ROOT%tulsa_build_timing_summary.py" ^
    --states-csv "%STATES_CSV%" ^
    --outdir "%OUTDIR%" ^
    --filter-outliers
if errorlevel 1 goto :error

REM Expected output: timing_summary_Stanford_064.csv
set SUMMARY_CSV=%OUTDIR%\timing_summary_%SITE%.csv
echo [STEP 3] Done. Timing summary:
echo          %SUMMARY_CSV%
echo.

REM ===================== STEP 4: PLOTS (incl. GANTT) =================
set PLOTS_DIR=%OUTDIR%\plots
if not exist "%PLOTS_DIR%" (
    echo Creating plots folder: "%PLOTS_DIR%"
    mkdir "%PLOTS_DIR%"
)

echo [STEP 4] Generating plots (stacked per-patient, boxplots, histograms, Gantt)...
"%PYTHON%" "%REPO_ROOT%tulsa_plot_timing.py" ^
    --summary-csv "%SUMMARY_CSV%" ^
    --states-csv "%STATES_CSV%" ^
    --outdir "%PLOTS_DIR%" ^
    --site "%SITE%"
if errorlevel 1 goto :error

echo [STEP 4] Done. Plots written to:
echo          %PLOTS_DIR%
echo.

echo ================================================================
echo   PIPELINE COMPLETE
echo   Summary: %SUMMARY_CSV%
echo   Plots:   %PLOTS_DIR%
echo ================================================================
goto :eof

:error
echo.
echo ********************************************************
echo   ERROR: Pipeline aborted. See messages above.
echo ********************************************************
exit /b 1
