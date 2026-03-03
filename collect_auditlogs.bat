@echo off
setlocal enabledelayedexpansion

REM -------------------------------------------------------------
REM STEP 1: Collect AuditLogRecords into auditlogs_<site>.csv
REM -------------------------------------------------------------

set SITE=Stanford_064
set SITE_LABEL=Stanford
set YEARS=All
set DATE=20251119

set ANALYSIS_ROOT=C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis

REM Repo root (folder where this .bat lives)
set REPO_ROOT=%~dp0

REM Python in your venv
set PYTHON=%REPO_ROOT%.venv\Scripts\python.exe

REM Output directory for this analysis day/site
set OUTDIR=%ANALYSIS_ROOT%\%DATE%_%SITE_LABEL%

echo.
echo ================================================================
echo   STEP 1: COLLECT AUDITLOGS
echo   Site:    %SITE%
echo   Years:   %YEARS%
echo   Date:    %DATE%
echo   OutDir:  %OUTDIR%
echo ================================================================
echo.

"%PYTHON%" "%REPO_ROOT%tulsa_collect_auditlogs.py" ^
    --site %SITE% ^
    --years %YEARS% ^
    --outdir "%OUTDIR%"

REM If you ever want to override the default timing root, add:
REM   --root "C:\Users\NicholasSisco\Profound Medical" ^
REM   --timing-subdir "Clinical Science Team - Genius Services\Timing Data" ^

if errorlevel 1 (
    echo.
    echo ********************************************************
    echo   ERROR: Auditlog collection failed.
    echo ********************************************************
    exit /b 1
)

echo.
echo Auditlog collection complete.
endlocal
