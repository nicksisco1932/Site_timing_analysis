@echo off
setlocal enabledelayedexpansion

REM -------------------------------------------------------------
REM STEP: State duration summary stats (mean/median/std per state)
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
echo   STATE DURATION STATS
echo   Site:    %SITE%
echo   Date:    %DATE%
echo   Analysis dir: %ANALYSIS_DIR%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_state_stats.py" ^
    --site %SITE% ^
    --analysis-root "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: State stats generation failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo State stats complete.
endlocal
