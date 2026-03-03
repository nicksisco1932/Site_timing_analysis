@echo off
setlocal enabledelayedexpansion

REM -------------------------------------------------------------
REM STEP 4: Time sanity check (clock + noon/multi-day)
REM -------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set DATE=20251119

set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis
set REPO_ROOT=%~dp0
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

set ANALYSIS_DIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%
set STATES=%ANALYSIS_DIR%\auditlogs_%SITE%_states.csv

echo.
echo ================================================================
echo   STEP 4: TIME SANITY CHECK
echo   Site:    %SITE%
echo   Date:    %DATE%
echo   States:  %STATES%
echo   OutDir:  %ANALYSIS_DIR%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_time_sanity.py" ^
    --states-csv "%STATES%" ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Time sanity stage failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo Time sanity complete.
endlocal
