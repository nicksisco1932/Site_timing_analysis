@echo off
setlocal enabledelayedexpansion

REM -------------------------------------------------------------
REM STEP 2: Apply state machine + durations
REM -------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set DATE=20251119

set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis
set REPO_ROOT=%~dp0
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

set ANALYSIS_DIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%
set INFILE=%ANALYSIS_DIR%\auditlogs_%SITE%.csv

echo.
echo ================================================================
echo   STEP 2: STATE MACHINE
echo   Site:    %SITE%
echo   Date:    %DATE%
echo   Input:   %INFILE%
echo   OutDir:  %ANALYSIS_DIR%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_state_machine.py" ^
    --infile "%INFILE%" ^
    --outdir "%ANALYSIS_DIR%"

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: State machine stage failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo State machine stage complete.
endlocal
