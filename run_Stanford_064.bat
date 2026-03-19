@echo off
setlocal enabledelayedexpansion

REM ------------------------------------------------------------------
REM Site timing pipeline (delegates to tulsa_site_pipeline.py)
REM ------------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set YEARS=All
set DATE=2025.11.19

set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis

REM Repo root (folder where this .bat lives)
set REPO_ROOT=%~dp0

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
