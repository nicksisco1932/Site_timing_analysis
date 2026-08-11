@echo off
setlocal enabledelayedexpansion

REM Project: Site Timing Analysis
REM File: run_Stanford_064.bat
REM Primary author: Nicholas J. Sisco, Ph.D.
REM Organization: Profound Medical, LLC
REM Created: 2026-03-03
REM Purpose: Runs the run Stanford 064 timing-analysis workflow from Windows batch.
REM
REM Provenance: Original implementation or material contribution by
REM Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
REM
REM Rights status: Proprietary / internal use unless otherwise specified
REM by Profound Medical, LLC.
REM ------------------------------------------------------------------
REM Site timing pipeline (delegates to tulsa_site_pipeline.py)
REM ------------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set YEARS=All
set DATE=2025.11.19

REM Repo root (folder where this .bat lives)
set REPO_ROOT=%~dp0
set ANALYSIS_ROOT=%REPO_ROOT%outputs\timing_gantt

REM Python in your venv
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

echo.
echo ================================================================
echo   TULSA SITE TIMING PIPELINE (Python)
echo   Site:       %SITE%
echo   Years:      %YEARS%
echo   Date:       %DATE%
echo   Output dir: %ANALYSIS_ROOT%\%DATE%_%SITE%_timing_Gantt
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_site_pipeline.py" ^
    --site %SITE% ^
    --site-label %SITE_LABEL% ^
    --years %YEARS% ^
    --date %DATE% ^
    --analysis-root "%ANALYSIS_ROOT%" ^
    --trend-with-gantt

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Pipeline failed. See messages above.
    echo ********************************************************
    exit /b 1
)

echo.
echo Pipeline finished successfully.
endlocal
