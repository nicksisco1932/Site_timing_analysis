@echo off
setlocal enabledelayedexpansion

REM ===================================================================
REM ONE-CLICK FULL TULSA SITE PIPELINE
REM Includes:
REM   1) Collect AuditLogs
REM   2) State Machine + Timebase
REM   3) Timing Summary
REM   4) Time Sanity (Clock Integrity)
REM ===================================================================

REM ------------------ CONFIGURE YOUR RUN HERE -------------------------
set SITE=Stanford_064
set SITE_LABEL=Stanford
set YEARS=All
set DATE=20251119

REM Analysis root
set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis

REM Repo root (folder where this .bat lives)
set REPO_ROOT=%~dp0

REM Python in venv
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

REM Output working directory
set ANALYSIS_DIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%
REM ===================================================================



echo.
echo ================================================================
echo   FULL TULSA SITE PIPELINE
echo   Site:        %SITE%
echo   Label:       %SITE_LABEL%
echo   Years:       %YEARS%
echo   Date:        %DATE%
echo   Output Dir:  %ANALYSIS_DIR%
echo ================================================================
echo.


REM -------------------------------------------------------------
REM STEP 1: COLLECT AUDITLOGS
REM -------------------------------------------------------------

echo.
echo ============================
echo   STEP 1: COLLECT AUDITLOGS
echo ============================

"%PYTHON%" "%REPO_ROOT%tulsa_collect_auditlogs.py" ^
    --site %SITE% ^
    --years %YEARS% ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Failed during AUDITLOG COLLECTION
    echo ********************************************************
    exit /b 1
)

echo Auditlog collection complete.



REM -------------------------------------------------------------
REM STEP 2: STATE MACHINE + TIMEBASE
REM -------------------------------------------------------------

echo.
echo ============================
echo   STEP 2: STATE MACHINE
echo ============================

set INFILE=%ANALYSIS_DIR%\auditlogs_%SITE%.csv

"%PYTHON%" "%REPO_ROOT%tulsa_state_machine.py" ^
    --infile "%INFILE%" ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Failed during STATE MACHINE parsing
    echo ********************************************************
    exit /b 1
)

echo State machine stage complete.



REM -------------------------------------------------------------
REM STEP 3: TIMING SUMMARY
REM -------------------------------------------------------------

echo.
echo ============================
echo   STEP 3: TIMING SUMMARY
echo ============================

set STATES=%ANALYSIS_DIR%\auditlogs_%SITE%_states.csv

"%PYTHON%" "%REPO_ROOT%tulsa_build_timing_summary.py" ^
    --states-csv "%STATES%" ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Failed during TIMING SUMMARY
    echo ********************************************************
    exit /b 1
)

echo Timing summary complete.



REM -------------------------------------------------------------
REM STEP 4: TIME SANITY (Clock + Noon)
REM -------------------------------------------------------------

echo.
echo ============================
echo   STEP 4: TIME SANITY CHECK
echo ============================

"%PYTHON%" "%REPO_ROOT%tulsa_time_sanity.py" ^
    --states-csv "%STATES%" ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Failed during TIME SANITY CHECK
    echo ********************************************************
    exit /b 1
)

echo Time sanity check complete.



echo.
echo ================================================================
echo   FULL PIPELINE COMPLETED SUCCESSFULLY
echo   Output: %ANALYSIS_DIR%
echo ================================================================
echo.

endlocal
exit /b 0
