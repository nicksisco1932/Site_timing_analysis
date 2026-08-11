@echo off
setlocal enabledelayedexpansion

REM Project: Site Timing Analysis
REM File: build_timing_summary.bat
REM Primary author: Nicholas J. Sisco, Ph.D.
REM Organization: Profound Medical, LLC
REM Created: 2026-03-03
REM Purpose: Runs the build timing summary timing-analysis workflow from Windows batch.
REM
REM Provenance: Original implementation or material contribution by
REM Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
REM
REM Rights status: Proprietary / internal use unless otherwise specified
REM by Profound Medical, LLC.
REM -------------------------------------------------------------
REM STEP 3: Build timing summary
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
echo   STEP 3: BUILD TIMING SUMMARY
echo   Site:    %SITE%
echo   Date:    %DATE%
echo   States:  %STATES%
echo   OutDir:  %ANALYSIS_DIR%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_build_timing_summary.py" ^
    --states-csv "%STATES%" ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Timing summary stage failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo Timing summary complete.
endlocal
