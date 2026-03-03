@echo off
setlocal enabledelayedexpansion

REM -------------------------------------------------------------
REM STEP: State duration histograms from timing_summary_<site>.csv
REM -------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set DATE=20251119

set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis
set REPO_ROOT=%~dp0
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

set ANALYSIS_DIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%

echo.
echo ================================================================
echo   STATE DURATION HISTOGRAMS
echo   Site:    %SITE%
echo   Date:    %DATE%
echo   Analysis dir: %ANALYSIS_DIR%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_state_histograms.py" ^
    --site %SITE% ^
    --analysis-root "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: State histogram generation failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo State histograms complete.
endlocal
